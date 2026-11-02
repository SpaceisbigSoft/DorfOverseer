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
    s = fort({"undead": {"undead": 1, "list": [{"id": 9, "name": "zombie", "distance": 10}]}},
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
    assert p and p[0].action["layer"] == "Cavern1" and {"x": 5, "y": 6, "z": 8} in p[0].action["tiles"], p
    s["deep"]["dangers"] = []
    s["threats"]["sealed"] = {"Cavern1": {"doors": 2}}
    p = acts(plan(s, Memory())[0], "seal_cavern")
    assert p and p[0].action == {"type": "seal_cavern", "layer": "Cavern1", "open": True}, p


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

    BRIDGE_TEST = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")

    @test("bridge: the new actions are in the table and refuse bad input before reaching the game")
    def _():
        src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        for name in ("fire_guard", "prisoner_room", "moon_cell", "seal_cavern"):
            assert f"    {name} = act_{name}," in src, name
        assert "threats = function() return safe(function() return reqscript('ai-threats').survey(txt) end) end" in src
        ns = {}
        harness = BRIDGE_TEST.split("LUA = LuaRuntime")[0].split('HARNESS = r"""', 1)[1].split('"""', 1)[0]
        H = LUA.execute(harness, src)
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
