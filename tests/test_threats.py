"""(0.105.0) Round 3: threats answered. The planner's rules
(brain/planner_threats.py) on the real test fort with a `threats` report
added, the bridge's new actions, and the pure parts of lua/ai-threats.lua
in a real Lua engine (pip install lupa).

    python tests/test_threats.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
import planner_threats as PT  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def fort(threats: dict, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["threats"] = threats
    s.update(kw)
    return s


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


@test("fire near the dwarves: guarded (paths restricted, jobs off) and said where; lifted once out")
def _():
    s = fort({"fire": {"fires": 4, "spots": [{"x": 10, "y": 20, "z": 30, "n": 4, "near": 8}], "jobs_near": 3}})
    props, notes = plan(s, Memory())
    g = acts(props, "fire_guard")
    assert g and g[0].action["type"] == "fire_guard" and not g[0].action.get("lift"), props
    assert any("fire in 4 place(s): x10 y20 z30" in n for n in notes), notes
    s = fort({"fire": {"fires": 4, "spots": [{"x": 10, "y": 20, "z": 30, "n": 4, "near": 200}]}})
    assert not acts(plan(s, Memory())[0], "fire_guard")                       # far away: noted only
    s = fort({"fire": {"fires": 0, "spots": [], "guarded_tiles": 50}})
    g = acts(plan(s, Memory())[0], "fire_guard")
    assert g and g[0].action == {"type": "fire_guard", "lift": True}, g
    import overseer
    assert overseer.short({"type": "fire_guard"}) == "keep the dwarves away from the fire"
    assert "werebeasts" in overseer.short({"type": "moon_cell", "ids": [1]})


@test("prisoners: a cage room when none inside; keep is the default, release/kill said and kept")
def _():
    s = fort({"prisoners": {"caged": 2, "cage_rooms": 0}})
    props, notes = plan(s, Memory())
    assert acts(props, "prisoners", "prisoner_room"), props
    assert any("2 prisoner(s) kept" in n for n in notes), notes
    s = fort({"prisoners": {"caged": 2, "cage_rooms": 1}})
    s["settings"]["prisoners"] = "kill"
    props, notes = plan(s, Memory())
    assert not acts(props, "prisoners") and any("no safe way" in n for n in notes), notes
    assert PT.threat_rules_of({"settings": {"prisoners": "odd"}})["prisoners"] == "keep"


@test("thieves: a snatcher inside gets the squad; none free: a note")
def _():
    th = {"thieves": {"list": [{"id": 77, "name": "Snat", "kind": "snatcher", "inside": True, "kill_ok": True}],
                      "seen_total": 1}}
    s = fort(th)
    s["military"]["squads"] = [{"id": 3, "members": 6, "name": "Axes"}]
    k = [p for p in plan(s, Memory())[0] if p.rule == "squad_attack" and 77 in p.action.get("kill", [])]
    assert k and k[0].action["squad_id"] == 3, k
    s["military"]["squads"] = []
    _, notes = plan(s, Memory())
    assert any("Snat (snatcher) in the fort and no squad" in n for n in notes), notes


@test("thieves seen: cage traps at a gated entrance with none (fort with no trap style)")
def _():
    s = fort({"thieves": {"list": [], "seen_total": 2}})
    s["entrances"] = {"entrances": [{"id": 5, "x": 1, "y": 2, "z": 3, "sealed": True, "kind": "surface",
                                     "equipment": [{"kind": "door"}]}]}
    m = Memory()
    props, notes = [], []
    import culture
    old = culture.profile_from
    try:
        culture.profile_from = lambda *a, **k: {"traps": "none"}
        PT._threat_rules(planner.normalize(s), m, PLANNER_CONFIG, props, notes)
    finally:
        culture.profile_from = old
    t = acts(props, "traps", "place_traps")
    assert t and t[0].action == {"type": "place_traps", "entrance_id": 5, "kind": "cage", "count": 3}, props


@test("the undead near the dwarves or an evil cloud near those outside: the alarm, and it isn't lowered")
def _():
    s = fort({"undead": {"undead": 1, "list": [{"id": 9, "name": "zombie", "distance": 10, "can_reach_dwarves": True}]}},
             civ_alert=False, civ_alert_ready=True)
    a = acts(plan(s, Memory())[0], "threat_alert")
    assert a and a[0].action == {"type": "civ_alert", "on": True} and "walking dead" in a[0].reason, a
    s = fort({"undead": {"clouds": 3, "cloud_outside_near": 12}}, civ_alert=False, civ_alert_ready=True)
    assert acts(plan(s, Memory())[0], "threat_alert")
    s = fort({"undead": {"clouds": 3, "cloud_outside_near": 12}}, civ_alert=True, civ_alert_ready=True)
    m = Memory(ai_alert_raised=True, quiet_cycles=99)
    assert not [p for p in plan(s, m)[0] if p.action == {"type": "civ_alert", "on": False}]
    s = fort({"undead": {"clouds": 3, "cloud_outside_near": 300}}, civ_alert=False, civ_alert_ready=True)
    assert not acts(plan(s, Memory())[0], "threat_alert")


@test("a reanimating land: bodies lying outside rotted away when quiet")
def _():
    s = fort({"undead": {"reanimating": True, "surface_corpses": 12}})
    p = acts(plan(s, Memory())[0], "reanimation")
    assert p and p[0].action == {"type": "prune_remains"}, p
    s = fort({"undead": {"reanimating": True, "surface_corpses": 2}})
    assert not acts(plan(s, Memory())[0], "reanimation")


@test("werebeasts: no change seen yet - a note; near the moon - a cell; past it - let out; switch off - let out")
def _():
    s = fort({"were": {"list": [{"id": 4, "name": "Wolfy"}], "changes": [], "moon_phase": 7}})
    props, notes = plan(s, Memory())
    assert not acts(props, "moon_cell") and any("full moon isn't known" in n for n in notes), notes
    now = abs_tick(planner.normalize(s))
    period = 28 * TICKS_PER_DAY
    s["threats"]["were"]["changes"] = [{"tick": now - period + 1 * TICKS_PER_DAY}]     # due in a day
    c = acts(plan(s, Memory())[0], "moon_cell")
    assert c and c[0].action == {"type": "moon_cell", "ids": [4]}, c
    s["threats"]["were"]["changes"] = [{"tick": now - 10 * TICKS_PER_DAY}]
    s["threats"]["were"]["cells"] = [{"unit_id": 4, "locked": True}]
    c = acts(plan(s, Memory())[0], "moon_cell")
    assert c and c[0].action.get("release") is True, c
    assert PT.moon_due([], now, PLANNER_CONFIG) is None
    s["settings"]["moon_cells"] = False
    c = acts(plan(s, Memory())[0], "moon_cell")
    assert c and c[0].action.get("release") is True


@test("a forgotten beast in an open cavern the squads can't take: the way down locked; gone: unlocked")
def _():
    s = fort({"sealed": {}})
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True,
                              "open_at": {"x": 5, "y": 6, "z": 7}, "column": [{"z": 8}, {"z": 9}]}],
                 "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    s["military"]["squads"] = []
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action["layer"] == "Cavern1" and {"x": 5, "y": 6, "z": 8} not in p[0].action["tiles"], p
    # (0.105.0 review) only the column's stair/ramp/hatch tiles, and the cavern's levels sent
    s["deep"]["caverns"][0].update(column=[{"z": 8, "shape": "STAIR_UPDOWN"}, {"z": 9, "shape": "FLOOR"},
                                           {"z": 10, "shape": "FLOOR", "building": "Hatch"}], z_top=7, z_bottom=3)
    p = acts(plan(s, Memory())[0], "seal_cavern")
    tl = p[0].action["tiles"]
    assert {"x": 5, "y": 6, "z": 8} in tl and {"x": 5, "y": 6, "z": 10} in tl and {"x": 5, "y": 6, "z": 9} not in tl, tl
    assert (p[0].action["z1"], p[0].action["z2"]) == (3, 7), p[0].action
    s["deep"]["dangers"] = []
    s["threats"]["sealed"] = {"Cavern1": {"doors": 2}}
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action == {"type": "seal_cavern", "layer": "Cavern1", "open": True}, p


@test("(0.105.0 review) the undead alarm: only the dead that can reach; not a reanimating land's own; capped in days")
def _():
    def alarm(rows, m=None):
        s = fort({"undead": {"undead": len(rows), "list": rows}}, civ_alert=False, civ_alert_ready=True)
        return acts(plan(s, m or Memory())[0], "threat_alert"), s
    assert not alarm([{"id": 1, "name": "z", "distance": 5, "can_reach_dwarves": False}])[0]   # walled off
    assert not alarm([{"id": 1, "name": "z", "distance": 5}])[0]                               # unknown
    assert not alarm([{"id": 1, "name": "z", "distance": 5, "can_reach_dwarves": True, "outside": True}])[0]
    assert alarm([{"id": 1, "name": "z", "distance": 5, "can_reach_dwarves": True, "outside": True,
                   "invader": True}])[0]
    assert alarm([{"id": 1, "name": "z", "distance": 5, "can_reach_dwarves": True, "outside": True, "great": True}])[0]
    assert not alarm([{"id": 1, "name": "z", "distance": 300, "can_reach_dwarves": True}])[0]  # far away
    # held 7 days at most, then a Needs-you note
    row = [{"id": 1, "name": "z", "distance": 5, "can_reach_dwarves": True}]
    m = Memory()
    a, s = alarm(row, m)
    assert a and m.threat_alarm.get("since") == abs_tick(planner.normalize(s))
    m.threat_alarm["since"] -= 8 * TICKS_PER_DAY
    props, notes = plan(s, m)
    assert not acts(props, "threat_alert") and any("no longer holds the alarm" in n for n in notes), notes
    # all clear: the clock forgets
    s = fort({"undead": {"undead": 0, "list": []}})
    plan(s, m)
    assert m.threat_alarm == {}


@test("(0.105.0 review) werebeasts: a changed one's cell id is sent with the others'; a sealed layer gone is unlocked")
def _():
    s = fort({"were": {"list": [{"id": 4, "name": "Wolfy"}, {"id": 5, "name": "Raging", "changed": True, "cell": True}],
                       "cells": [{"unit_id": 5, "locked": True}]}})
    now = abs_tick(planner.normalize(s))
    s["threats"]["were"]["changes"] = [{"tick": now - 1 * TICKS_PER_DAY}]
    c = acts(plan(s, Memory())[0], "moon_cell")
    assert c and sorted(c[0].action["ids"]) == [4, 5], c
    s = fort({"sealed": {"Cavern9": {"doors": 2, "days": 8}}})
    s["deep"] = {"caverns": [], "dangers": []}
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action == {"type": "seal_cavern", "layer": "Cavern9", "open": True}, p
    s["threats"]["sealed"]["Cavern9"]["days"] = 2
    assert not acts(plan(s, Memory())[0], "seal_cavern")


@test("a great beast on the surface near dwarves out there: the alarm")
def _():
    s = fort({"surface": {"list": [{"id": 3, "name": "a giant", "great": True, "distance_outside": 15}]}},
             civ_alert=False, civ_alert_ready=True)
    a = acts(plan(s, Memory())[0], "threat_alert")
    assert a and "surface" in a[0].reason, a


@test("nobody fetches the wounded: two put on DF's Recover wounded labour")
def _():
    s = fort({"rescue": {"holders": 0, "down": 1, "mode": "OnlySelectedDoesThis"}})
    props, notes = plan(s, Memory())
    r = acts(props, "rescue_labor")
    assert r and r[0].action == {"type": "assign_labor", "job": "RECOVER_WOUNDED", "count": 2}, r
    assert any("lie down waiting" in n for n in notes)
    assert not acts(plan(fort({"rescue": {"holders": 3}}), Memory())[0], "rescue_labor")


@test("a failed threats section: skipped, nothing proposed; the digest default is {}")
def _():
    import digest
    assert digest.SECTION_DEFAULTS["threats"] == {}
    s = fort({"error": "boom"})
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.rule in ("fire_guard", "moon_cell", "seal_cavern", "rescue_labor")]


# --- the Lua side ----------------------------------------------------------------

try:
    from lupa import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime:
    LUA = LuaRuntime(unpack_returned_tuples=True)
    SRC = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    ENV = LUA.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'ai-threats', 't', e))(); return e", SRC)

    @test("lua: cluster, near_any, thief_kind, fire_tiles, find_rect (pure)")
    def _():
        pts = LUA.table_from([LUA.table_from(p) for p in ({"x": 1, "y": 1, "z": 5}, {"x": 2, "y": 3, "z": 5},
                                                          {"x": 40, "y": 40, "z": 5})])
        c = ENV.cluster(pts, 8, 5)
        assert c[1].n == 2 and c[2].n == 1, (c[1].n, c[2].n)
        assert ENV.near_any(4, 4, 5, pts, 3) and not ENV.near_any(4, 4, 6, pts, 3)
        assert ENV.thief_kind("SNATCHER", None) == "snatcher" and ENV.thief_kind(None, "ThiefTarget") == "thief"
        assert ENV.thief_kind("MINER", "None") is None
        one = LUA.table_from([LUA.table_from({"x": 5, "y": 5, "z": 1})])
        assert len(list(ENV.fire_tiles(one, 1, 100).values())) == 9
        assert len(list(ENV.fire_tiles(one, 5, 10).values())) == 10
        r = ENV.find_rect(LUA.eval("function(x, y) return x >= 10 and y >= 3 end"), 0, 0, 20, 3, 3)
        assert r is not None and (r.x, r.y) == (10, 3), (r and (r.x, r.y))

    @test("lua (0.105.0 review): the fire guard takes off only dig, build and haul jobs; doors touching a zone")
    def _():
        for jt in ("Dig", "DigChannel", "CarveUpwardStaircase", "ConstructBuilding", "StoreItemInStockpile",
                   "StoreItemInBin", "BringItemToDepot", "RemoveConstruction", "DestroyBuilding", "SmoothWall"):
            assert ENV.fire_job_ok(jt), jt
        for jt in ("Eat", "Drink", "Sleep", "RecoverWounded", "DressWound", "Surgery", "GiveWater", "GiveFood",
                   "DiagnosePatient", "BringCrutch", "ApplyCast", "StoreItemInHospital", "ConstructBed",
                   "ConstructDoor", "Rest", None):
            assert not ENV.fire_job_ok(jt), jt
        # an L-shaped zone: (0..2, 0) and (0, 0..2); a tile at (2, 2) touches no zone tile
        inz = LUA.eval("function(x, y) return (y == 0 and x >= 0 and x <= 2) or (x == 0 and y >= 0 and y <= 2) end")
        assert ENV.touches_zone(inz, 1, 1) and ENV.touches_zone(inz, 3, 1) and not ENV.touches_zone(inz, 3, 3)

    GAME = r"""
local src = ...
local G = {saved = {}, units = {}, buildings = {}, citizens = {}, tiles = {}}
local e = setmetatable({G = G}, {__index = _G})
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {cur_year = 1, cur_year_tick = 0, plotinfo = {burrows = {list = {}, next_id = 1}},
                  world = {buildings = {all = G.buildings, other = {ZONE_DUNGEON = {}, ZONE_BEDROOM = {}}}}},
        unit = {find = function(id) return G.units[id] end},
        building = {find = function(id) for _, b in ipairs(G.buildings) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch'}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {isDead = function() return false end, getReadableName = function(u) return u.name end,
                     getCitizens = function() return G.citizens end},
            burrows = {setAssignedUnit = function() end, clearTiles = function() end, setAssignedTile = function() end},
            buildings = {containsTile = function() return true end,
                         findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function(x, y, z) return {feature_global = z <= 5} end}}
assert(load(src, 'ai-threats', 't', e))()
return e
"""

    @test("lua (0.105.0 review): a changed werebeast's cell is never freed; no seal with a dwarf in the cavern")
    def _():
        E = LUA.execute(GAME, SRC)
        G = E.G
        LUA.execute("""local E = ...; local G = E.G
            G.units[5] = {id = 5, name = 'Raging', race = 1, enemy = {normal_race = 2}, pos = {x = 1, y = 1, z = 10}}
            G.units[4] = {id = 4, name = 'Calm', race = 1, enemy = {normal_race = -1}, pos = {x = 9, y = 9, z = 10}}
            G.saved['ai-overseer/threats'] = {cells = {['5'] = {zone = 77, locked = true, doors = {}}}}""", E)
        r = E.moon_cell(LUA.table_from([4]), False, True)
        st = G.saved["ai-overseer/threats"]
        assert st.cells["5"] is not None and r.kept and r.kept[1] == "Raging", dict(r)
        r = E.moon_cell(LUA.table_from([]), True, False)                # a release keeps it too
        assert G.saved["ai-overseer/threats"].cells["5"] is not None and (not r.released or len(r.released) == 0), dict(r)
        LUA.execute("local E = ...; E.G.units[5].enemy.normal_race = -1", E)   # back to a dwarf: let out
        E.moon_cell(LUA.table_from([]), True, False)
        assert G.saved["ai-overseer/threats"].cells["5"] is None
        # the seal: a citizen down on a cavern tile (z 3) -> refused; none -> the door on the tile locked
        LUA.execute("""local E = ...; local G = E.G
            G.citizens[1] = {id = 1, name = 'Urist', pos = {x = 0, y = 0, z = 3}}
            local door = {id = 30, door_flags = {forbidden = false}, getType = function() return 'Door' end}
            local near = {id = 31, door_flags = {forbidden = false}, getType = function() return 'Door' end}
            G.tiles['5,6,7'] = door; G.tiles['6,6,7'] = near; G.door, G.near = door, near""", E)
        tiles = LUA.table_from([LUA.table_from({"x": 5, "y": 6, "z": 7})])
        r = E.seal_cavern("Cavern1", tiles, False, False, 1, 5)
        assert r.rejected and "Urist" in r.error, dict(r)
        LUA.execute("local E = ...; E.G.citizens[1].pos.z = 8", E)
        r = E.seal_cavern("Cavern1", tiles, False, False, 1, 5)
        assert r.ok and r.locked == 1 and G.door.door_flags.forbidden and not G.near.door_flags.forbidden, dict(r)

    BRIDGE_TEST = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")

    @test("bridge: the new actions are in the table and refuse bad input before reaching the game")
    def _():
        src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        for name in ("fire_guard", "prisoner_room", "moon_cell", "seal_cavern"):
            assert f"    {name} = act_{name}," in src, name
        assert "threats = function() return safe(function() return reqscript('ai-threats').survey(txt) end) end" in src
        ns = {}
        harness = BRIDGE_TEST.split("LUA = LuaRuntime")[0].split('HARNESS = r"""', 1)[1].split('"""', 1)[0]
        H = LUA.execute(harness, src, str(ROOT / "lua"))   # (13c) where the bridge's parts are
        H.scripts = LUA.table_from({"ai-threats": LUA.eval("""{
            fire_guard = function(r, j, lift, dry) return {ok = true, r = r, j = j, lift = lift} end,
            prisoner_room = function(dry) return {ok = true} end,
            moon_cell = function(ids, release, dry) return {ok = true, n = #ids, release = release} end,
            seal_cavern = function(layer, tiles, open) return {ok = true, n = #tiles, open = open} end}""")})
        M = H.module()

        def t(d):
            if isinstance(d, dict):
                return LUA.table_from({k: t(v) for k, v in d.items()})
            if isinstance(d, list):
                return LUA.table_from([t(v) for v in d])
            return d
        r = M.act_fire_guard(t({}))
        assert r.ok and (r.r, r.j, r.lift) == (6, 40, False)
        assert M.act_fire_guard(t({"lift": True})).lift is True
        for bad in ({"radius": 0}, {"radius": 99}, {"max_jobs": -1}, {"lift": "yes"}):
            assert M.act_fire_guard(t(bad)).rejected, bad
        assert M.act_prisoner_room(t({})).ok
        assert M.act_moon_cell(t({"ids": [1, 2]})).n == 2
        assert M.act_moon_cell(t({"ids": ["x"]})).rejected and M.act_moon_cell(t({"ids": 5})).rejected
        assert M.act_moon_cell(t({"release": True})).release is True
        assert M.act_seal_cavern(t({"layer": "Cavern1", "tiles": [{"x": 1, "y": 2, "z": 3}]})).n == 1
        assert M.act_seal_cavern(t({"layer": "Cavern1", "open": True})).open is True
        for bad in ({}, {"layer": "C"}, {"layer": "C", "tiles": [{"x": 1}]}, {"layer": "C", "tiles": []}):
            assert M.act_seal_cavern(t(bad)).rejected, bad


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
