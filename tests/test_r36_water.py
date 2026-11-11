"""(0.105.36, group water) The focused audit's D4 findings: a work retired
twice no longer blocks the other water works (the brain skips it, the bridge
stamps its refusal); a cavern well shut for a danger near it still counts as a
well; flood shuts counted only near the work and within 28 days; a reopen
starts the stall clocks again; leak-watch holds looked at again (the floodgate
placed again, a dried room un-held) and not busy for other works; the screw
pumps set to "Start pump manually" while the stack fills; the drink swap only
where the bridge says a brewable crop grows on that plot; the well's retry
timed from the furnish refusal; unknown drink not short for an unfound cavern.

    python tests/test_r36_water.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from planner import PLANNER_CONFIG as CFG, Memory  # noqa: E402
import planner_core  # noqa: E402
import planner_farms  # noqa: E402
import planner_water  # noqa: E402
import planner_wells  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = (ROOT / "lua" / "ai-waterworks.lua").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_waterworks.py").read_text(encoding="utf-8"),
                 re.S).group(1)
LUA = LuaRuntime(unpack_returned_tuples=True) if LuaRuntime else None
DAY = 1200
YEAR = 403200


def T(**kw):
    return LUA.table_from(kw)


def L(*items):
    return LUA.table_from(list(items))


def step(env, kind, **kw):
    return env.step(kind, T(**kw))


def works(W):
    return W.saved["ai-overseer/waterworks"].works


def moat_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(40, 61):
        for y in range(30, 51):
            W.set(x, y, 100, T(outside=False))
    W.entrances = L(T(x=50, y=50, z=100, id=1))
    W.citizens = L(T(x=50, y=40, z=100), T(x=52, y=40, z=100))
    for y in range(52, 58):
        W.set(40, y, 99, T(shape="FLOOR", material="RIVER", liquid=True, depth=7, outside=True))
        W.set(40, y, 100, T(shape="EMPTY", outside=True))
    W.survey = T(bodies=L(T(kind="river", tiles=6, nearest=T(x=40, y=54, z=99))))
    return env, W


def irrigation_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 95, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=95), T(x=60, y=61, z=95))
    W.set(70, 60, 94, T(shape="FLOOR", liquid=True, depth=7))
    return env, W


def pump_world():
    env = LUA.execute(FAKE, SRC)
    W = env.W
    for x in range(30, 90):
        for y in range(40, 80):
            W.set(x, y, 90, T(shape="FLOOR"))
    W.citizens = L(T(x=60, y=60, z=90), T(x=61, y=60, z=92))
    W.set(60, 60, 86, T(shape="FLOOR", liquid=True, depth=7))
    W.survey = T(bodies=L(T(kind="pool", tiles=1, nearest=T(x=60, y=60, z=86))))
    return env, W


def to_filling(env, W, kind):
    step(env, kind)
    step(env, kind)
    wk = works(W)[kind]
    W.dig_all(wk.plan.dig)
    if wk.plan.dig2:
        step(env, kind)
        W.dig_all(wk.plan.dig2)
    assert step(env, kind).stage == "building"
    W.build_all()
    assert step(env, kind).stage == "linking"
    assert step(env, kind).stage == "filling"
    r = step(env, kind)
    assert r.plug_dug, dict(r)
    return works(W)[kind]


def soak(W, wk):
    """A citizen in deep water on the work's own tiles."""
    c = wk.plan.wet[1]
    W.set(c.x, c.y, c.z, T(liquid=True, depth=7))
    W.citizens = L(T(x=c.x, y=c.y, z=c.z))


def water_fort(works_, refused, **kw):
    s = {"settings": {"traits": {"fortification": 100, "engineering": 0}}, "dwarves": {"total": 60},
         "date": {"year": 10, "tick": 100000}, "others_on_map": {}, "hazards": {"wet": []},
         "water": {"bodies": [{"kind": "river", "tiles": 30, "nearest": {"x": 1, "y": 1, "z": 1}}]},
         "entrances": {"entrances": [{"kind": "surface", "id": 1}]},
         "buildings": {"workshops": {}, "furnaces": {}, "other": {}},
         "waterworks": {"works": works_, "refused": refused}}
    s.update(kw)
    return s


def run_rule(s, m=None):
    props, notes = [], []
    planner_water._waterworks_rule(s, m, CFG, props, notes)
    return props, notes


def no_soil():
    m = Memory()
    m.farm_failure = "no soil within reach"
    return m


# ---- High: a work retired twice --------------------------------------------------------------

@test("D4 High: a moat retired twice (the bridge never begins it again) is skipped: irrigation is proposed")
def _():
    s = water_fort({"moat": {"kind": "moat", "stage": "retired", "why": "leaked"}},
                   {"moat": {"tick": 1 * YEAR, "why": "retired: leaked", "retired": 2}})
    props, _n = run_rule(s, no_soil())
    assert [p.rule for p in props] == ["waterworks_irrigation"], [(p.rule, p.action) for p in props]
    # retired once: the moat again after the retry wait (as before)
    s["waterworks"]["refused"]["moat"]["retired"] = 1
    props, _n = run_rule(s, no_soil())
    assert [p.rule for p in props] == ["waterworks_moat"], [(p.rule, p.action) for p in props]


@test("D4 High: the bridge stamps the refusal of a twice-retired work (a new tick, `retired` kept)")
def _():
    env, W = moat_world()
    to_filling(env, W, "moat")
    st = env.load_state()
    st.works["moat"].stage = "held"
    st.works["moat"].why = "leaked"
    env.save_state(st)
    step(env, "moat", retire=True, why="leaked")
    st = env.load_state()
    st.retired_n["moat"] = 2
    env.save_state(st)
    W.tick += 60 * DAY
    r = step(env, "moat")
    ref = env.load_state().refused["moat"]
    assert "retired 2 times" in r.error and r.retired == 2, dict(r)
    assert ref.tick == W.tick and ref.retired == 2, dict(ref)
    # a dry run changes nothing
    W.tick += DAY
    step(env, "moat", dry_run=True)
    assert env.load_state().refused["moat"].tick == W.tick - DAY


# ---- Med: a cavern well shut for a danger ----------------------------------------------------

def well_state(lid):
    return {"settings": {"traits": {}}, "dwarves": {"total": 60, "needs_medical_care": 0},
            "society": {"parched": 0}, "stocks": {"drink": 900}, "military": {"soldiers": 6},
            "buildings": {"other": {"Well": 1}, "zones": {"Hospital": 1}},
            "projects": {"open": [], "max_open": 2, "well_lids": [lid]},
            "date": {"year": 5, "tick": 1000, "season": "spring"}, "deep": {}, "others_on_map": {},
            "map": {"layers": []}}


@test("D4 Med: a cavern well's shaft shut for a creature near it still counts: no second cavern well")
def _():
    s = well_state({"project_id": 9, "gate": "closed", "x": 1, "y": 1, "elevation": -40,
                    "watch_near": {"name": "a giant cave spider"}})
    m = Memory()
    m.well_failure = "no clean water inside the fort to channel a well over"
    m.cavern_shaft_stairs = True
    m.well_floor_retried = True
    props, notes = [], []
    planner_wells._well_rule(s, m, {}, CFG, props, notes)
    assert not props, [(p.rule, p.action) for p in props]
    assert any("still counted as a well" in n for n in notes), notes
    # shut with no danger near: not a well (the B4 rule), the well rule goes on
    s["projects"]["well_lids"][0].pop("watch_near")
    props, notes = [], []
    planner_wells._well_rule(s, m, {}, CFG, props, notes)
    assert props and props[0].rule == "well", [(p.rule, p.action) for p in props]


@test("D4 Med: no cavern well is begun while a danger is near the cavern well's shaft (extra-well path)")
def _():
    s = well_state({"project_id": 9, "gate": "open", "x": 1, "y": 1, "elevation": -40,
                    "watch_near": {"name": "a giant cave spider"}})
    s["dwarves"]["total"] = 200
    m = Memory()
    m.extra_well_failure = "the only water below is in a cavern"
    m.cavern_shaft_stairs = True
    m.well_floor_retried = True
    props, notes = [], []
    planner_wells._well_rule(s, m, {}, CFG, props, notes)
    assert not any(p.action.get("cavern") for p in props), [(p.rule, p.action) for p in props]
    assert any("giant cave spider is near the cavern well" in n for n in notes), notes


# ---- Med: flood shuts --------------------------------------------------------------------------

@test("D4 Med: floods a year apart, or far from the work, never hold a done moat")
def _():
    env, W = moat_world()
    wk = to_filling(env, W, "moat")
    wk.stage = "done"
    soak(W, wk)
    for _ in range(3):
        W.tick += YEAR
        step(env, "moat", shut=True, why="dwarves in deep water")
        assert works(W).moat.stage == "done", works(W).moat.why
        W.tick += 4 * DAY
        assert step(env, "moat", reopen=True).reopened
    assert works(W).moat.shuts == 1
    # three floods in a week, dwarves in water only far away: not counted (the last near one still is)
    W.citizens = L(T(x=2, y=2, z=99))
    W.set(2, 2, 99, T(liquid=True, depth=7))
    for _ in range(3):
        W.tick += 2 * DAY
        step(env, "moat", shut=True, why="dwarves in deep water")
    assert works(W).moat.stage == "done" and works(W).moat.shuts == 1, (works(W).moat.stage, works(W).moat.shuts)


@test("D4 Med: three floods near the work within 28 days: held (then retired by the AI), saying so")
def _():
    env, W = moat_world()
    wk = to_filling(env, W, "moat")
    soak(W, wk)
    for _ in range(3):
        W.tick += 5 * DAY
        r = step(env, "moat", shut=True, why="dwarves in deep water")
    assert r.stage == "held" and "3 times in 28 days" in works(W).moat.why, works(W).moat.why
    assert "by hand" not in works(W).moat.why


# ---- Med: a reopen moves the stall clocks ----------------------------------------------------

@test("D4 Med: irrigation shut at day 26 and reopened at day 30 isn't held at its next step")
def _():
    env, W = irrigation_world()
    to_filling(env, W, "irrigation")
    W.tick += 26 * DAY
    step(env, "irrigation")
    step(env, "irrigation", shut=True, why="dwarves in deep water")
    W.tick += 4 * DAY
    assert step(env, "irrigation", reopen=True).reopened
    r = step(env, "irrigation")
    assert r.stage != "held" and works(W).irrigation.stage == "filling", (r.stage, r.error)
    # ...and it is still held when no water comes in the next 28 days
    W.tick += 29 * DAY
    r = step(env, "irrigation")
    assert r.stage == "held" and "no water reached" in r.error, (r.stage, r.error)


@test("D4 Med: a moat shut at day 25 of filling and reopened isn't held at once; a pull not made is asked again")
def _():
    env, W = moat_world()
    to_filling(env, W, "moat")
    W.tick += 25 * DAY
    step(env, "moat")
    step(env, "moat", shut=True, why="dwarves in deep water")
    W.tick += 4 * DAY
    r = step(env, "moat", reopen=True)
    assert r.reopened and r.opening, dict(r)
    r = step(env, "moat")
    assert r.stage != "held" and "filling" in str(r.error), (r.stage, r.error)
    # the dwarf never pulls: the gate closed again (as if the pull was lost), asked again after 2 days
    gate = env.building(works(W).moat.plan.gate.x, works(W).moat.plan.gate.y, works(W).moat.plan.gate.z, "Floodgate")
    gate.closed = True
    works(W).moat.opened_once = None
    n = len(W.pulls)
    W.tick += 3 * DAY
    r = step(env, "moat")
    assert "on the way to open" in r.error and len(W.pulls) == n + 1, (r.error, len(W.pulls))


# ---- Med: leak-watch holds ------------------------------------------------------------------

WET_WHY = ("the farm room is still wet after 28 days (3 tile(s)): water is still getting in "
           "(the floodgate leaks, or a second way in); the AI keeps it watched")


@test("D4 Med: a leak-watch hold asks for a re-check and doesn't block the moat")
def _():
    s = water_fort({"irrigation": {"kind": "irrigation", "stage": "held", "gate": "shut", "why": WET_WHY}}, {})
    props, _n = run_rule(s, no_soil())
    acts = [p.action for p in props]
    assert {"type": "water_work", "kind": "irrigation", "recheck": True, "why": "recheck: the leak watch"} in acts, acts
    assert any(p.rule == "waterworks_moat" for p in props), acts
    assert not any(a.get("retire") for a in acts), acts
    rc = next(p for p in props if p.action.get("recheck"))
    assert overseer.short(rc.action) == "the muddied farm level: look again at its leak watch"
    # its floodgate open: shut it (as before), no re-check in the same cycle
    s["waterworks"]["works"]["irrigation"]["gate"] = "open"
    props, _n = run_rule(s, no_soil())
    assert any(p.action.get("shut") for p in props) and not any(p.action.get("recheck") for p in props)


@test("D4 Med: the bridge's re-check: a still-wet room stays held (gate shut); dried, it is finished")
def _():
    env, W = irrigation_world()
    to_filling(env, W, "irrigation")
    wk = works(W).irrigation
    r = wk.plan.room
    W.set(r.x1 + 1, r.y1 + 1, r.z, T(liquid=True, depth=1))
    assert step(env, "irrigation").stage == "drying"
    W.tick += 29 * DAY
    h = step(env, "irrigation")
    assert h.stage == "held" and "water is still getting in" in h.error and "by hand" not in h.error, dict(h)
    assert step(env, "irrigation").error == works(W).irrigation.why          # no recheck: unchanged
    r2 = step(env, "irrigation", why="recheck: the leak watch")
    assert r2.waiting and r2.stage == "held" and "still wet (1 tile" in r2.error, dict(r2)
    W.set(r.x1 + 1, r.y1 + 1, r.z, T(liquid=False, depth=0))
    W.mud[W.key(r.x1 + 1, r.y1 + 1, r.z)] = True
    r3 = step(env, "irrigation", why="recheck: the leak watch")
    assert r3.ok and r3.stage == "drying", dict(r3)
    assert step(env, "irrigation").stage == "finishing"
    assert step(env, "irrigation").stage == "done"


@test("D4 Med: the floodgate gone: a new one placed where it stood, then built, linked and filled again")
def _():
    env, W = moat_world()
    wk = to_filling(env, W, "moat")
    g = wk.plan.gate
    gk = W.key(g.x, g.y, g.z) + "Floodgate"
    W.buildings[gk] = None
    r = step(env, "moat")
    assert r.stage == "held" and "the floodgate is gone" in r.error, dict(r)
    n = len(W.designated)
    r = step(env, "moat", recheck=True)
    assert r.waiting and "a new one is placed" in r.error, dict(r)
    new = [W.designated[i] for i in range(n + 1, len(W.designated) + 1)]
    assert [(d.x, d.y, d.z, d.text) for d in new] == [(g.x, g.y, g.z, "x")], [(d.x, d.y, d.text) for d in new]
    r = step(env, "moat", recheck=True)
    assert r.ok and r.stage == "building", dict(r)
    W.build_all()
    assert step(env, "moat").stage == "linking"
    assert step(env, "moat").stage == "filling"
    n = len(W.pulls)
    r = step(env, "moat")                # the new floodgate's lever pulled open (the old one's pulls were lost)
    assert len(W.pulls) == n + 1 and not W.pulls[n + 1].instant, (len(W.pulls), dict(r))
    r = step(env, "moat")
    assert r.waiting and "filling" in r.error and works(W).moat.opened_once, dict(r)


# ---- Med: the pumps worked by hand ------------------------------------------------------------

@test("D4 Med: the stack's screw pumps are set to 'Start pump manually' while it fills, unset when done")
def _():
    env, W = pump_world()
    wk = to_filling(env, W, "pump")
    pumps = [b for b in wk.plan.builds.values() if b.kind == "ScrewPump"]
    assert pumps
    r = step(env, "pump")
    assert r.waiting and "pumping" in r.error, dict(r)
    ids = [env.building(b.x, b.y, b.z, "ScrewPump").id for b in pumps]
    assert all(W.manual[i] is True for i in ids), dict(W.manual)
    assert works(W).pump.manual == len(pumps) and works(W).pump.manual_since == W.tick
    row = env.report().works.pump
    assert row.manual == len(pumps) and row.manual_since == W.tick
    t = wk.plan.test
    W.set(t.x, t.y, t.z, T(liquid=True, depth=5))
    assert step(env, "pump").stage == "done"
    assert all(W.manual[i] is False for i in ids) and works(W).pump.manual is None


@test("D4 Med: a flood shut stops the pumps; the stall flag is cleared once the reservoir rises again")
def _():
    env, W = pump_world()
    wk = to_filling(env, W, "pump")
    t = wk.plan.test
    step(env, "pump")
    W.tick += 15 * DAY
    step(env, "pump")
    assert works(W).pump.stalled
    W.set(t.x, t.y, t.z, T(liquid=True, depth=2))
    step(env, "pump")
    assert works(W).pump.stalled is None
    step(env, "pump", shut=True, why="dwarves in deep water")
    ids = [env.building(b.x, b.y, b.z, "ScrewPump").id for b in wk.plan.builds.values() if b.kind == "ScrewPump"]
    assert all(W.manual[i] is False for i in ids)


@test("D4 Med: the brain gives the pump labour once the pumps are set by hand (and on a stall), never without")
def _():
    now = 10 * 403200 + 100000
    row = {"kind": "pump", "stage": "filling", "lift": 2, "manual": 2, "manual_since": now - 600}
    props, _n = run_rule(water_fort({"pump": row}, {}))
    lab = [p.action for p in props if p.action["type"] == "assign_labor"]
    assert lab == [{"type": "assign_labor", "job": "OPERATE_PUMP", "count": 2}], lab
    row["manual_since"] = now - 10 * DAY                 # pumping for a while, not stalled: not again
    props, _n = run_rule(water_fort({"pump": row}, {}))
    assert not [p for p in props if p.action["type"] == "assign_labor"]
    row2 = {"kind": "pump", "stage": "filling", "lift": 2, "stalled": True}   # pumps not set by hand: no labour
    props, _n = run_rule(water_fort({"pump": row2}, {}))
    assert not [p for p in props if p.action["type"] == "assign_labor"]


@test("D4 Med: the Lua sets building_screw_pumpst.pump_manually (df-structures' name)")
def _():
    code = "\n".join(line.split("--")[0] for line in SRC.splitlines())
    assert "pump_manually = on == true" in code


# ---- Lows ---------------------------------------------------------------------------------------

@test("D4 Low: no drink swap where the bridge says no brewable crop grows on that plot (its biome)")
def _():
    plot = {"id": 1, "underground": False, "biome": "desert_sand", "crops": ["FLAX", "", "", ""],
            "options": 1, "options_any": 1, "ok_now": True, "ai_now": True, "brew_options": 0}
    s = {"dwarves": {"total": 20}, "stocks": {"drink": 5}, "date": {"year": 3, "season": "spring"},
         "farms": {"season": "spring",
                   "crops": {"FLAX": {"brews": None, "seeds": 10, "seasons": ["spring"], "underground": False},
                             "STRAWBERRY_WILD": {"brews": "WINE", "seeds": 10, "seasons": ["spring"],
                                                 "underground": False}},
                   "plot_list": [plot]}}
    plots = planner_farms.farm_plots_live(s)
    assert planner_farms.drink_swap_wanted(s, plots) is False
    plot["brew_options"] = 1
    assert planner_farms.drink_swap_wanted(s, planner_farms.farm_plots_live(s)) is True
    lua = (ROOT / "lua" / "ai-builder-farms.lua").read_text(encoding="utf-8")
    assert "p.brew_options = nb" in lua


@test("D4 Low: the well retry is timed from the furnish refusal, not the place_well")
def _():
    m = Memory()
    m.last_fired["well"] = 100
    planner_core._record_any_outcome({"type": "furnish_project", "project_id": 3},
                                     {"ok": False, "error": "the game would not place the well over the hole"},
                                     {}, m, 50000)
    assert m.last_fired["well"] == 50000 and "place the well" in m.well_failure


@test("D4 Low: texts: no 'by hand' in the works' holds; the reopen label; the retire words")
def _():
    holds = re.findall(r"hold\(\(?'([^']*)'", SRC)
    assert holds and not any("by hand" in h for h in holds), holds
    assert "mend it by hand" not in SRC and "link it by hand" not in SRC and "dry it by hand" not in SRC
    assert overseer.short({"type": "water_work", "kind": "moat", "reopen": True}) == \
        "open the moat's floodgate again (the flood is over)"
    s = water_fort({"irrigation": {"kind": "irrigation", "stage": "held", "why": "the floor dried without mud"}}, {})
    props, _n = run_rule(s)
    assert "tried again elsewhere" not in props[0].reason and "old site only if" in props[0].reason


@test("D4 Low: ai_opens_cavern: no stocks section is not 'short of water'; the docstring says three-state")
def _():
    s = {"settings": {"traits": {}}, "dwarves": {"total": 40}, "society": {"parched": 0},
         "military": {"squads": [{"members": 10}]}}
    ok, why = planner_wells.ai_opens_cavern(s, CFG)
    assert not ok and "not known" in why, why
    s["stocks"] = {"drink": 0}
    ok, why = planner_wells.ai_opens_cavern(s, CFG)
    assert ok and "drink is down" in why, why
    doc = planner_wells.ai_opens_cavern.__doc__
    assert "off (its default)" not in doc and "three-state" in doc


if __name__ == "__main__":
    finish(None if LuaRuntime else "lupa is not installed")
