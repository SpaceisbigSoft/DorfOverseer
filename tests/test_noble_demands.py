"""(0.105.41, item 1) The nobles' demands: lua/ai-noble-demands.lua (the
monarch, the land holders, each noble room's value required against its
own, polish_room) in a real Lua engine with a fake game, and
brain/planner_nobles.py (the plan, the rule, the view).

    python tests/test_noble_demands.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

from planner import PLANNER_CONFIG, plan, Memory  # noqa: E402
from planner_nobles import noble_room_plan, nobles_view, _noble_value_rule  # noqa: E402
from digest import normalize, digest  # noqa: E402

SRC = module_src("ai-noble-demands.lua")

FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local G = {zones = {}, units = {}, engravings = {}, mandates = {}, areas = {}, tiles = {}, qf = {}}
env.G = G
env.df = {
    global = {world = {engravings = G.engravings, mandates = {all = G.mandates}}},
    building_type = {Statue = 'Statue', Civzone = 'Civzone', Bed = 'Bed', Table = 'Table'},
    civzone_type = setmetatable({}, {__index = function(_, k) return k end}),
    historical_entity_type = {Civilization = 'Civilization', SiteGovernment = 'SiteGovernment'},
    entity_position_responsibility = {LAW_MAKING = 'LAW_MAKING'},
    building = {find = function(id) for _, z in ipairs(G.zones) do if z.id == id then return z end end end},
}
env.dfhack = {
    units = {getCitizens = function() return G.units end,
             getNoblePositions = function(u) return u.positions end,
             getReadableName = function(u) return 'dwarf ' .. u.id end},
    items = {getValue = function(it) return it.v end},
    buildings = {containsTile = function(z, x, y) return x >= z.x1 and x <= z.x2 and y >= z.y1 and y <= z.y2 end},
}
env.reqscript = function(n)
    if n == 'ai-builder' then
        return {tile_info = function(x, y, z)
                    local t = G.tiles[x .. ',' .. y .. ',' .. z]
                    if t then return {shape = t.shape, material = t.material, smoothed = t.smoothed} end
                    return nil
                end,
                level_areas = function() return G.areas end,
                quickfort_apply = function(mode, cells, z, ax, ay)
                    table.insert(G.qf, {mode = mode, cells = cells, z = z, ax = ax, ay = ay})
                    return {dig_designated = {value = #cells}}
                end}
    end
    error('reqscript ' .. n)
end
assert(load(src, 'ai-noble-demands', 't', env))()
return env
"""


def game():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, SRC)
    return lua, env


def lt(lua, v):
    if isinstance(v, dict):
        return lua.table_from({k: lt(lua, x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return lua.table_from([lt(lua, x) for x in v])
    return v


def add(lua, env, where, v):
    t = env.G[where]
    t[len(t) + 1] = v if not isinstance(v, (dict, list)) else lt(lua, v)
    return t[len(t)]


def position(lua, code, entity="SiteGovernment", land_holder=0, law=False, **req):
    p = {"code": code, "name": {0: code.lower()}, "land_holder": land_holder,
         "responsibilities": {"LAW_MAKING": law}}
    p.update(req)
    return lt(lua, {"position": p, "entity": {"id": 5, "type": entity}})


def zone(lua, env, zid, kind, x1, y1, x2, y2, z=10, items=(), statues=0, unbuilt=0):
    bs = [{"t": "Statue", "items": [{"item": {"v": 100}}]} for _ in range(statues)]
    bs += [{"t": "Statue", "items": [], "unbuilt": True} for _ in range(unbuilt)]
    bs.append({"t": "Table", "items": [{"item": {"v": v}} for v in items]})
    blds = []
    for b in bs:
        bt = lt(lua, {"contained_items": b["items"]})
        kind_ = b["t"]
        lua.execute("local b, k = ...; b.getType = function() return k end", bt, kind_)
        if b.get("unbuilt"):
            lua.execute("local b = ...; b.getBuildStage = function() return 0 end; "
                        "b.getMaxBuildStage = function() return 1 end", bt)
        blds.append(bt)
    zt = lt(lua, {"id": zid, "type": kind, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "z": z})
    zt.contained_buildings = lua.table_from(blds)
    lua.execute("local b = ...; b.getType = function() return 'Civzone' end", zt)
    add(lua, env, "zones", zt)
    return zt


def unit(lua, env, uid, positions, owned=()):
    u = lua.table_from({"id": uid, "positions": lua.table_from(positions), "owned_buildings": lua.table_from(list(owned))})
    add(lua, env, "units", u)
    return u


# --- the Lua: pure -------------------------------------------------------------

@test("demands: the most of each kind over a noble's offices; storage too")
def _():
    lua, env = game()
    need, store = env.demands_of(lt(lua, [{"required": {"office": 100, "bedroom": 50}, "storage": {"boxes": 2}},
                                          {"required": {"office": 2500, "tomb": 3}}]))
    assert (need.office, need.bedroom, need.tomb, need.dining) == (2500, 50, 3, None)
    assert store.boxes == 2


@test("titles: the monarch above all; else the highest land holder (baron, count, duke)")
def _():
    lua, env = game()
    assert env.title_of(lt(lua, [{"land_holder": 1}, {"land_holder": 3}])) == "duke"
    assert env.title_of(lt(lua, [{"land_holder": 2}, {"monarch": True}])) == "monarch"
    assert env.title_of(lt(lua, [{}])) is None


@test("polish: natural rock smoothed first, smooth rock not yet engraved after; never soil, a job, a corridor's floor")
def _():
    lua, env = game()
    tiles = lt(lua, [{"x": 1, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "smoothed": False},
                     {"x": 2, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "smoothed": True},
                     {"x": 3, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "smoothed": True},
                     {"x": 4, "y": 1, "z": 9, "shape": "FLOOR", "material": "SOIL", "smoothed": False},
                     {"x": 5, "y": 1, "z": 9, "shape": "WALL", "material": "MINERAL", "smoothing": True},
                     {"x": 6, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "ring": True},
                     {"x": 7, "y": 1, "z": 9, "shape": "WALL", "material": "STONE", "ring": True}])
    sm, en, pend = env.polish_split(tiles, lt(lua, {"3,1,9": {"q": 0}}))
    assert sorted(sm[i].x for i in range(1, len(sm) + 1)) == [1, 7]
    assert [en[i].x for i in range(1, len(en) + 1)] == [2]
    assert pend == 1                      # the wall being smoothed: polish still under way


@test("polish: tiles designated or under a smoothing/engraving job count as pending; soil and a corridor's floor not")
def _():
    lua, env = game()
    tiles = lt(lua, [{"x": 1, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "smoothing": True},
                     {"x": 2, "y": 1, "z": 9, "shape": "WALL", "material": "STONE", "smoothed": True, "polish_job": True},
                     {"x": 3, "y": 1, "z": 9, "shape": "FLOOR", "material": "SOIL", "smoothing": True},
                     {"x": 4, "y": 1, "z": 9, "shape": "FLOOR", "material": "STONE", "ring": True, "smoothing": True}])
    sm, en, pend = env.polish_split(tiles, lt(lua, {}))
    assert len(sm) == 0 and len(en) == 0 and pend == 2, pend


@test("inside_areas: a zone is the AI's when its middle is in one of its levels on that z")
def _():
    lua, env = game()
    areas = lt(lua, [{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "z": 5}])
    assert env.inside_areas(lt(lua, {"x1": 2, "y1": 2, "x2": 4, "y2": 4, "z": 5}), areas)
    assert not env.inside_areas(lt(lua, {"x1": 2, "y1": 2, "x2": 4, "y2": 4, "z": 6}), areas)
    assert not env.inside_areas(lt(lua, {"x1": 20, "y1": 2, "x2": 24, "y2": 4, "z": 5}), areas)


# --- the Lua: the report -------------------------------------------------------

def fort(lua, env):
    """A duke with an office worth 300 + engravings, no bedroom; a monarch
    (the capital) with a bedroom; a manager whose office asks 1."""
    off = zone(lua, env, 101, "Office", 10, 10, 12, 12, items=(200, 100))
    bed = zone(lua, env, 102, "Bedroom", 20, 10, 21, 11, items=(5000,), statues=2)
    mo = zone(lua, env, 103, "Office", 30, 10, 31, 10, items=(10,))
    add(lua, env, "engravings", {"pos": {"x": 11, "y": 11, "z": 10}, "quality": 5, "flags": {"floor": True}})
    add(lua, env, "engravings", {"pos": {"x": 13, "y": 11, "z": 10}, "quality": 0, "flags": {"floor": False}})
    add(lua, env, "engravings", {"pos": {"x": 9, "y": 11, "z": 10}, "quality": 0, "flags": {"floor": True}})
    add(lua, env, "engravings", {"pos": {"x": 11, "y": 11, "z": 99}, "quality": 5, "flags": {"floor": True}})
    add(lua, env, "areas", {"x1": 0, "y1": 0, "x2": 15, "y2": 15, "z": 10})
    for x in range(10, 13):
        for y in range(10, 13):
            env.G.tiles[f"{x},{y},10"] = lt(lua, {"shape": "FLOOR", "material": "STONE", "smoothed": (x, y) != (10, 10)})
    duke = unit(lua, env, 1, [position(lua, "DUKE", land_holder=3, required_office=2500, required_bedroom=2500,
                                       required_boxes=4)], [off])
    king = unit(lua, env, 2, [position(lua, "MONARCH", entity="Civilization", law=True, required_bedroom=10000,
                                       required_office=10000)], [bed])
    unit(lua, env, 3, [position(lua, "MANAGER", required_office=1)], [mo])
    unit(lua, env, 4, [position(lua, "BROKER")])          # asks nothing: not listed
    unit(lua, env, 5, [])
    add(lua, env, "mandates", {"unit": duke})
    add(lua, env, "mandates", {"unit": king})
    add(lua, env, "mandates", {"unit": duke})
    return duke, king


def rooms_of(n):
    return {n.rooms[i].kind: n.rooms[i] for i in range(1, len(n.rooms) + 1)}


@test("survey: titles, the capital, each room's need against its value (items + engravings), AI-built, polish left")
def _():
    lua, env = game()
    fort(lua, env)
    r = env.survey()
    assert r.capital is True and r.monarch == "dwarf 2"
    assert len(r.land_holders) == 1 and r.land_holders[1].title == "duke"
    ns = {r.nobles[i].unit_id: r.nobles[i] for i in range(1, len(r.nobles) + 1)}
    assert set(ns) == {1, 2, 3}, set(ns)
    d = ns[1]
    assert d.title == "duke" and d.land_holder == 3 and d.mandates == 2 and d.storage.boxes == 4
    rd = rooms_of(d)
    # 300 of furniture; inside a masterful (100) engraving; the wall beside (10); a corridor's floor not
    assert rd["office"].zone_id == 101 and rd["office"].value == 410, rd["office"].value
    assert rd["office"].need == 2500 and rd["office"].ai_built is True
    assert rd["office"].smooth_left == 1 and rd["office"].engrave_left == 7, (rd["office"].smooth_left, rd["office"].engrave_left)
    assert rd["bedroom"].zone_id is None and rd["bedroom"].need == 2500
    k = ns[2]
    assert k.monarch and k.title == "monarch" and k.mandates == 1
    rk = rooms_of(k)
    assert rk["bedroom"].value == 5200 and rk["bedroom"].statues == 2 and rk["bedroom"].ai_built is None
    assert rk["bedroom"].smooth_left is None          # the player's room: never polished
    assert rk["office"].zone_id is None
    assert rooms_of(ns[3])["office"].value == 10 and ns[3].title is None


@test("survey: a statue placed and not built is counted as the room's and as pending; a smoothing job as polish pending")
def _():
    lua, env = game()
    fort(lua, env)
    z = zone(lua, env, 104, "Bedroom", 40, 10, 41, 11, items=(10,), statues=1, unbuilt=1)
    unit(lua, env, 6, [position(lua, "BARON", land_holder=1, required_bedroom=5000)], [z])
    env.polish_jobs = lua.eval("function() return {['12,12,10'] = true} end")
    r = env.survey()
    ns = {r.nobles[i].unit_id: r.nobles[i] for i in range(1, len(r.nobles) + 1)}
    b = rooms_of(ns[6])["bedroom"]
    assert b.statues == 2 and b.statues_pending == 1, (b.statues, b.statues_pending)
    assert rooms_of(ns[2])["bedroom"].statues_pending is None      # built statues: none pending
    o = rooms_of(ns[1])["office"]
    assert o.polish_pending == 1 and o.engrave_left == 6, (o.polish_pending, o.engrave_left)


@test("survey: no nobles -> an empty list, not the capital")
def _():
    lua, env = game()
    unit(lua, env, 1, [])
    r = env.survey()
    assert len(r.nobles) == 0 and r.capital is False


@test("polish_room: smooths first, engraves once smooth; refuses the player's rooms and a zone gone; dry run")
def _():
    lua, env = game()
    fort(lua, env)
    r = env.polish_room(101, True)
    assert r.ok and r.step == "smooth" and r.tiles == 1 and r.dry_run and len(env.G.qf) == 0
    r = env.polish_room(101, False)
    assert r.ok and r.designated == 1 and env.G.qf[1].cells[1].text == "s"
    assert (env.G.qf[1].cells[1].x, env.G.qf[1].cells[1].y, env.G.qf[1].ax) == (0, 0, 10)
    env.G.tiles["10,10,10"].smoothed = True
    r = env.polish_room(101, False)
    assert r.ok and r.step == "engrave" and env.G.qf[2].cells[1].text == "e" and r.tiles == 8
    r = env.polish_room(102, False)
    assert not r.ok and r.rejected and "not in a level the AI dug" in r.error
    r = env.polish_room(999, False)
    assert not r.ok and r.rejected


# --- the brain -----------------------------------------------------------------

def state(**kw):
    s = normalize({})
    s["settings"] = {"traits": {"deference": 0}}
    s["noble_demands"] = {
        "capital": True, "monarch": "Urist, king",
        "land_holders": [{"name": "Bomrek, baron", "title": "baron"}],
        "nobles": [
            {"unit_id": 1, "name": "Bomrek, baron", "title": "baron", "positions": ["BARON"], "mandates": 1,
             "rooms": [{"kind": "office", "need": 1000, "zone_id": 11, "value": 400, "statues": 0, "ai_built": True,
                        "smooth_left": 12, "engrave_left": 0},
                       {"kind": "bedroom", "need": 1000, "zone_id": None}]},
            {"unit_id": 2, "name": "Urist, king", "title": "monarch", "positions": ["MONARCH"],
             "rooms": [{"kind": "bedroom", "need": 10000, "zone_id": 21, "value": 2000, "statues": 1},
                       {"kind": "tomb", "need": 10000, "zone_id": 22, "value": 20000, "statues": 0}]},
            {"unit_id": 3, "name": "Kib, manager", "positions": ["MANAGER"],
             "rooms": [{"kind": "office", "need": 1, "zone_id": 31, "value": 0, "statues": 0}]},
        ]}
    s["supplies"] = {"statues": 1}
    s.update(kw)
    return s


def by(plan_, uid, kind):
    return next(e for e in plan_ if e["unit_id"] == uid and e["kind"] == kind)


@test("plan: the monarch first; a free statue to the highest noble's room, then smoothing, then statues ordered")
def _():
    p = noble_room_plan(state(), PLANNER_CONFIG)
    assert p[0]["unit_id"] == 2
    assert by(p, 2, "bedroom")["action"] == {"type": "place_in_zone", "zone_id": 21, "what": "statue"}
    assert by(p, 2, "tomb")["status"] == "ok"
    assert by(p, 1, "office")["action"] == {"type": "polish_room", "zone_id": 11}
    assert by(p, 1, "bedroom")["status"] == "missing"
    o = by(p, 3, "office")
    assert o["action"]["type"] == "work_order" and o["action"]["recipe"] == "stone_statue" and o["is_order"]


@test("plan: engraving once smooth; a statue cap reached and nothing to engrave: wants finer furniture")
def _():
    s = state()
    s["supplies"] = {"statues": 0}
    s["orders"] = [{"recipe": "stone_statue", "amount_left": 3, "amount_total": 3, "by_ai": True}]
    r = s["noble_demands"]["nobles"][0]["rooms"][0]
    r.update(smooth_left=0, engrave_left=9)
    s["noble_demands"]["nobles"][1]["rooms"][0]["statues"] = PLANNER_CONFIG["noble_room_statues_max"]
    p = noble_room_plan(s, PLANNER_CONFIG)
    assert by(p, 1, "office")["action"] == {"type": "polish_room", "zone_id": 11} and "engraved" in by(p, 1, "office")["plan"]
    assert by(p, 2, "bedroom")["action"] is None and by(p, 2, "bedroom")["plan"].startswith("wants finer")
    assert by(p, 3, "office")["action"] is None and "once one is made" in by(p, 3, "office")["plan"]


@test("plan: a statue placed and not built yet: no second statue (nor for another room), no order; polish still goes on")
def _():
    s = state()
    s["supplies"] = {"statues": 1}          # the report still counts the placed statue free
    s["noble_demands"]["nobles"][1]["rooms"][0]["statues_pending"] = 1
    p = noble_room_plan(s, PLANNER_CONFIG)
    b = by(p, 2, "bedroom")
    assert b["action"] is None and "being put in" in b["plan"], b
    o = by(p, 3, "office")                  # the free count is that same statue: not given to the manager
    assert o["action"] is None or o["action"]["type"] != "place_in_zone", o
    s["noble_demands"]["nobles"][0]["rooms"][0]["statues_pending"] = 1
    assert by(noble_room_plan(s, PLANNER_CONFIG), 1, "office")["action"] == {"type": "polish_room", "zone_id": 11}
    # day after day while it stands unbuilt: the rule never places another
    for _ in range(3):
        props = []
        _noble_value_rule(s, PLANNER_CONFIG, props, [])
        assert not any(x.action.get("type") == "place_in_zone" for x in props), props


@test("plan: smoothing or engraving under way: the room waits, no statues ordered, no second designation")
def _():
    s = state()
    s["supplies"] = {"statues": 0}
    s["noble_demands"]["nobles"] = s["noble_demands"]["nobles"][:1]       # the baron alone
    r = s["noble_demands"]["nobles"][0]["rooms"][0]
    r.update(smooth_left=0, engrave_left=0, polish_pending=12)
    o = by(noble_room_plan(s, PLANNER_CONFIG), 1, "office")
    assert o["action"] is None and "being smoothed or engraved (12" in o["plan"], o
    r.update(polish_pending=0)
    o = by(noble_room_plan(s, PLANNER_CONFIG), 1, "office")
    assert o["action"] and o["action"]["type"] == "work_order", o


@test("rule: held while a threat can reach the dwarves or a siege is on")
def _():
    for extra in ({"others_on_map": {"threats_that_can_reach_dwarves": 2}},
                  {"world": {"sieges": [{"active": True}]}}):
        s = state()
        s.update(extra)
        props = []
        _noble_value_rule(s, PLANNER_CONFIG, props, [])
        assert not props, (extra, props)
    s = state(others_on_map={"threats_that_can_reach_dwarves": 0})
    props = []
    _noble_value_rule(s, PLANNER_CONFIG, props, [])
    assert len(props) == 1


@test("plan: Deference at its lowest leaves the rooms alone (but the manager's office)")
def _():
    s = state(settings={"traits": {"deference": -150}})
    p = noble_room_plan(s, PLANNER_CONFIG)
    assert by(p, 2, "bedroom")["action"] is None and "Deference" in by(p, 2, "bedroom")["plan"]
    assert by(p, 3, "office")["action"] is not None


@test("rule: one step a cycle, the monarch's room first; a note when a room can go no higher")
def _():
    props, notes = [], []
    _noble_value_rule(state(), PLANNER_CONFIG, props, notes)
    assert len(props) == 1 and props[0].rule == "noble_value"
    assert props[0].action["zone_id"] == 21 and "Urist, king's bedroom is worth 2000 of the 10000" in props[0].reason
    s = state()
    s["supplies"] = {"statues": 0}
    s["noble_demands"]["nobles"] = [s["noble_demands"]["nobles"][1]]
    s["noble_demands"]["nobles"][0]["rooms"][0]["statues"] = 99
    props, notes = [], []
    _noble_value_rule(s, PLANNER_CONFIG, props, notes)
    assert not props and any("finer furniture" in n for n in notes), notes


@test("rule: nothing without the section, or when it failed")
def _():
    props, notes = [], []
    _noble_value_rule(normalize({}), PLANNER_CONFIG, props, notes)
    s = state()
    s["_errors"] = {"noble_demands": "boom"}
    _noble_value_rule(s, PLANNER_CONFIG, props, notes)
    assert not props and not notes


@test("plan(): the rule runs inside the planner on a real fort's report and its proposal comes out")
def _():
    import json
    s = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s["noble_demands"] = state()["noble_demands"]
    s["supplies"] = dict(s.get("supplies") or {}, statues=1)
    props, notes = plan(s, Memory())
    mine = [p for p in props if p.rule == "noble_value"]
    assert len(mine) == 1 and mine[0].action["zone_id"] == 21, (mine, [n for n in notes if "failed" in n])


@test("view: the capital, the land holders, each noble's rooms required vs actual and the plan")
def _():
    lines = nobles_view(state(), PLANNER_CONFIG)
    text = "\n".join(lines)
    assert "the fort is the capital (Urist, king)" in text
    assert "Land holders: Bomrek, baron (baron)" in text
    assert re.search(r"bedroom\s+needs\s+10000\s+has\s+2000\s+under: a statue put in", text), text
    assert "1 mandate" in text and "missing" in text
    assert nobles_view(normalize({}), PLANNER_CONFIG)[0].startswith("  (no noble demands")


@test("digest: the titles and the rooms under value in a line each")
def _():
    d = digest(state())
    assert "TITLES capital (monarch Urist, king); baron Bomrek, baron" in d, d
    assert "NOBLE ROOMS UNDER VALUE" in d and "Urist, king bedroom 2000/10000" in d


@test("bridge: the section, the action (dry run), its label, its cache and the module are registered")
def _():
    hub = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "noble_demands = function() return safe(" in hub
    assert "    polish_room = function(a)" in hub and "'polish_room'," in hub
    assert "'ai-noble-demands'" in hub.split("BRIDGE_MODULES = {")[1].split("}")[0]
    assert "SECTION_CACHE_DAYS.noble_demands = 1" in hub
    over = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert '"polish_room":' in over
    assert "noble_demands" in normalize({})
    assert PLANNER_CONFIG["noble_value_cooldown_ticks"] > 0


finish()
