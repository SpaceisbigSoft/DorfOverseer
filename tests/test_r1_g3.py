"""(r1 g3) Water in winter, and wells that count only when they serve.

B (R-B finding 1): the only well stood over a surface brook that freezes;
in winter the well rule looked only for an open drop inside the fort and
never dug a shaft; every winter every patient died of thirst. E (R-CE): one
cavern well for 80-94 dwarves, and the shelter's dry-level widening counted
the level with its one well tile as watered. A3 22 / B8: "a well for every
70" never fired (the slot cap; a refusal not naming the cavern never led to
the cavern well).

    python tests/test_r1_g3.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, skip  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal  # noqa: E402
from planner import record  # noqa: E402
import planner_wells  # noqa: E402
import planner_shelter  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except Exception:  # noqa: BLE001
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
B_REFUSAL = ("no open drop from a free floor inside the fort to clean water; and the water near the surface "
             "freezes in winter (a well over it would be taken down), so the AI looks only inside the fort")


def b_fort(season: str = "autumn", tick: int = 290000) -> dict:
    """Fort B as its report stood (R-B 1a/1c; run2/B/state-last.json): 16
    citizens, no well (the shore well over the brook at x67-73 y122-125,
    elevation 42, given up before the ice), the surface 15 degrees over
    freezing in late autumn, the cavern water at x125 y126 z136 (Cavern1, z
    123-146), the survey's cistern 'none'."""
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 4, "month": "Timber", "season": season, "tick": tick, "year": 253}
    s["dwarves"]["total"] = 16
    s["dwarves"]["needs_medical_care"] = 0
    s["society"]["parched"] = 0
    s["buildings"]["other"].pop("Well", None)
    s["buildings"].setdefault("zones", {}).pop("WaterSource", None)
    s["projects"]["open"] = []
    s["projects"]["well_lids"] = []
    s["projects"]["max_open"] = 3
    s["env_hazards"] = {"frost": {"surface_temp": 10015, "freezing": False, "wells": [], "zones": [], "on_ice": []}}
    s["water"] = {"ok": True, "done": True, "tick": 106231076,
                  "bodies": [{"kind": "surface", "tiles": 38, "stagnant_share": 100, "salt_share": 0,
                              "nearest": {"d": 53, "depth": 7, "x": 73, "y": 124, "z": 170}},
                             {"kind": "cavern", "tiles": 12390, "stagnant_share": 0, "salt_share": 0,
                              "nearest": {"d": 68, "depth": 7, "x": 125, "y": 126, "z": 136}}],
                  "cistern": {"none": True, "why": "no tunnel through solid rock from a cistern site to still water"}}
    s["map"]["layers"] = [{"name": "Cavern1", "z_top": 146, "z_bottom": 123, "discovered": True},
                          {"name": "Cavern2", "z_top": 118, "z_bottom": 114, "discovered": True}]
    s["map"].setdefault("dwarves", {})["z_bottom"] = 160
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["others_on_map"]["threats"] = []
    s.setdefault("deep", {})["dangers"] = []
    s.setdefault("well_safety", {})["book"] = {"active": [], "closed_sites": 0, "cooldown_days_left": 0}
    return s


def memory() -> Memory:
    m = Memory()
    m.well_floor_retried = True
    m.cavern_shaft_stairs = True
    m.well_failure = B_REFUSAL
    return m


def winter_props(s, m=None, cfg=None):
    p, n = [], []
    planner_wells._winter_water_rule(s, m if m is not None else memory(), cfg or PLANNER_CONFIG, p, n, {})
    return p, n


# ---- 1. water in winter -----------------------------------------------------------------

@test("B: no well, its brook freezing in late autumn: a cavern well (a shaft) before the winter, not an inside drop")
def _():
    s = b_fort()
    m = memory()
    # the well rule as before: only an inside drop (refused 78 times in B)
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    planner_wells._winter_water_rule(s, m, PLANNER_CONFIG, p, n, {})
    ww = [x for x in p if x.rule == "winter_water"]
    assert ww and ww[0].action["type"] == "place_well" and ww[0].action.get("cavern") is True, [(x.rule, x.action) for x in p]
    assert ww[0].action.get("urgent") is True and "works in winter" in ww[0].reason, ww[0].reason
    # the inside-only ordinary well of the same cycle is dropped (one well a cycle)
    assert not [x for x in p if x.rule == "well" and not x.action.get("cavern")], [(x.rule, x.action) for x in p]


@test("a shore well over surface water, in summer at a fort where ice was seen: the cavern well is dug now")
def _():
    s = b_fort(season="summer", tick=150000)
    s["buildings"]["other"]["Well"] = 1
    s["env_hazards"]["frost"]["surface_temp"] = 10060
    s["env_hazards"]["frost"]["wells"] = [{"id": 49, "x": 72, "y": 124, "z": 170, "water": "water", "outside": True}]
    m = memory()
    m.climate_freezes = True
    p, n = winter_props(s, m)
    assert p and p[0].action.get("cavern") and p[0].priority == 3 and not p[0].action.get("urgent"), [(x.action, x.priority) for x in p]
    # a warm fort (no ice ever, warm surface, summer): nothing
    m.climate_freezes = False
    p, n = winter_props(s, m)
    assert not p and not n, (p, n)


@test("a fort with a cavern well (water under no sky), a working cistern or an underground water zone: no winter rule")
def _():
    s = b_fort()
    s["buildings"]["other"]["Well"] = 1
    s["env_hazards"]["frost"]["wells"] = [{"id": 13, "x": 125, "y": 126, "z": 160, "water": "water"}]
    assert winter_props(s) == ([], [])
    s["env_hazards"]["frost"]["wells"] = []
    s["water"]["cistern_status"] = {"stage": "done", "gate": "shut", "depth": 6, "v": 2}
    assert winter_props(s) == ([], [])
    del s["water"]["cistern_status"]
    s["env_hazards"]["frost"]["zones"] = [{"x": 125, "y": 126, "z": 136, "water": "water"}]
    assert winter_props(s) == ([], [])
    # no frost reading (an older bridge): nothing said
    s = b_fort()
    del s["env_hazards"]
    assert winter_props(s) == ([], [])


@test("B as it was: Cavern1 unfound, the Rules switch at 'ai', no armed soldier: no shaft; said why (both ways)")
def _():
    s = b_fort()
    s["map"]["layers"][0]["discovered"] = False
    s["settings"]["open_caverns"] = "ai"
    s["military"]["squads"] = []
    p, n = winter_props(s)
    assert not p, [(x.rule, x.action) for x in p]
    assert any("no cavern well now" in x and "soldier" in x and "no cistern site" in x for x in n), n
    # the switch at never: never, whatever the soldiers
    s["settings"]["open_caverns"] = "never"
    s["military"]["squads"] = [{"id": 1, "members": 4, "power": {"armed": 4}}]
    p, n = winter_props(s)
    assert not p and any("Never" in x for x in n), (p, n)
    # at 'ai' with soldiers: the winter need is the AI's reason to open it
    s["settings"]["open_caverns"] = "ai"
    p, n = winter_props(s)
    assert p and p[0].action.get("cavern") and p[0].action.get("open_caverns") is True, [x.action for x in p]
    assert "opens Cavern1 for the first time" in p[0].reason, p[0].reason


@test("no cavern well (a recent refusal): the survey's cistern, filled while the water is liquid, whatever the fort's size")
def _():
    s = b_fort(season="summer", tick=150000)
    m = memory()
    m.climate_freezes = True
    m.cavern_well_failure = "no floor inside the fort over cavern water"
    s["water"]["cistern"] = {"elevation": 30, "source": "underground pool", "tunnel": 12,
                             "well": {"x": 100, "y": 150}, "cistern": {}}
    p, n = [], []
    # the cistern rule itself waits for 30 dwarves: it says nothing at 16
    planner_wells._cistern_rule(s, m, PLANNER_CONFIG, p, n, {})
    assert not p, [x.action for x in p]
    planner_wells._winter_water_rule(s, m, PLANNER_CONFIG, p, n, {})
    assert [x.action["type"] for x in p] == ["cistern_step"] and p[0].rule == "winter_water", [x.action for x in p]
    assert p[0].action["prefs"]["freezes"] is True
    # once begun, the cistern rule carries it: the winter rule only notes
    s["water"]["cistern_status"] = {"stage": "digging", "v": 2}
    p, n = winter_props(s, m)
    assert not p and any("cistern is being made" in x for x in n), (p, n)


@test("the winter well waits for no ordinary slot: over max_open it goes as urgent; a cavern well being dug: nothing more")
def _():
    s = b_fort()
    s["projects"]["open"] = [{"id": i, "kind": "rooms", "phase": "dig"} for i in range(3)]
    p, n = winter_props(s)
    assert p and p[0].action.get("urgent") is True, [x.action for x in p]
    s["projects"]["open"] = [{"id": i, "kind": "rooms", "phase": "dig"} for i in range(5)]
    p, n = winter_props(s)
    assert not p and any("free building slot" in x for x in n), (p, n)
    s["projects"]["open"] = [{"id": 70, "kind": "well", "phase": "dig", "summary": {"cavern": True}}]
    p, n = winter_props(s)
    assert not p and any("being made" in x for x in n), (p, n)
    # a shore well being dug is no winter water: the cavern well still asked
    s["projects"]["open"] = [{"id": 71, "kind": "well", "phase": "dig", "summary": {"shore": True}}]
    p, n = winter_props(s)
    assert p and p[0].action.get("cavern"), (p, n)


@test("planner: the winter rule runs in plan() (B's state)")
def _():
    from planner import plan
    s = b_fort()
    props, notes = plan(s, memory())
    ww = [x for x in props if x.rule == "winter_water"]
    assert ww and ww[0].action.get("cavern"), [x.rule for x in props]


# ---- 2. wells per population ------------------------------------------------------------

def e_fort() -> dict:
    """Fort E (R-CE 6): one cavern well for 90 dwarves, every slot full
    (projects.open at max_open), the ordinary well refused "no open drop ...;
    no pond, brook or river within 40"."""
    s = b_fort(season="summer", tick=150000)
    s["dwarves"]["total"] = 90
    s["buildings"]["other"]["Well"] = 1
    s["env_hazards"]["frost"]["wells"] = [{"id": 19, "x": 125, "y": 126, "z": 150, "water": "water"}]
    s["projects"]["max_open"] = 4
    s["projects"]["open"] = [{"id": i, "kind": "rooms", "phase": "furnish"} for i in range(4)]
    s["military"]["squads"] = [{"id": 1, "members": 10, "power": {"armed": 10}}]
    return s


@test("E: 90 dwarves on one well, every slot full: another well is asked (it returned in silence before)")
def _():
    s = e_fort()
    m = memory()
    m.well_failure = ""
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert p and p[0].action.get("extra") is True and p[0].action.get("urgent") is True, ([x.action for x in p], n)
    assert "one for every 40" in p[0].reason, p[0].reason
    # one slot more taken at most
    s["projects"]["open"].append({"id": 9, "kind": "rooms", "phase": "dig"})
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert not p and any("free building slot" in x for x in n), ([x.action for x in p], n)


@test("E: the ordinary extra well refused for no drop and no pond: the cavern well follows (not the same refusal each season)")
def _():
    s = e_fort()
    m = memory()
    m.well_failure = ""
    m.extra_well_failure = ("no open drop from a free floor inside the fort to clean water; no pond, brook or river "
                            "within 40 tiles of the surface entrances")
    m.last_fired["extra_well"] = 0
    p, n = [], []
    planner_wells._well_rule(s, m, {}, PLANNER_CONFIG, p, n)
    assert p and p[0].action.get("cavern") is True, ([x.action for x in p], n)


@test("record: an extra well refused for a full slot list is no refusal of the water")
def _():
    m = Memory()
    s = b_fort()
    record([(Proposal("well", {"type": "place_well", "extra": True}, "x", 5),
             {"ok": False, "rejected": True, "error": "already 4 unfinished building projects"})], s, m)
    assert m.extra_well_failure == "", m.extra_well_failure
    record([(Proposal("well", {"type": "place_well", "extra": True}, "x", 5),
             {"ok": False, "error": "no open drop"})], s, m)
    assert m.extra_well_failure == "no open drop", m.extra_well_failure


@test("dwarves_per_well is 40")
def _():
    assert PLANNER_CONFIG["dwarves_per_well"] == 40


# ---- 3. a well counts only when it serves, weighed against the civilians ----------------

@test("shelter pick's water test: one well for 90 civilians is short; for 20 it holds them; drink alone as before")
def _():
    need90 = planner_shelter._needs(90, PLANNER_CONFIG)
    assert any("1 well(s) for 90" in x for x in planner_shelter._shortfalls(500, 0, 1, 1000, need90))
    assert not planner_shelter._shortfalls(500, 0, 3, 1000, need90)
    need20 = planner_shelter._needs(20, PLANNER_CONFIG)
    assert not planner_shelter._shortfalls(500, 0, 1, 1000, need20)
    assert any("no well" in x for x in planner_shelter._shortfalls(500, 10, 0, 1000, need20))
    assert not planner_shelter._shortfalls(500, 40, 0, 1000, need20)


def society_world():
    import test_society as TS
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, df = lua.execute(TS.SHELTER_FAKE, TS.module_src("ai-society.lua"))
    return lua, env, df


@test("refresh_shelter (E): a picked level with one well for 90 civilians is widened to the whole fort's three wells")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, env, df = society_world()
    lua.execute(r"""local env = ...
        CALLS = {}
        local rq = env.reqscript
        env.reqscript = function(n)
          if n == 'ai-shelter-plan' then return {pick_levels = function() return {[15] = true} end} end
          if rq then return rq(n) end
          error('reqscript ' .. n)
        end
        env.fill_shelter = function(b, only)
          table.insert(CALLS, only and 'picked' or 'whole')
          if only then return 10, {drink_units = 0, well_tiles = 1, drink_tiles = 0, civs = 90} end
          return 500, {drink_units = 20, well_tiles = WHOLE_WELLS, drink_tiles = 5, civs = 90}
        end""", env)
    lua.execute("WHOLE_WELLS = 3")
    r = env.refresh_shelter()
    assert list(lua.eval("CALLS").values()) == ["picked", "whole"] and r.widened_for_drink and r.tiles == 500, dict(r)
    # the whole fort no better (its one well is the picked one): the pick kept, not dry
    lua.execute("CALLS = {}; WHOLE_WELLS = 1")
    lua.execute("""local env = ...; local f = env.fill_shelter
        env.fill_shelter = function(b, only) local n, i = f(b, only); if not only then i.drink_units = 0 end; return n, i end""", env)
    r = env.refresh_shelter()
    assert list(lua.eval("CALLS").values()) == ["picked", "whole", "picked"] and not r.widened_for_drink and not r.dry, dict(r)
    # 20 civilians: one well is water enough, no widening
    lua.execute(r"""local env = ...; CALLS = {}
        env.fill_shelter = function(b, only)
          table.insert(CALLS, only and 'picked' or 'whole')
          return 10, {drink_units = 0, well_tiles = 1, drink_tiles = 0, civs = 20}
        end""", env)
    r = env.refresh_shelter()
    assert list(lua.eval("CALLS").values()) == ["picked"], list(lua.eval("CALLS").values())


@test("shelter supplies: a well with its shaft shut or ice (well_gives_water false), or no citizen's walk group beside it, is no well")
def _():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    lua, env, df = society_world()
    lua.execute(r"""local env = ...
        local function vec(list)
            local t = {}
            for i, v in ipairs(list or {}) do t[i - 1] = v end
            return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end})
        end
        local function well(x, gives)
            return {centerx = x, centery = 5, z = 2, gives = gives,
                    getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
        end
        env.df.global.world.buildings.other.WELL = vec({well(5, true), well(9, false), well(40, true)})
        env.df.global.world.items = {other = {DRINK = vec({})}}
        env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
        env.dfhack.units.getCitizens = function() return {{pos = {x = 6, y = 5, z = 2}}} end
        -- x 0-20 one walk group (the citizens'); x 30+ another (cut off)
        env.dfhack.maps = {getWalkableGroup = function(p) return p.x < 30 and 1 or 2 end}
        local rq = env.reqscript
        env.reqscript = function(n)
          if n == 'ai-society-burrows' then return {well_gives_water = function(b) return b.gives end} end
          if rq then return rq(n) end
          error('reqscript ' .. n)
        end""", env)
    out, units, wells, food = env.shelter_supplies()
    xs = sorted(w.x for w in wells.values())
    assert xs == [5], xs
    # the game can't tell walk groups: every well that gives water counts
    lua.execute("local env = ...; env.dfhack.maps = nil", env)
    out, units, wells, food = env.shelter_supplies()
    assert sorted(w.x for w in wells.values()) == [5, 40]


finish()
