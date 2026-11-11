"""(0.105.26, features) Two new features:

1. citizens stranded outside (lua/ai-gates.lua stranded_citizens, the
   brain's planner_gates._stranded_rule): reported with how long and why;
   the gates opened when the AI shut them and no enemy is near; a Needs-you
   note when there is no way in; held while enemies are near.
2. cavern openings and forgotten beasts (lua/ai-threats.lua seal_cavern and
   the openings on record, the cavern well's shaft watcher in
   lua/ai-builder-wells.lua, planner_threats._cavern_beasts): every opening
   locked while a great beast is in the caverns, whatever the squads could
   do; not while citizens are down there; opened again after; a cavern
   entrance gets doors straight away.

    python tests/test_fix26_features.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish  # noqa: E402

import planner  # noqa: E402
from planner import Memory, plan  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(**kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["map"]["elevation_offset"] = -100
    s.update(kw)
    return s


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def needs_you(notes):
    return [n for n in notes if n.startswith("[you]")]


ROW = {"id": 7, "name": "Urist", "x": 40, "y": 41, "z": 150, "cause": "lockdown", "by_ai": True,
       "out_ticks": 2400, "out_days": 2, "entrance": {"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173}}


# --- 1. stranded outside: the brain -------------------------------------------------

@test("stranded: shut out by the AI's lockdown, no enemy near: the gates opened; (0.105.33) not while a threat can reach the dwarves (armed; their gate alone, no Needs you)")
def _():
    s = fort()
    s["entrances"]["armed"] = True
    s["entrances"]["stranded"] = [dict(ROW)]
    props, notes = plan(s, Memory())
    p = acts(props, "stranded", "open_gates")
    assert p and p[0].priority == 0 and "Urist" in p[0].reason and "lockdown" in p[0].reason, props
    assert "elevation 50" in p[0].reason, p[0].reason
    # (0.105.33) a threat that can reach the dwarves: open_gates would let it
    # in; the gates are armed and the player told
    s["entrances"]["armed"] = False
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, notes = plan(s, Memory())
    assert not acts(props, "stranded", "open_gates") and acts(props, typ="arm_gates"), props
    assert not [n for n in needs_you(notes) if "Urist" in n], needs_you(notes)   # (0.105.34) nothing waits for the player
    # just out (under ~4 hours): nothing yet
    s["entrances"]["stranded"] = [dict(ROW, out_ticks=50, out_days=0)]
    assert not acts(plan(s, Memory())[0], "stranded")


@test("stranded: held while an enemy is near them or the gate")
def _():
    for k in ("danger_near", "gate_danger"):
        s = fort()
        s["entrances"]["stranded"] = [dict(ROW, **{k: 12})]
        props, notes = plan(s, Memory())
        assert not acts(props, "stranded"), props
        assert any("enemy is 12 tiles away" in n for n in notes), notes
    s = fort()
    s["entrances"]["stranded"] = [dict(ROW, danger_near=200, gate_danger=150)]
    assert acts(plan(s, Memory())[0], "stranded", "open_gates")          # far: opened


@test("stranded: no way back in (collapse, fire): (0.105.35) a plain note with their names and where, a way dug in; no gate opened")
def _():
    s = fort()
    rows = [dict(ROW, id=i, name=f"Dwarf{i}", cause="no_path", by_ai=None, entrance=None) for i in range(7)]
    s["entrances"]["stranded"] = rows
    props, notes = plan(s, Memory())
    assert not acts(props, "stranded"), props
    assert acts(props, "way_in", "dig_way_in"), [(p.rule, p.action) for p in props]
    line = [n for n in notes if "no way back in" in n]
    assert line and "Dwarf0 (x40 y41 elevation 50)" in line[0] and "7 citizen(s)" in line[0] and "2 more" in line[0], line
    assert "the AI digs them a way in" in line[0] and not [n for n in needs_you(notes) if "no way back in" in n], notes
    # (0.105.35) a gate shut, but not by the AI (a raised bridge, a locked door): that entrance opened, no Needs you
    s["entrances"]["stranded"] = [dict(ROW, cause="gate_shut", by_ai=False)]
    props, notes = plan(s, Memory())
    assert [p.action for p in acts(props, "stranded")] == [{"type": "open_entrance", "id": 1}], props
    assert not any("not by the AI" in n for n in needs_you(notes)), notes
    # (0.105.35) down in the caverns behind the AI's gate: their entrance opened when the caverns read
    # safe, else kept shut and said; never a Needs you, never open_gates
    s["entrances"]["stranded"] = [dict(ROW, in_cavern=True)]
    props, notes = plan(s, Memory())
    got = [p.action for p in acts(props, "stranded")]
    assert got == [{"type": "open_entrance", "id": 1, "cavern_ok": True}] or (
        not got and any("keeps that way shut" in n for n in notes)), (got, notes)
    assert not any("down in the caverns" in n for n in needs_you(notes)), notes
    # down in the caverns with no way up at all: kept as Needs you, saying the AI digs none from a cavern
    s["entrances"]["stranded"] = [dict(ROW, in_cavern=True, cause="no_path")]
    props, notes = plan(s, Memory())
    ny = [n for n in needs_you(notes) if "down in the caverns" in n]
    assert not acts(props, "stranded") and ny and "digs no way in from a cavern" in ny[0] and "yourself" not in ny[0], notes


# --- 2. cavern openings: the brain --------------------------------------------------

def cave_fort(threats=None, dangers=None, **kw):
    s = fort(**kw)
    s["threats"] = threats if threats is not None else {"sealed": {}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110,
                              "open_at": {"x": 5, "y": 6, "z": 121},
                              "column": [{"z": 122, "shape": "STAIR_UPDOWN"}]}],
                 "dangers": dangers if dangers is not None else
                 [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    return s


@test("cavern beast: every opening locked even when the squads could take it (fight_or_hide said fight)")
def _():
    import planner_military
    real = planner_military.fight_or_hide
    planner_military.fight_or_hide = lambda *a, **k: (True, "the squads are strong")
    try:
        s = cave_fort()
        props, notes = plan(s, Memory())
    finally:
        planner_military.fight_or_hide = real
    p = acts(props, "seal_cavern")
    assert p and p[0].action["layer"] == "all caverns" and p[0].action["openings"] is True, props
    assert {"x": 5, "y": 6, "z": 122} in p[0].action["tiles"] and (p[0].action["z1"], p[0].action["z2"]) == (110, 120)
    import overseer
    assert overseer.short(p[0].action) == "lock every way into the caverns"


@test("cavern beast: a forgotten beast in a closed cavern still locks the openings on record")
def _():
    s = cave_fort(threats={"sealed": {}, "openings": {"list": [
        {"x": 1, "y": 2, "z": 3, "kind": "gate", "building": "Door", "built": True, "locked": False}]}},
        dangers=[{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern3"}])
    s["deep"]["caverns"][0]["open"] = False
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action["openings"] is True and "tiles" not in p[0].action, p
    # sealed, and a door built since stands open: sealed again
    s["threats"]["sealed"] = {"all caverns": {"doors": 1, "days": 1}}
    assert acts(plan(s, Memory())[0], "seal_cavern")
    s["threats"]["openings"]["list"][0]["closed"] = True                  # a door shut, not locked: still sealed
    assert acts(plan(s, Memory())[0], "seal_cavern")
    s["threats"]["openings"]["list"][0]["locked"] = True
    assert not acts(plan(s, Memory())[0], "seal_cavern")                 # all locked: nothing to do
    s["threats"]["openings"]["list"][0].update(locked=False, sealed=True)  # shut by its lever by the seal
    assert not acts(plan(s, Memory())[0], "seal_cavern")
    # a titan on the surface is not a cavern danger
    s = cave_fort(dangers=[{"id": 9, "name": "Titan", "kind": "titan", "layer": "surface"}])
    assert not acts(plan(s, Memory())[0], "seal_cavern")


@test("cavern beast: not sealed while citizens are down in the caverns; the player told")
def _():
    s = cave_fort(threats={"sealed": {}, "cavern_citizens": {"n": 2, "list": [
        {"id": 3, "name": "Kib", "x": 9, "y": 9, "z": 115}, {"id": 4, "name": "Zon", "x": 9, "y": 8, "z": 115}]}})
    props, notes = plan(s, Memory())
    assert not acts(props, "seal_cavern"), props
    ny = [n for n in needs_you(notes) if "down there" in n]
    assert ny and "Kib at x9 y9 elevation 15" in ny[0] and "2 citizen(s)" in ny[0], notes


@test("cavern beast gone: the openings opened again, and said; old per-layer seals still opened")
def _():
    s = cave_fort(threats={"sealed": {"all caverns": {"doors": 3, "days": 4}}}, dangers=[])
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action == {"type": "seal_cavern", "layer": "all caverns", "open": True}, p
    assert "opened again" in p[0].reason
    # a seal from before 0.105.26 (one layer)
    s = cave_fort(threats={"sealed": {"Cavern1": {"doors": 1}}}, dangers=[])
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action == {"type": "seal_cavern", "layer": "Cavern1", "open": True}, p
    # the beast still there: the "all caverns" seal is not opened because a day count passed
    s = cave_fort(threats={"sealed": {"all caverns": {"doors": 3, "days": 30}}})
    assert not [p for p in acts(plan(s, Memory())[0], "seal_cavern") if p.action.get("open")]


@test("cavern entrance with no door: doors on it straight away (no beast needed), once")
def _():
    s = cave_fort(dangers=[])
    s["entrances"]["entrances"].append({"id": 4, "kind": "cavern", "x": 60, "y": 61, "z": 121, "width": 2,
                                        "sealed": False, "equipment": [], "door_spots": 2})
    p = acts(plan(s, Memory())[0], "cavern_openings")
    assert p and p[0].action == {"type": "build_gate_doors", "entrance_id": 4} and p[0].priority == 2, p
    m = Memory()
    m.gate_doors_requested.append("60,61,121")
    assert not acts(plan(s, m)[0], "cavern_openings")


@test("cavern beast: the cavern well's shaft said shut (no water) and the injured put to the player")
def _():
    s = cave_fort()
    s["projects"]["well_lids"] = [{"project_id": 3, "x": 1, "y": 1, "z": 1, "gate": "closed"}]
    s["dwarves"]["needs_medical_care"] = 2
    s["buildings"].setdefault("other", {})["Well"] = 1
    props, notes = plan(s, Memory())
    assert any("draws no water" in n for n in notes), notes
    assert any("only well is the cavern well" in n for n in needs_you(notes)), notes


# --- the Lua side ------------------------------------------------------------------

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)

    def K(x, y, z):
        return (z * 4096 + y) * 4096 + x

    GATES_GAME = r"""
local src = ...
local G = {citizens = {}, units = {}, groups = {}, zones = {}}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 10, cur_year_tick = 5000,
                  world = {units = {active = G.units}, buildings = {other = {ZONE_MEETING_HALL = G.zones}}}},
        building = {find = function(id) return nil end}}
e.dfhack = {units = {getCitizens = function() return G.citizens end,
                     getReadableName = function(u) return u.name end,
                     isAlive = function() return true end, isCitizen = function(u) return u.citizen == true end,
                     isHidden = function() return false end, isDanger = function(u) return u.danger == true end,
                     isInvader = function() return false end, isGreatDanger = function() return false end},
            maps = {getWalkableGroup = function(p) return G.groups[p.x .. ',' .. p.y .. ',' .. p.z] or 0 end,
                    getTileFlags = function(x, y, z) return {feature_global = false} end}}
assert(load(src, 'ai-gates', 't', e))()
return e
"""

    @test("lua gates: stranded citizens reported with how long and why (lockdown, no path); the inside ones not")
    def _():
        E = LUA.execute(GATES_GAME, module_src("ai-gates.lua"))
        G = E.G
        t = LUA.table_from
        inside = t({K(5, 5, 10): True, K(5, 6, 10): True, K(19, 5, 10): True})
        ent = t({"id": 1, "kind": "surface", "x": 19, "y": 5, "z": 10, "outs": t({K(20, 5, 10): True}),
                 "equipment": t([t({"id": 50, "kind": "door"})])})
        E.GATES = t({"scanned": True, "inside": inside, "entrances": t([ent]), "closed": t({1: True}), "armed": True})
        G.zones[1] = t({"centerx": 5, "centery": 5, "z": 10})
        for k, g in {"5,5,10": 1, "5,6,10": 1, "20,5,10": 2, "25,5,10": 2, "40,40,10": 3}.items():
            G.groups[k] = g
        G.citizens[1] = t({"id": 1, "name": "Out", "pos": t({"x": 25, "y": 5, "z": 10})})
        G.citizens[2] = t({"id": 2, "name": "Lost", "pos": t({"x": 40, "y": 40, "z": 10})})
        G.citizens[3] = t({"id": 3, "name": "Home", "pos": t({"x": 5, "y": 6, "z": 10})})
        G.units[1] = t({"id": 9, "danger": True, "pos": t({"x": 28, "y": 5, "z": 10}), "flags1": t({})})
        r = E.stranded_citizens()
        assert r.interior.what == "meeting hall" and r.interior.group == 1, dict(r.interior)
        rows = {r.list[i].name: r.list[i] for i in range(1, len(r.list) + 1)}
        assert set(rows) == {"Out", "Lost"} and r.total == 2, rows
        assert rows["Out"].cause == "lockdown" and rows["Out"].by_ai and rows["Out"].entrance.id == 1
        assert rows["Out"].danger_near == 3 and rows["Out"].gate_danger is not None
        assert rows["Lost"].cause == "no_path" and rows["Lost"].entrance is None
        # a game day later: counted out a day
        E.df["global"].cur_year_tick = 5000 + 1300
        r = E.stranded_citizens()
        assert r.list[1].out_days == 1 and r.list[1].out_ticks == 1300, dict(r.list[1])
        # the gate opened (the watcher's lockdown off, the door unlocked): Out isn't stranded; Lost still is
        E.GATES.closed = t({})
        E.GATES.armed = False
        G.groups["20,5,10"] = 1                  # (DF joins the walk groups once the door is open)
        G.groups["25,5,10"] = 1
        r = E.stranded_citizens()
        assert r.total == 1 and r.list[1].name == "Lost", r.total
        # back in: the clock forgets
        G.citizens[2].pos.x, G.citizens[2].pos.y = 5, 5
        r = E.stranded_citizens()
        assert r.total == 0 and E.STRANDED_SINCE[2] is None
        # a door locked, not by the watcher: gate_shut, not by the AI
        E.df.building.find = LUA.eval("function(id) return {id = id, door_flags = {forbidden = true}} end")
        r = E.stranded_citizens()
        assert r.total == 1 and r.list[1].cause == "gate_shut" and not r.list[1].by_ai, dict(r.list[1])

    THREATS_GAME = r"""
local src = ...
local G = {saved = {}, citizens = {}, tiles = {}, pulled = {}, mods = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 1, cur_year_tick = 0},
        building = {find = function(id) for _, b in pairs(G.tiles) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch'}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {getReadableName = function(u) return u.name end, getCitizens = function() return G.citizens end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function(x, y, z) return {feature_global = z <= 5} end}}
local function bld(id, ty) return {id = id, door_flags = {forbidden = false, closed = false},
    getType = function() return ty end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
G.tiles['10,10,10'] = bld(30, 'Door')        -- a cavern entrance's door (from the gates scan)
G.tiles['11,11,11'] = bld(31, 'Hatch')       -- the cavern well's shaft hatch: never locked by the seal
G.tiles['12,12,12'] = bld(32, 'Hatch')       -- a hatch on its own lever
G.tiles['13,13,13'] = bld(33, 'Door')        -- on the way down (a tile the brain sent)
G.mods['ai-gates'] = {
    GATES = {entrances = {{id = 4, kind = 'cavern', x = 9, y = 9, z = 10,
                           equipment = {{id = 30, kind = 'door', x1 = 10, y1 = 10, z = 10},
                                        {id = 32, kind = 'hatch', x1 = 12, y1 = 12, z = 12}}},
                          {id = 5, kind = 'cavern', x = 50, y = 50, z = 10, equipment = {}},
                          {id = 6, kind = 'surface', x = 70, y = 70, z = 20, equipment = {}}}},
    lever_links = function() return {[32] = {40}} end,
    lever_targets = function(links, l) return {32} end,
    pull_instant = function(l) table.insert(G.pulled, l); local h = G.tiles['12,12,12']
        h.door_flags.closed = not h.door_flags.closed; return true end}
G.mods['ai-builder'] = {well_lids = function() return {{project_id = 3, shaft_hatch = {x = 11, y = 11, z = 11}}} end}
assert(load(src, 'ai-threats', 't', e))()
return e
"""

    @test("lua threats: the openings on record (gates' cavern entrances, the well's shaft) and their state")
    def _():
        E = LUA.execute(THREATS_GAME, module_src("ai-threats.lua"))
        d = E.load_state()
        r = E.openings_report(d, 0)
        rows = {(r.list[i].x, r.list[i].y, r.list[i].z): r.list[i] for i in range(1, r.n + 1)}
        assert set(rows) == {(10, 10, 10), (12, 12, 12), (50, 50, 10), (11, 11, 11)}, set(rows)
        assert rows[(11, 11, 11)].kind == "well" and rows[(50, 50, 10)].kind == "open"
        assert rows[(10, 10, 10)].building == "Door" and rows[(10, 10, 10)].locked is False
        # kept in the save
        E.survey(None)
        st = E.G.saved["ai-overseer/threats"]
        assert st.openings["10,10,10"].kind == "gate" and st.openings["11,11,11"].kind == "well"

    @test("lua threats: the seal locks every opening on record (not the well's shaft), pulls a lever's own hatch; "
          "refused with a dwarf down there; opened again after")
    def _():
        E = LUA.execute(THREATS_GAME, module_src("ai-threats.lua"))
        G = E.G
        E.survey(None)                                         # the openings put on record
        tl = LUA.table_from([LUA.table_from({"x": 13, "y": 13, "z": 13})])
        G.citizens[1] = LUA.table_from({"id": 1, "name": "Kib", "pos": LUA.table_from({"x": 0, "y": 0, "z": 3})})
        r = E.seal_cavern("all caverns", tl, False, False, 1, 5, True)
        assert r.rejected and "Kib" in r.error, dict(r)
        G.citizens[1].pos.z = 9
        r = E.seal_cavern("all caverns", tl, False, False, 1, 5, True)
        T = G.tiles
        assert r.ok and r.locked == 3, dict(r)
        assert T["10,10,10"].door_flags.forbidden and T["13,13,13"].door_flags.forbidden
        assert not T["11,11,11"].door_flags.forbidden and not T["11,11,11"].door_flags.closed   # the well's
        assert list(G.pulled.values()) == [40] and T["12,12,12"].door_flags.closed
        assert G.saved["ai-overseer/threats"].openings["13,13,13"].kind == "way_down"
        rep = E.openings_report(E.load_state(), 0)
        sealed = {(rep.list[i].x, rep.list[i].y): rep.list[i].sealed for i in range(1, rep.n + 1)}
        assert sealed[(10, 10)] and sealed[(12, 12)] and sealed[(13, 13)] and not sealed[(11, 11)], sealed
        r = E.seal_cavern("all caverns", LUA.table_from([]), True, False)
        assert r.ok and not T["10,10,10"].door_flags.forbidden and not T["12,12,12"].door_flags.closed, dict(r)
        assert list(G.pulled.values()) == [40, 40] and G.saved["ai-overseer/threats"].sealed["all caverns"] is None

    WELLS_GAME = r"""
local src = ...
local T = {timers = {}, pulls = {}, units = {}, citizens = {}}
local e = setmetatable({T = T}, {__index = _G})
e.ez = function(z) return z end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 1, cur_year_tick = 0, world = {units = {active = T.units}}},
        building_type = {Hatch = 'Hatch'}, job_type = {PullLever = 1},
        building = {find = function(id) return {id = id, jobs = {}} end}}
e.dfhack = {timeout = function(n, u, f) table.insert(T.timers, f); return #T.timers end,
            buildings = {findAtTile = function(p) if p.x == 10 and p.y == 10 and p.z == 40 then return T.hatch end end},
            units = {isActive = function() return true end, isDead = function() return false end,
                     isCitizen = function() return false end, isDanger = function(u) return u.danger == true end,
                     isGreatDanger = function(u) return u.great == true end, isAnimal = function() return false end,
                     getCitizens = function() return T.citizens end},
            maps = {getTileFlags = function(x, y, z) return {feature_global = z < 40} end},
            job = {removeJob = function() end}}
e.load_projects = function() return {list = {{id = 3, kind = 'well', x = 10, y = 10, z = 50, shaft = {41, 40},
                                               shaft_gate = {lever_id = 8, hatch_id = 7}}}} end
e.anchor_of = function(p) return {x = p.x, y = p.y} end
e.pull = function(id) table.insert(T.pulls, id); T.hatch.door_flags.closed = true; return true end
T.hatch = {id = 7, door_flags = {closed = false, forbidden = false}, getType = function() return 'Hatch' end,
           getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
assert(load(src, 'ai-builder-wells', 't', e))()
return e
"""

    @test("lua wells: the shaft watcher shuts the shaft for a forgotten beast anywhere below, not with a dwarf down there")
    def _():
        E = LUA.execute(WELLS_GAME, (ROOT / "lua" / "ai-builder-wells.lua").read_text(encoding="utf-8"))
        T = E.T
        T.units[1] = LUA.table_from({"id": 9, "danger": True, "great": True, "flags1": LUA.table_from({}),
                                     "pos": LUA.table_from({"x": 150, "y": 150, "z": 30})})    # 140 tiles off
        T.citizens[1] = LUA.table_from({"id": 1, "pos": LUA.table_from({"x": 5, "y": 5, "z": 30})})   # in the cavern
        E.shaft_watch_start()
        T.timers[len(T.timers)]()
        assert len(T.pulls) == 0 and T.hatch.door_flags.closed is False      # a dwarf down there: left open
        T.citizens[1].pos.z = 50
        T.timers[len(T.timers)]()
        assert list(T.pulls.values()) == [8] and T.hatch.door_flags.closed is True
        # an ordinary danger that far: left alone (as before)
        E.SHAFT_WATCH.on = False
        E2 = LUA.execute(WELLS_GAME, (ROOT / "lua" / "ai-builder-wells.lua").read_text(encoding="utf-8"))
        E2.T.units[1] = LUA.table_from({"id": 9, "danger": True, "flags1": LUA.table_from({}),
                                        "pos": LUA.table_from({"x": 150, "y": 150, "z": 30})})
        E2.shaft_watch_start()
        E2.T.timers[len(E2.T.timers)]()
        assert len(E2.T.pulls) == 0
        E2.SHAFT_WATCH.on = False

    @test("bridge: seal_cavern takes openings (no tiles needed then) and passes it on")
    def _():
        src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        bt = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")
        harness = bt.split("LUA = LuaRuntime")[0].split('HARNESS = r"""', 1)[1].split('"""', 1)[0]
        H = LUA.execute(harness, src, str(ROOT / "lua"))
        H.scripts = LUA.table_from({"ai-threats": LUA.eval("""{
            seal_cavern = function(layer, tiles, open, dry, z1, z2, openings)
                return {ok = true, n = #tiles, open = open, openings = openings} end}""")})
        M = H.module()
        t = lambda d: LUA.table_from({k: (LUA.table_from(v) if isinstance(v, list) else v) for k, v in d.items()})
        r = M.act_seal_cavern(t({"layer": "all caverns", "openings": True}))
        assert r.ok and r.n == 0 and r.openings is True, dict(r)
        assert M.act_seal_cavern(t({"layer": "all caverns", "openings": "yes"})).rejected
        assert M.act_seal_cavern(t({"layer": "C", "tiles": []})).rejected          # still: no tiles, no openings


if __name__ == "__main__":
    finish()
