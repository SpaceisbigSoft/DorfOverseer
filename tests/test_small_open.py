"""(0.105.24) Tests for Phase 12's small open items and the loops of the 2-5 Nov
run: the quarry's count, stone orders cancelled for want of stone, work that
nobody can do, actions done again for the same reason, the traction patient
in an ordinary bed (lua/ai-health.lua, in a real Lua engine with a small fake
of the game: pip install lupa), and the mayor's meetings with visitors.

    python tests/test_small_open.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import PLANNER_CONFIG, Memory, Proposal, abs_tick, note_cycle, plan, record, select  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


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


# --- the quarry's count -------------------------------------------------------

@test("quarry: the count is 10-30 whatever Mining says (the bridge takes 1-30; A, B, D, E asked 60)")
def _():
    from planner import mining_plan
    for m in (-200, -100, 0, 50, 100, 200):
        q = mining_plan({"mining": m}, PLANNER_CONFIG)["quarry"]
        assert 10 <= q <= 30, (m, q)
    assert mining_plan({"mining": -100}, PLANNER_CONFIG)["quarry"] < mining_plan({}, PLANNER_CONFIG)["quarry"] \
        < mining_plan({"mining": 100}, PLANNER_CONFIG)["quarry"] == 30
    bridge = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "int_in(a.count or 30, 1, 30)" in bridge          # what the bridge takes (the clamp's other half)


# --- stone orders cancelled for want of stone ---------------------------------

@test("stone: a stone order cancelled for want of stone is booked as stuck, and the door is then ordered in wood")
def _():
    s = fort()
    s["stone_use"] = {"usable": 0, "economic": {}}
    s["orders"] = [{"id": 41, "recipe": "stone_door", "job": "ConstructDoor", "amount_left": 1,
                    "amount_total": 1, "by_ai": True}]
    m = Memory()
    note_cycle(s, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 15 * 1200
    st = by_rule(plan(later, m)[0], "stone")
    assert st and st[0].action == {"type": "cancel_work_order", "order_id": 41, "stuck": "stone_door"}, st
    record([(st[0], {"ok": True, "cancelled": True})], later, m)
    assert "stone_door" in m.stuck_cancelled, m.stuck_cancelled
    # buildingplan still waits for a door: the planned-parts rule asks stone_door, select() makes it wood
    later["orders"] = []
    p = Proposal("planned_parts", {"type": "work_order", "recipe": "stone_door", "amount": 1},
                 "1 planned building part(s) wait for a door", 3, True)
    later["buildings"]["workshops"]["Carpenters"] = max(1, int(later["buildings"]["workshops"].get("Carpenters") or 0))
    allowed, held = select([p], later, m)
    assert allowed and allowed[0].action["recipe"] == "wooden_door", (allowed, held)


# --- work that nobody can do --------------------------------------------------

@test("labour: one quire job waiting with nobody holding bookbinding gets a dwarf; with holders it waits for 3")
def _():
    from planner_industry import _labor_waiting_rule
    cfg = dict(PLANNER_CONFIG)
    p = []
    _labor_waiting_rule({"waiting": [{"labor": "BOOKBINDING", "jobs": 1, "holders": 0, "idle": 0}]}, 90, cfg, p)
    assert p and p[0].action == {"type": "assign_labor", "job": "BOOKBINDING", "count": 1}, p
    p = []
    _labor_waiting_rule({"waiting": [{"labor": "BOOKBINDING", "jobs": 1, "holders": 2, "idle": 0}]}, 90, cfg, p)
    assert not p, p
    p = []          # a detail set to nobody is the player's word, still
    _labor_waiting_rule({"waiting": [{"labor": "PAPERMAKING", "jobs": 1, "holders": 0, "idle": 0,
                                      "mode": "NobodyDoesThis"}]}, 90, cfg, p)
    assert not p, p


# --- done again for the same reason -------------------------------------------

def _crossbow(reason="4 crossbow soldiers and 3 with a crossbow: make 1 at the bowyer's"):
    return Proposal("arms", {"type": "work_order", "recipe": "wooden_crossbow", "amount": 1}, reason, 3, True)


@test("no effect: a crossbow ordered 4 times for the same reason is held 56 days, then tried once more")
def _():
    s = fort()
    s["orders"] = []
    s["buildings"]["workshops"]["Bowyers"] = 1
    m = Memory()
    cd = PLANNER_CONFIG["rule_cooldown_ticks"]
    for i in range(PLANNER_CONFIG["no_effect_max"]):
        allowed, held = select([_crossbow()], s, m)
        assert allowed, (i, held)
        record([(allowed[0], {"ok": True, "order_id": 100 + i})], s, m)
        s["date"]["tick"] += max(cd, 7 * 1200)
        m.orders_by_day.clear()
    allowed, held = select([_crossbow()], s, m)
    assert not allowed and any("same reason" in h and "hunter" in h for h in held), held
    # another reason (a soldier armed, or a new one): asked at once
    allowed, _ = select([_crossbow("4 crossbow soldiers and 4 with a crossbow: make 1")], s, m)
    assert allowed
    # the hold runs out: once more
    s["date"]["tick"] += PLANNER_CONFIG["no_effect_hold_days"] * 1200
    allowed, _ = select([_crossbow()], s, m)
    assert allowed
    # a refusal doesn't count; other rules aren't watched
    m2 = Memory()
    for _ in range(6):
        record([(Proposal("drink", {"type": "work_order", "recipe": "brew_drink", "amount": 5}, "same", 3, True),
                 {"ok": True})], s, m2)
    assert not m2.no_effect
    assert Memory.from_dict(m.to_dict()).no_effect == m.no_effect


@test("no effect: the same one quiver handed out 4 times is held, with why")
def _():
    s = fort()
    m = Memory()
    q = Proposal("quivers", {"type": "assign_quivers", "limit": 1},
                 "1 crossbow soldier(s) without a quiver (they can't carry bolts) and 1 free: give them one", 3)
    for _ in range(4):
        allowed, _ = select([q], s, m)
        assert allowed
        record([(q, {"ok": True, "assigned": 1, "left": 0})], s, m)
        s["date"]["tick"] += 8 * 1200
    allowed, held = select([q], s, m)
    assert not allowed and any("takes it back" in h for h in held), held


# --- traction (planner) ----------------------------------------------------------

def _traction_state(in_bed=1, free=1, benches=1, waited=10):
    s = fort()
    s["infection"] = {"infected": 0, "traction": {"waiting": 1, "in_bed": in_bed, "on_bench": 0,
                                                   "benches": benches, "benches_free": free, "got_up": 0}}
    s["health"] = dict(s.get("health") or {}, patients=[{"id": 77, "name": "Tulon", "needs": ["immobilize", "traction"],
                                                         "job": "Rest", "on": "Bed", "in_hospital": True}])
    m = Memory()
    m.patient_since = {"77": abs_tick(s) - waited * 1200}
    return s, m


@test("traction: a patient in an ordinary bed a week with a bench free is got up; not new, not with no bench free")
def _():
    from planner_care import _traction_rest_rule
    cfg = PLANNER_CONFIG
    s, m = _traction_state()
    p, notes = [], []
    _traction_rest_rule(s, cfg, p, notes, m)
    assert p and p[0].action == {"type": "traction_rest", "max": 1} and "Tulon" in p[0].reason, p
    s, m = _traction_state(waited=2)
    p = []
    _traction_rest_rule(s, cfg, p, [], m)
    assert not p                                                     # DF may still be moving him
    s, m = _traction_state(free=0)
    p, notes = [], []
    _traction_rest_rule(s, cfg, p, notes, m)
    assert not p and any("every traction bench is taken" in n for n in notes), notes
    s, m = _traction_state(benches=0, free=0)
    p, notes = [], []
    _traction_rest_rule(s, cfg, p, notes, m)
    assert not p and any("no finished traction bench" in n for n in notes), notes
    s, m = _traction_state(in_bed=0)
    p = []
    _traction_rest_rule(s, cfg, p, [], m)
    assert not p                                                     # on the bench, or up: DF's doctors
    s, m = _traction_state()
    props = by_rule(plan(s, m)[0], "traction_rest")
    assert props, "the rule isn't wired into plan()"
    import overseer
    assert "traction bench" in overseer.short({"type": "traction_rest"})


# --- traction (the bridge, lua/ai-health.lua) ----------------------------------

try:
    from lupa import LuaRuntime
except ImportError:
    LuaRuntime = None

HEALTH = (ROOT / "lua" / "ai-health.lua").read_text(encoding="utf-8")

FAKE = r"""
local src, spec = ...
local REST = 7
local units, jobs = {}, {}
for _, u in ipairs(spec.units) do
    local job = nil
    if u.rest then job = {id = 600 + u.id, job_type = REST, pos = {x = u.x, y = u.y, z = 0}} end
    table.insert(units, {id = u.id, pos = {x = u.x, y = u.y, z = 0}, job = {current_job = job},
                         health = {flags = {rq_traction = u.traction == true}}, body = {wounds = {}},
                         military = {squad_id = -1}})
end
-- furniture: {x, y, kind, built}
local furn = {}
for i, f in ipairs(spec.furniture) do
    table.insert(furn, {id = 700 + i, centerx = f[1], centery = f[2], z = 0, kind = f[3], users = {unit = {}},
                        getType = function() return f[3] end,
                        getBuildStage = function() return f[4] == false and 0 or 3 end,
                        getMaxBuildStage = function() return 3 end})
end
local zone = {id = 900, contained_buildings = furn}
local loc = {id = 4, getType = function() return 2 end,
             getContents = function() return {building_ids = spec.no_hospital and {} or {900}} end, occupations = {}}
local removed, site_data = {}, {}
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {cur_year = 50, cur_year_tick = spec.tick or 1000,
              world = {units = {active = units}, jobs = {list = {}}}},
    abstract_building_type = {[2] = 'HOSPITAL'},
    building_type = {[1] = 'Bed', [2] = 'TractionBench'},
    building = {find = function(id) return id == 900 and zone or nil end},
    unit = {find = function(id) for _, u in ipairs(units) do if u.id == id then return u end end end},
    job_type = {Rest = REST},
    unit_labor = {CLEAN = 1, DIAGNOSE = 2},
}
env.dfhack = {
    world = {getCurrentSite = function() return {id = 1, buildings = {loc}} end},
    units = {getCitizens = function() return units end, getReadableName = function(u) return 'dwarf ' .. u.id end},
    buildings = {findAtTile = function(pos)
        for _, f in ipairs(furn) do if f.centerx == pos.x and f.centery == pos.y then return f end end end,
        findCivzonesAt = function() return {zone} end},
    job = {removeJob = function(j)
        table.insert(removed, j.id)
        for _, u in ipairs(units) do if u.job.current_job == j then u.job.current_job = nil end end
        return true end},
    persistent = {getSiteData = function(k, d) return site_data[k] or d end,
                  saveSiteData = function(k, v) site_data[k] = v end},
}
local function fresh()
    local e = setmetatable({}, {__index = env})
    assert(load(src, 'ai-health', 't', e))()
    return e
end
local mod = fresh()
mod.reload = fresh
return mod, removed
"""


def traction_world(units, furniture, **kw):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    return lua.execute(FAKE, HEALTH, lt({"units": units, "furniture": furniture, **kw}))


if LuaRuntime is not None:
    @test("traction_rest (lua): the patient resting in a bed is got up while a bench stands free; once a month; the survey counts")
    def _():
        units = [{"id": 1, "x": 1, "y": 1, "traction": True, "rest": True},       # in a bed
                 {"id": 2, "x": 2, "y": 1, "traction": True, "rest": True},       # on the bench already
                 {"id": 3, "x": 3, "y": 1, "rest": True}]                          # in a bed, no traction asked
        furniture = [(1, 1, 1), (2, 1, 2), (3, 1, 1), (5, 5, 2)]                    # beds 1,3; benches 2 (taken), 5
        env, removed = traction_world(units, furniture)
        t = env.survey().traction
        assert (t.waiting, t.in_bed, t.on_bench, t.benches, t.benches_free) == (2, 1, 1, 2, 1), \
            (t.waiting, t.in_bed, t.on_bench, t.benches, t.benches_free)
        d = env.traction_rest(1, True)
        assert d.ok and d.dry_run and len(removed) == 0
        r = env.traction_rest(1, False)
        assert r.ok and r.got_up[1].unit_id == 1 and list(removed.values()) == [601], (dict(r), list(removed.values()))
        again = env.reload()
        r2 = again.traction_rest(1, False)
        assert not r2.ok and r2.rejected and "got up lately" in r2.error, dict(r2)   # kept in the save

    @test("traction_rest (lua): none without a free finished bench, or a hospital")
    def _():
        units = [{"id": 1, "x": 1, "y": 1, "traction": True, "rest": True}]
        env, removed = traction_world(units, [(1, 1, 1), (5, 5, 2, False)])           # the bench not built
        r = env.traction_rest(1, False)
        assert not r.ok and "no free, finished traction bench" in r.error and len(removed) == 0, dict(r)
        env, _ = traction_world(units, [(1, 1, 1), (5, 5, 2)], no_hospital=True)
        assert "no hospital zone" in env.traction_rest(1, False).error

    @test("traction_picks (pure): only those needing traction, resting, on a bed, not got up lately")
    def _():
        lua = LuaRuntime(unpack_returned_tuples=True)
        pure = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                           "assert(load(src, 'h', 't', e))(); return e", HEALTH)
        rows = [{"id": 9, "traction": True, "resting": True, "on": "Bed"},
                {"id": 3, "traction": True, "resting": True, "on": "Bed"},
                {"id": 4, "traction": True, "resting": False, "on": "Bed"},
                {"id": 5, "traction": True, "resting": True, "on": "TractionBench"},
                {"id": 6, "traction": True, "resting": True, "on": "Bed", "up": True}]
        picks = pure.traction_picks(lua.table_from([lua.table_from(r) for r in rows]), 5)
        assert [p.id for p in picks.values()] == [3, 9]

    @test("traction_rest is in the bridge's action table, bounded 1-3")
    def _():
        src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
        assert "traction_rest = act_traction_rest" in src and "int_in(a.max or 1, 1, 3)" in src


# --- the mayor's meetings ---------------------------------------------------------

@test("complaints: meetings with visitors are counted in the note, with what would lessen them")
def _():
    from planner_society import _complaint_notes
    s = fort()
    s["census"] = s.get("census") or {}
    s["stress"] = {"causes": [{"thought": "UnableComplain", "citizens": 9, "about": {"vent_at_boss": 6}}]}
    s["offices"] = {"offices": {"MAYOR": {"held": ["Oddom Nomaluker"]}}}
    s["meetings"] = {"activities": [{"actor": "Mosus, Poet", "noble": "Oddom Nomaluker, mayor", "visitor": True}],
                     "requests": 4, "requests_visitors": 2}
    s["noble_rooms"] = {"nobles": []}
    import planner_society
    real = planner_society.stress_causes
    planner_society.stress_causes = lambda st: st["stress"]["causes"]
    try:
        notes = []
        _complaint_notes(s, PLANNER_CONFIG, notes)
    finally:
        planner_society.stress_causes = real
    assert notes and "3 of those meetings are with visitors" in notes[0] and "Outsiders" in notes[0], notes


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
