"""(0.105.46, I4) Collapse recovery: a fallen fort in survival mode.

B fell from 100 to 1 (thirst), E from 58 to 23, F from 100 to 46 (a titan);
D (the Hermit hold, Outsiders -150) sat at 15 for ten years and then 8, DF
sending no migrants. Tested here:
  * entering (under the floor max(12, a quarter of the peak); a fall of a
    third in a game year) and leaving (at the floor a season); a new fort of
    7 is not a fallen one; Extreme-low Growth never; the peak from the timeline;
  * the holds: hunts, kill zones, lures, missions, landmarks, new non-survival
    levels wait; water, wells, drink, food, beds, the hospital, the guard,
    the gates go on (and urgent levels, a mood's workshop);
  * the closed fort and its migrants: Outsiders never touches the cap; in
    recovery the cap opens past the strain hold, the baby caps rise; the
    player's own cap (Rules off) is a Needs you; a wave is called (force
    Migrants) after half a year with nobody, at most three times;
  * the digest's RECOVERY line, the journal, the Rules switch, the Lua
    module (the migration section and call_migrants) and the bridge wiring.

    python tests/test_r46_recovery.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan, note_cycle  # noqa: E402
from planner_core import Proposal, player_rules  # noqa: E402
import planner_growth  # noqa: E402
import planner_recovery as R  # noqa: E402
from digest import normalize, SECTION_DEFAULTS, digest  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 336 * DAY
HERMIT = {"outsiders": -150, "trade": -100, "growth": -60, "caution": 60, "surface": -60, "fortification": 100,
          "deference": -60}


def st(pop: int, tick: int, traits: dict | None = None, year: int = 260, **extra) -> dict:
    s = {"settings": {"traits": traits or {}, "set_pop_cap": True, "fort_goal": "expand"},
         "dwarves": {"total": pop}, "date": {"year": year, "tick": tick}, "society": {"pop_cap": 100}}
    s.update(extra)
    return s


def walk(memory: Memory, pops: list, start: int = 0, step_days: int = 7, traits=None) -> list:
    """note_recovery through a run of citizen counts, one a step; the notes."""
    notes: list = []
    t = start
    for p in pops:
        y, tick = 260 + t // YEAR, t % YEAR
        R.note_recovery(st(p, tick, traits, year=y), memory, CFG, notes)
        t += step_days * DAY
    return notes


# ---- entering and leaving -----------------------------------------------------------------

@test("enter: under the floor (max 12, a quarter of the peak) once the fort was over it; a new fort of 7 is not fallen")
def _():
    m = Memory()
    walk(m, [7, 7, 7, 8, 9, 10, 11])
    assert not R.in_recovery(m), m.recovery
    m = Memory()
    m.recovery = {"peak": 60, "peak_seeded": True}   # a high long ago: the floor is 15
    notes = walk(m, [16, 16, 14])
    r = R.in_recovery(m)
    assert r and r["floor"] == 15 and "under its floor of 15" in r["why"], r
    assert any(n.startswith("RECOVERY:") for n in notes), notes
    assert R.recovery_floor(CFG, 300) == 75 and R.recovery_floor(CFG, 20) == 12


@test("enter: a fall of a third within a game year (E 58 -> 23, F 100 -> 46), not from a small high, not a slow loss")
def _():
    m = Memory()
    walk(m, [58, 58, 50, 40, 23])
    r = R.in_recovery(m)
    assert r and "fell from 58 to 23" in r["why"], r
    m = Memory()
    walk(m, [100, 46])
    assert "fell from 100 to 46" in R.in_recovery(m)["why"]
    m = Memory()
    walk(m, [12, 12, 9])                       # a high under recovery_drop_min (15), never over the floor: no
    assert not R.in_recovery(m)
    m = Memory()
    walk(m, [60, 50], step_days=0)
    walk(m, [41], start=400 * DAY)             # the 60 is over a year old by then
    assert not R.in_recovery(m), m.recovery


@test("leave: at the floor or over it for a season (and a season in); the year's high starts again from there")
def _():
    m = Memory()
    walk(m, [100, 46])                         # in, at 46 (over its floor of 25)
    since = R.in_recovery(m)["since"]
    walk(m, [46] * 11, start=7 * DAY)          # 77 days: not yet
    assert R.in_recovery(m)
    notes = walk(m, [46, 46], start=since + 84 * DAY)
    assert not R.in_recovery(m) and any("recovery over" in n for n in notes), notes
    walk(m, [46], start=since + 100 * DAY)     # the same fall is not counted again
    assert not R.in_recovery(m), m.recovery
    ev = [e["event"] for e in R.recovery_journal(m)]
    assert ev == ["entered", "left"] and R.recovery_journal(m) == [], ev


@test("leave: under the floor the season's clock stops; a fall back under it starts it again")
def _():
    m = Memory()
    walk(m, [60, 60, 10])                      # floor 15
    assert R.in_recovery(m)["above_since"] is None
    walk(m, [16] * 10 + [12] + [16] * 10, start=21 * DAY)
    assert R.in_recovery(m)                    # above 70 days at most since the fall back to 12
    walk(m, [16] * 14, start=21 * DAY + 21 * 7 * DAY)
    assert not R.in_recovery(m)


@test("Extreme-low Growth shrinks on purpose: never recovery (and one under way ends)")
def _():
    m = Memory()
    walk(m, [60, 60, 10])
    assert R.in_recovery(m)
    walk(m, [9], start=30 * DAY, traits={"growth": -150})
    assert not R.in_recovery(m)


@test("the peak from the timeline: a fort that fell before this version knows its high")
def _():
    m = Memory()
    m.timeline = {"fields": ["day", "pop"], "days": [[87000, 30]], "seasons": [{"season": 1, "high": {"pop": 100}}],
                  "years": [{"year": 250, "high": {"pop": 88}}]}
    walk(m, [20])
    r = R.in_recovery(m)
    assert m.recovery["peak"] == 100 and r and r["floor"] == 25, m.recovery


@test("note_cycle runs it, a failure is a note; the save's memory keeps it (from_dict / to_dict)")
def _():
    m = Memory()
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = 60
    note_cycle(s, m)
    s2 = copy.deepcopy(BASE)
    s2["dwarves"]["total"] = 10
    s2["date"]["tick"] = int(s2["date"].get("tick") or 0) + 7 * DAY
    note_cycle(s2, m)
    assert R.in_recovery(m), m.recovery
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert R.in_recovery(m2)["floor"] == 15


# ---- the holds ----------------------------------------------------------------------------

def P(rule, **action):
    return Proposal(rule, action, "why", 5)


@test("holds: hunts, kill zones, lures, missions, landmarks, the hall, siege works, polish, a library wait")
def _():
    held = [P("hunt", type="hunt_send"), P("killzone", type="build_killzone"), P("lure_build", type="build_lure"),
            P("lure_open", type="lure_open"), P("mission", type="send_mission"), P("landmark_step", type="landmark_step"),
            P("hall", type="place_hall"), P("siege_engine", type="place_siege_engine"), P("polish", type="polish"),
            P("ladder", type="start_project", kind="library"), P("growth", type="start_project", kind="bedrooms",
                                                                  growth=True),
            P("killzone_parts", type="work_order", recipe="mechanisms"), P("expel", type="expel_dwarf"),
            P("wild_hunt", type="squad_orders"), P("gems", type="work_order")]
    for p in held:
        assert R.held_in_recovery(p), (p.rule, p.action)


@test("holds: water, wells, drink, food, beds, the hospital, the guard, the gates, urgent levels, a mood go on")
def _():
    kept = [P("water", type="water_zone"), P("well", type="place_well"), P("drink", type="work_order"),
            P("food", type="work_order"), P("farms", type="farm_plots"), P("rooms", type="give_room"),
            P("hospital", type="start_project", kind="hospital"), P("x", type="start_project", kind="bedrooms"),
            P("x", type="start_project", kind="tavern", urgent=True), P("mood", type="start_project", kind="library"),
            P("gates", type="close_threatened_gates"), P("gate_doors", type="build_gate_doors"),
            P("squad_make", type="make_squad"), P("fill", type="fill_squads"), P("pop_cap", type="set_population_cap"),
            P("lure_shut", type="lure_shut"), P("crafts", type="work_order"), P("burial", type="coffins"),
            P("infected_rest", type="rest_infected"), P("recovery_migrants", type="call_migrants")]
    for p in kept:
        assert not R.held_in_recovery(p), (p.rule, p.action)


@test("recovery_apply: only in recovery; the held said in one note; survival rules move up a step")
def _():
    props = [P("hunt", type="hunt_send"), P("drink", type="work_order")]
    m = Memory()
    assert R.recovery_apply(list(props), m, []) == props
    walk(m, [60, 60, 10])
    notes: list = []
    kept = R.recovery_apply([P("hunt", type="hunt_send"), P("drink", type="work_order")], m, notes)
    assert [p.rule for p in kept] == ["drink"] and kept[0].priority == 4, kept
    assert notes and "1 step(s) wait" in notes[0] and "hunt send" in notes[0], notes


@test("plan(): a fort in recovery proposes no hunts or ladder levels (the filter runs after every rule)")
def _():
    m = Memory()
    walk(m, [60, 60, 10])
    s = copy.deepcopy(BASE)
    props, notes = plan(s, m)
    assert not [p for p in props if R.held_in_recovery(p)], [(p.rule, p.action) for p in props if R.held_in_recovery(p)]


# ---- the closed fort and its migrants -------------------------------------------------------

def cap(citizens: int, traits: dict, society: dict, memory: Memory | None = None, goal: str = "expand",
        cfg=CFG) -> tuple:
    s = {"settings": {"traits": traits, "set_pop_cap": True, "fort_goal": goal},
         "society": society, "dwarves": {"total": citizens}, "date": {"year": 260, "tick": 0}}
    props, notes = [], []
    planner_growth._pop_cap_rule(s, memory or Memory(), cfg, citizens, props, notes)
    return props, notes


@test("closed fort: Outsiders never moves DF's population cap (visitors and trade only)")
def _():
    so = {"pop_cap": 0, "strict_pop_cap": 0}
    for o in (-200, -150, -50, 0, 100):
        p, _ = cap(40, {"outsiders": o}, dict(so))
        assert p and p[0].action["cap"] == 100 and p[0].action["strict"] == 120, (o, p)


@test("closed fort: in recovery the cap opens past the strain hold (D: 15 dwarves held at 15), baby caps raised")
def _():
    m = Memory()
    m.strain_hold = True
    m.strain_cap = 15
    so = {"pop_cap": 15, "strict_pop_cap": 25, "baby_cap": 0, "baby_pct": 0}
    unhappy = {"pop": 15}
    import outcomes
    real = outcomes.measure
    outcomes.measure = lambda s: {"drink_pd": 0, "pop": 15}     # strained: drink short
    try:
        cfg = dict(CFG, survival_floor=0)                  # the 0.105.44 floor apart
        p, _ = cap(15, HERMIT, dict(so), m, cfg=cfg)
        assert not p or p[0].action["cap"] == 15, p        # strained, not in recovery: held at its size
        walk(m, [60, 60, 15])                              # D fell: in recovery
        p, _ = cap(15, HERMIT, dict(so), m, cfg=cfg)
        a = p[0].action
        assert a["cap"] == 25 and a["strict"] == 35 and a["baby_cap"] == CFG["floor_baby_cap"], a
        assert "recovering" in p[0].reason and "not migrants" in p[0].reason, p[0].reason
    finally:
        outcomes.measure = real
    assert unhappy


@test("closed fort: Maintain keeps the player's size; Extreme-low Growth is left alone in recovery")
def _():
    m = Memory()
    walk(m, [60, 60, 10])
    m.maintain_pop = 12
    p, _ = cap(10, {}, {"pop_cap": 12, "strict_pop_cap": 12}, m, goal="maintain", cfg=dict(CFG, survival_floor=0))
    assert p and p[0].action["cap"] == 15, p           # the floor (15), not 10 over the citizens
    p, _ = cap(10, {"growth": -150}, {"pop_cap": 7, "strict_pop_cap": 7}, m, cfg=dict(CFG, survival_floor=0))
    assert not p or p[0].action["cap"] == CFG["min_citizens"], p


def mig_state(pop=10, pop_cap=30, mig=None, rules=None, threats=0, tick=0, year=262):
    s = {"settings": {"traits": {}, "set_pop_cap": True, **(rules or {})}, "dwarves": {"total": pop},
         "date": {"year": year, "tick": tick}, "society": {"pop_cap": pop_cap},
         "migration": {"force": "force", "queued": 0, "hermit_tool": False, "civ": True} if mig is None else mig,
         "others_on_map": {"threats_that_can_reach_dwarves": threats}}
    return s


def fallen(days_ago: int = 200) -> Memory:
    m = Memory()
    walk(m, [60, 60, 10], start=2 * YEAR - days_ago * DAY - 14 * DAY)
    return m


def mig(s, m):
    props, notes = [], []
    R._migrants_rule(s, m, CFG, props, notes)
    return props, notes


@test("migrants: half a year in recovery with nobody: a wave is called (force Migrants); sooner, nothing")
def _():
    p, n = mig(mig_state(), fallen(200))
    assert [x.action for x in p] == [{"type": "call_migrants"}], (p, n)
    p, n = mig(mig_state(), fallen(100))
    assert not p and not n, (p, n)


@test("migrants: a siege, a wave queued, or the cap shut by the AI's own rule: wait (a note), no call")
def _():
    m = fallen(200)
    for s in (mig_state(threats=3), mig_state(mig={"force": "force", "queued": 1}), mig_state(pop_cap=10)):
        p, n = mig(s, m)
        assert not p and n and not any("NEEDS" in x.upper()[:12] for x in n), (p, n)


@test("migrants: Needs you only when nothing else can be done (the player's cap, DFHack's hermit, no script, off, 3 calls)")
def _():
    from planner_core import NEEDS_YOU
    m = fallen(200)
    cases = [mig_state(pop_cap=10, rules={"set_pop_cap": False}),
             mig_state(mig={"force": "force", "queued": 0, "hermit_tool": True}),
             mig_state(mig={"force": None, "queued": 0}),
             mig_state(rules={"call_migrants": False})]
    for s in cases:
        p, n = mig(s, m)
        assert not p and n and n[0].startswith(NEEDS_YOU), (s, p, n)
    m.recovery["calls"] = [m.recovery["since"] + DAY * k for k in (170, 290, 400)]
    p, n = mig(mig_state(year=263), m)
    assert not p and n[0].startswith(NEEDS_YOU) and "3 migrant waves called" in n[0], n


@test("migrants: a call seen by note_recovery (last_fired) is counted and journalled; a newcomer resets the count")
def _():
    m = fallen(200)
    m.last_fired["recovery_migrants"] = 2 * YEAR - 5 * DAY + 260 * YEAR
    walk(m, [10], start=2 * YEAR)
    assert len(m.recovery["calls"]) == 1
    assert any(e["event"] == "migrants_called" for e in R.recovery_journal(m))
    walk(m, [14], start=2 * YEAR + 7 * DAY)                  # migrants came
    p, n = mig(mig_state(pop=14, tick=2 * YEAR % YEAR + 8 * DAY), m)
    assert not p, p                                            # nobody waits half a year now


@test("migrants: a fort stalled under the survival floor a year (D at 15) is called for too, not in recovery")
def _():
    m = Memory()
    walk(m, [15] * 52)                                        # a year at 15, peak 15 (floor 12): no recovery
    assert not R.in_recovery(m) and R.stalled(st(15, 0, year=261), m, CFG)
    p, n = mig(mig_state(pop=15, pop_cap=30, year=261, tick=7 * DAY), m)
    assert p and p[0].action == {"type": "call_migrants"} and "stalled" in p[0].reason, (p, n)


# ---- reporting and wiring -----------------------------------------------------------------

@test("digest: a RECOVERY line while recovering (s['_recovery'] from note_cycle); none otherwise")
def _():
    m = Memory()
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = 60
    note_cycle(s, m)
    assert "RECOVERY" not in digest(s)
    s2 = copy.deepcopy(BASE)
    s2["dwarves"]["total"] = 10
    s2["date"]["tick"] = int(s2["date"].get("tick") or 0) + 7 * DAY
    note_cycle(s2, m)
    line = [x for x in digest(s2).splitlines() if x.startswith("RECOVERY")]
    assert line and "floor 15 peak 60 now 10" in line[0], line
    assert SECTION_DEFAULTS["migration"] == {}


@test("wiring: the overseer's words and journal, the Rules switch (on by default), settings and the GUI")
def _():
    import overseer
    assert "call_migrants" in overseer.SHORT_WORDS
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert "recovery_journal(memory)" in src and '"kind": "recovery"' in src
    assert player_rules({"settings": {}})["call_migrants"] is True
    assert player_rules({"settings": {"call_migrants": False}})["call_migrants"] is False
    sset = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert "call_migrants = true," in sset and "'call_migrants'," in sset and "call_migrants = s.call_migrants," in sset
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert "view_id = 'call_migrants'" in gui and "self.subviews.call_migrants:setOption" in gui
    for k in ("recovery_floor_min", "recovery_floor_peak_share", "recovery_drop_share", "recovery_drop_min",
              "recovery_leave_days", "recovery_cap_room", "recovery_migrants_wait_days",
              "recovery_migrants_cooldown_ticks", "recovery_migrants_max_calls", "recovery_stall_days"):
        assert k in CFG, k


@test("bridge: the migration section (safe), call_migrants (dry run), the module listed")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "migration = function() return safe(function() return reqscript('ai-recovery').report() end) end," in src
    actions = src[src.index("ACTIONS = {"):src.index("DRY_OK = {}")]
    assert "call_migrants = function(a)" in actions and "reqscript('ai-recovery').call_migrants" in actions
    dry = src[src.index("DRY_OK = {}"):src.index("}) do DRY_OK[name] = true end")]
    assert "'call_migrants'" in dry
    mods = src[src.index("BRIDGE_MODULES = {"):src.index("}", src.index("BRIDGE_MODULES = {"))]
    assert "'ai-recovery'" in mods


FAKE = r"""
local src = ...
local W = {events = {}, scripts = {force = true}, ran = {}, rv = 0, hermit = nil, adds = 1}
local env = setmetatable({}, {__index = _G})
env.CR_OK = 0
env.df = {global = {timed_events = W.events, plotinfo = {civ_id = 10}},
          timed_event_type = {Migrants = 2, Caravan = 0},
          historical_entity = {find = function(id) if id == 10 then return {id = 10} end end}}
env.dfhack = {findScript = function(n) return W.scripts[n] and ('scripts/' .. n .. '.lua') or nil end,
              run_command_silent = function(...)
                  table.insert(W.ran, table.concat({...}, ' '))
                  for _ = 1, W.adds do table.insert(W.events, {type = 2}) end
                  return 'ok', W.rv
              end}
env.reqscript = function(name)
    if name == 'hermit' then return {isEnabled = function() return W.hermit end} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-recovery', 't', env))()
return env, W
"""


@test("lua: the migration report (force script, waves queued, DFHack's hermit, the civ)")
def _():
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-recovery.lua"))
    r = env.report()
    assert r.force == "force" and r.queued == 0 and r.civ is True and r.hermit_tool is False, dict(r)
    w.scripts.hermit = True
    w.hermit = True
    w.events[1] = lua.table_from({"type": 2})
    r = env.report()
    assert r.hermit_tool is True and r.queued == 1, dict(r)
    w.scripts.force = None
    assert env.report().force is None


@test("lua: call_migrants: a dry run queues nothing; it runs force Migrants once; refused with a wave queued")
def _():
    if LuaRuntime is None:
        return
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-recovery.lua"))
    r = env.call_migrants(True)
    assert r.ok is True and r.dry_run is True and len(w.ran) == 0, dict(r)
    r = env.call_migrants(False)
    assert r.ok is True and r.queued == 1 and w.ran[1] == "force Migrants", dict(r)
    r = env.call_migrants(False)
    assert r.ok is False and r.rejected is True and len(w.ran) == 1, dict(r)
    lua2 = LuaRuntime(unpack_returned_tuples=True)
    env2, w2 = lua2.execute(FAKE, module_src("ai-recovery.lua"))
    w2.adds = 0
    r = env2.call_migrants(False)
    assert r.ok is False and "queued no wave" in r.error, dict(r)
    w2.scripts.force = None
    assert env2.call_migrants(False).ok is False


if __name__ == "__main__":
    finish()
