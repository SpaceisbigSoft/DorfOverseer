"""(0.105.97) A caravan stuck "Leaving": the AI clears it itself.

B, 23 Nov: a caravan stuck "Leaving" 118 days with 2 merchants on the map
(DF bug 12624); the AI told them to walk off twice, they stayed, and the AI
only wrote a Needs you while no caravan and few migrants came. Now, each step
h9_caravan_step_days after the one before:
  1. walk off (r2 h9's free_caravan);
  2. taken to the edge (step "edge": teleported to a map-edge tile of their
     own walk group, then told to leave);
  3. once none of its merchants is on the map and DF still holds it
     Leaving: DFHack's fix/stuck-merchants (only with no merchant of any
     caravan on the map) and `caravan leave <id>` (step "dismiss");
  4. only then the Needs you, saying what was tried and what DFHack said.

    python tests/test_r97_stuck_caravan.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src, module_src  # noqa: E402

from planner import PLANNER_CONFIG, Memory, NEEDS_YOU, Proposal  # noqa: E402
import planner_outside as O  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 403200
STEP = CFG["h9_caravan_step_days"]


def b_fort(tick: int, caravans=None, pop: int = 57) -> dict:
    """B on 23 Nov: 57 citizens, the cap open, a caravan stuck leaving."""
    s = {"settings": {"traits": {"piety": 150}, "set_pop_cap": True, "fort_goal": "expand"},
         "society": {"pop_cap": 200, "strict_pop_cap": 220},
         "dwarves": {"total": pop}, "stocks": {"drink": 20 * pop, "prepared_meals": 20 * pop},
         "migration": {"civ": True, "force": "force", "hermit_tool": False, "queued": 0},
         "others_on_map": {}, "date": {"year": 251 + tick // YEAR, "tick": tick % YEAR}}
    if caravans is not None:
        s["migration"]["caravans"] = caravans
    return s


def car(merchants=2, can_leave=2, entity=308, state="Leaving", leaving=True):
    c = {"entity": entity, "own": True, "state": state, "days_left": 0, "merchants": merchants}
    if leaving:
        c["leaving"] = True
    if merchants and leaving:
        c["can_leave"] = can_leave
    return c


def cycle(m, t, caravans, answer=None):
    """One cycle: note_cycle's book, the rule, and each proposal done with the
    bridge's answer (record()'s hook and cooldown)."""
    s = b_fort(t, caravans)
    props, notes = [], []
    O.note_outside(s, m, CFG)
    O._drought_rule(s, m, CFG, props, notes)
    now = 251 * YEAR + t
    for p in props:
        r = answer(p) if answer else {"ok": True, "told": 2}
        O.note_caravan_try(p, r, m, now)
        m.last_fired["stuck_caravan"] = now
    return props, notes


def run(m, days, caravans_at, answer=None, every=1):
    out = []
    for d in range(0, days, every):
        cs = caravans_at(d) if callable(caravans_at) else caravans_at
        out.append((d,) + cycle(m, d * DAY, cs, answer))
    return out


def steps(log):
    return [(d, p.action.get("step", "walk")) for d, ps, _ in log for p in ps]


@test("B's caravan: walk off twice, then taken to the edge, then (still there) a Needs you saying what was tried")
def _():
    m = Memory()
    def ans(p):
        if p.action.get("step") == "edge":
            return {"ok": True, "step": "edge", "moved": 2, "told": 2}
        return {"ok": True, "told": 2, "step": "walk"}
    log = run(m, 200, [car()], ans)
    st = steps(log)
    assert [s for _, s in st] == ["walk", "walk", "edge"], st
    assert st[0][0] >= CFG["h9_caravan_stuck_days"], st
    assert all(b - a >= STEP for (a, _), (b, _) in zip(st, st[1:])), st
    edge = next(p for _, ps, _ in log for p in ps if p.action.get("step") == "edge")
    assert edge.action == {"type": "free_caravan", "entity": 308, "step": "edge"} and edge.rule == "stuck_caravan"
    last = log[-1][2]
    ny = [n for n in last if n.startswith(NEEDS_YOU)]
    assert ny and "walk off 2 time(s)" in ny[0] and "map's edge 1 time(s)" in ny[0] and "2 taken to the edge" in ny[0] \
        and "12624" in ny[0], ny
    book = m.outside["stuck"]["308"]
    assert [t[1] for t in book["tries"]] == ["walk", "walk", "edge"], book


@test("taken to the edge, the merchants gone, DF still holding it Leaving: fix/stuck-merchants + caravan leave "
      "after a wait, then a Needs you with DFHack's answers")
def _():
    m = Memory()
    moved = {}
    cur = [0]

    def ans(p):
        st = p.action.get("step")
        if st == "edge":
            moved["day"] = cur[0]                    # gone from the map from the next cycle on
            return {"ok": True, "step": "edge", "moved": 2}
        if st == "dismiss":
            return {"ok": True, "step": "dismiss", "still": True,
                    "ran": [{"cmd": "fix/stuck-merchants", "ok": True, "out": "Removing 2 merchants"},
                            {"cmd": "caravan leave 0", "ok": True, "out": ""}]}
        return {"ok": True, "told": 2}

    log = []
    for d in range(0, 260):
        cur[0] = d
        cs = [car(merchants=0)] if "day" in moved else [car()]
        log.append((d,) + cycle(m, d * DAY, cs, ans))
    st = steps(log)
    assert [s for _, s in st] == ["walk", "walk", "edge", "dismiss"], st
    gone_day = moved["day"] + 1
    dis = st[-1][0]
    assert dis - gone_day >= STEP and dis - st[-2][0] >= STEP, (st, gone_day)
    p = next(p for _, ps, _ in log for p in ps if p.action.get("step") == "dismiss")
    assert p.action == {"type": "free_caravan", "entity": 308, "step": "dismiss"}, p.action
    ny = [n for n in log[-1][2] if n.startswith(NEEDS_YOU)]
    assert ny and "fix/stuck-merchants" in ny[0] and "Removing 2 merchants" in ny[0] and "caravan leave 0" in ny[0] \
        and "still holds" in ny[0], ny
    # the cause the drought says: the gone caravan
    assert O.drought_cause(b_fort(259 * DAY, [car(merchants=0)]), m, CFG)[0] == "caravan"


@test("dismiss waits while any merchant of another caravan is on the map (DFHack's docs), then runs")
def _():
    m = Memory()
    m.outside = {"first": 251 * YEAR, "leaving": {}, "stuck": {"308": {"since": 251 * YEAR, "gone": 251 * YEAR,
                 "tries": [[251 * YEAR, "walk", ""], [251 * YEAR + DAY, "walk", ""], [251 * YEAR + 2 * DAY, "edge", "2"]]}}}
    trader = car(merchants=3, entity=400, state="AtDepot", leaving=False)
    props, notes = cycle(m, 30 * DAY, [car(merchants=0), trader])
    assert not props and any("waits until no merchant of any caravan" in n for n in notes), notes
    props, notes = cycle(m, 31 * DAY, [car(merchants=0)])
    assert props and props[0].action.get("step") == "dismiss", (props, notes)


@test("the caravan gone home: its book dropped, nothing more done; a trading or plainly leaving one never booked")
def _():
    m = Memory()
    run(m, 60, [car()])
    assert "308" in m.outside["stuck"]
    props, notes = cycle(m, 61 * DAY, [])
    assert not props and m.outside["stuck"] == {}, m.outside
    # a caravan leaving with no merchant on the map that was never seen stuck: DF's own business
    m2 = Memory()
    log = run(m2, 80, [car(merchants=0)])
    assert not steps(log) and m2.outside.get("stuck") == {}, m2.outside
    # a caravan at the depot (not leaving): never booked, never moved
    m3 = Memory()
    log = run(m3, 80, [car(merchants=3, state="AtDepot", leaving=False)])
    assert not steps(log) and m3.outside.get("stuck") == {}


@test("no merchant with a way to the edge: the Needs you to open it, never a teleport")
def _():
    m = Memory()
    log = run(m, 120, [car(can_leave=0)])
    assert not steps(log) and any("way to the map's edge" in n for n in log[-1][2]), log[-1]


@test("0.105.96's memory (two walk-offs in `frees`): carried over, the next step is the edge")
def _():
    m = Memory()
    t0 = 251 * YEAR
    m.outside = {"first": t0, "leaving": {"308": t0}, "frees": [t0 + 30 * DAY, t0 + 60 * DAY],
                 "free_seen": t0 + 60 * DAY}
    m.last_fired["stuck_caravan"] = t0 + 60 * DAY
    props, notes = cycle(m, 100 * DAY, [car()])
    assert props and props[0].action.get("step") == "edge", (props, notes)
    assert "frees" not in m.outside and [t[1] for t in m.outside["stuck"]["308"]["tries"]][:2] == ["walk", "walk"]


@test("a refused edge step still counts: the Needs you follows, saying DF's refusal")
def _():
    m = Memory()

    def ans(p):
        if p.action.get("step") == "edge":
            return {"ok": False, "rejected": True, "error": "2 merchant(s) on the map, none taken to the edge"}
        return {"ok": True, "told": 2}
    log = run(m, 200, [car()], ans)
    assert [s for _, s in steps(log)] == ["walk", "walk", "edge"]
    ny = [n for n in log[-1][2] if n.startswith(NEEDS_YOU)]
    assert ny and "none taken to the edge" in ny[0], ny


@test("record() books the step through its hook; a dry run books nothing")
def _():
    import planner
    m = Memory()
    s = b_fort(40 * DAY, [car()])
    O.note_outside(s, m, CFG)
    p = Proposal("stuck_caravan", {"type": "free_caravan", "entity": 308, "step": "edge"}, "x", 5)
    planner.record([(p, {"ok": True, "step": "edge", "moved": 2})], s, m)
    tries = m.outside["stuck"]["308"]["tries"]
    assert tries and tries[-1][1] == "edge" and "2 taken to the edge" in tries[-1][2], tries
    n = len(tries)
    pd = Proposal("stuck_caravan", {"type": "free_caravan", "entity": 308, "step": "edge", "dry_run": True}, "x", 5)
    O.note_caravan_try(pd, {"ok": True}, m, 251 * YEAR + 41 * DAY)
    assert len(m.outside["stuck"]["308"]["tries"]) == n


@test("bridge: free_caravan hands its step on; the step checked in ai-recovery; its words; the cfg")
def _():
    b = bridge_hub_src()
    assert re.search(r"free_caravan = function\(a\)[\s\S]{0,300}\.free_caravan\(id, a\.dry_run == true, a\.step\)", b)
    src = module_src("ai-recovery.lua")
    assert "fix/stuck-merchants" in src and "'caravan', 'leave'" in src and "dfhack.units.teleport" in src
    assert "step is walk, edge or dismiss" in src
    assert len((ROOT / "lua" / "ai-recovery.lua").read_bytes()) < 60 * 1024
    import overseer
    w = overseer.SHORT_WORDS["free_caravan"]
    assert "edge" in w and "DFHack" in w
    for k in ("h9_caravan_edge_max", "h9_caravan_dismiss_max", "h9_caravan_step_days"):
        assert isinstance(CFG[k], int), k
    rec = (ROOT / "brain" / "planner_record.py").read_text(encoding="utf-8")
    assert '_hook("note_caravan_try", _caravan_try, p, r, memory, now)' in rec


# ---- Lua: the action's steps -----------------------------------------------------------------

LUA_FAKE = r"""
local src = ...
local W = {teleports = {}, ran = {}, scripts = {force = true, caravan = true, ['fix/stuck-merchants'] = true}}
local env = setmetatable({}, {__index = _G})
env.CR_OK = 0
local function unit(id, civ, x, y, z, grp)
  return {id = id, civ_id = civ, pos = {x = x, y = y, z = z, grp = grp},
          flags1 = {merchant = true, left = false, inactive = false, forest = false, caged = false, chained = false},
          animal = {leave_countdown = 0}, opponent = {unit_id = -1}}
end
-- a 20 x 10 map, levels 0..4; walk group 7 on the west edge of level 2 and the
-- north edge of level 3; group 9 nowhere on the edge
W.groups = {}
for y = 0, 9 do W.groups['0,' .. y .. ',2'] = 7 end
for x = 0, 19 do W.groups[x .. ',0,3'] = 7 end
W.u1 = unit(1, 308, 15, 5, 2, 7)           -- nearest: the west edge (0,5,2)
W.u2 = unit(2, 308, 4, 4, 2, 9)            -- no way out
W.u3 = unit(3, 308, 3, 3, 2, 7); W.u3.opponent.unit_id = 55      -- fighting
W.u4 = unit(4, 308, 2, 2, 2, 7); W.u4.flags1.chained = true      -- a prisoner
W.u5 = unit(5, 400, 8, 8, 3, 7)            -- a trader of another caravan
W.units = {W.u1, W.u2, W.u3, W.u4, W.u5}
env.df = {global = {timed_events = {}, plotinfo = {civ_id = 308,
            caravans = {{entity = 308, trade_state = 3, time_remaining = 0, flags = {tribute = false}},
                        {entity = 400, trade_state = 2, time_remaining = 5000, flags = {tribute = false}}}},
                    world = {units = {active = W.units}, map = {x_count = 20, y_count = 10, z_count = 5}}},
          caravan_state = {T_trade_state = {[1] = 'Approaching', [2] = 'AtDepot', [3] = 'Leaving'}},
          timed_event_type = {Migrants = 2},
          historical_entity = {find = function(id) return {id = id} end}}
env.dfhack = {findScript = function(n) return W.scripts[n] and 'x' or nil end,
              run_command_silent = function(...)
                  local a = {...}
                  table.insert(W.ran, table.concat(a, ' '))
                  return 'ran ' .. a[1], 0
              end,
              units = {isDead = function() return false end, getContainer = function() return nil end,
                       teleport = function(u, p)
                           table.insert(W.teleports, {id = u.id, x = p.x, y = p.y, z = p.z})
                           u.pos = {x = p.x, y = p.y, z = p.z, grp = u.pos.grp}
                           return true
                       end},
              maps = {getWalkableGroup = function(p) return p.grp end}}
env.reqscript = function(name)
    if name == 'ai-way-out' then return {edge_groups = function() return {[7] = true} end, EDGE = {z = {0, 4}}} end
    error('no module ' .. tostring(name))
end
assert(load(src, 'ai-recovery', 't', env))()
env.edge_group_at = function(x, y, z) return W.groups[x .. ',' .. y .. ',' .. z] or 0 end
return env, W
"""


def lua_env():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(LUA_FAKE, module_src("ai-recovery.lua"))
    return env, w, lua                               # one runtime for the tables a test makes


@test("lua: edge_tile_near (pure) picks the nearest edge tile of the unit's own group, its own level first")
def _():
    env, w, rt = lua_env()
    at = env.edge_group_at
    t = env.edge_tile_near(20, 10, 0, 4, at, w.u1.pos, 7)
    assert (t.x, t.y, t.z) == (0, 5, 2), (t.x, t.y, t.z)
    # from level 4 the nearest level with group 7 is 3 (the north edge), nearest x
    pos = rt.eval("{x = 12, y = 6, z = 4}")
    t = env.edge_tile_near(20, 10, 0, 4, at, pos, 7)
    assert (t.x, t.y, t.z) == (12, 0, 3), (t.x, t.y, t.z)
    assert env.edge_tile_near(20, 10, 0, 4, at, pos, 9) is None


@test("lua: step edge teleports only the free merchants that can reach the edge, and tells them to leave")
def _():
    env, w, _rt = lua_env()
    d = env.free_caravan(308, True, "edge")
    assert d.ok and d.dry_run and d.moved == 1 and len(list(w.teleports.values())) == 0, dict(d)
    d = env.free_caravan(308, False, "edge")
    assert d.ok and d.step == "edge" and d.moved == 1 and d.shut == 1 and d.held == 2, dict(d)
    tp = list(w.teleports.values())
    assert len(tp) == 1 and tp[0].id == 1 and (tp[0].x, tp[0].y, tp[0].z) == (0, 5, 2), [dict(x) for x in tp]
    assert w.u1.flags1.forest is True and w.u1.animal.leave_countdown == 2
    assert not w.u3.flags1.forest and not w.u4.flags1.forest and not w.u2.flags1.forest
    # a caravan trading is never moved; a bad step refused
    assert env.free_caravan(400, False, "edge").ok is False and len(list(w.teleports.values())) == 1
    assert env.free_caravan(308, False, "fly").ok is False
    # the walk step as before
    d = env.free_caravan(308, False)
    assert d.ok and d.step == "walk", dict(d)


@test("lua: step dismiss: refused with its merchants on the map; fix/stuck-merchants never with another's merchant "
      "on the map; then both run and their answers kept")
def _():
    env, w, _rt = lua_env()
    d = env.free_caravan(308, False, "dismiss")
    assert d.ok is False and "still on the map" in d.error, dict(d)
    for u in (w.u1, w.u2, w.u3, w.u4):
        u.flags1.left = True                         # gone from the map
    d = env.free_caravan(308, False, "dismiss")
    ran = list(w.ran.values())
    assert d.ok and "fix/stuck-merchants not run" in d.skipped and ran == ["caravan leave 1"], (dict(d), ran)
    w.u5.flags1.left = True
    d = env.free_caravan(308, True, "dismiss")
    assert d.ok and list(w.ran.values())[-1] == "fix/stuck-merchants -n", list(w.ran.values())
    d = env.free_caravan(308, False, "dismiss")
    ran = list(w.ran.values())[-2:]
    assert d.ok and ran == ["fix/stuck-merchants", "caravan leave 1"] and d.still is True, (dict(d), ran)
    cmds = [x.cmd for x in d.ran.values()]
    assert cmds == ["fix/stuck-merchants", "caravan leave 1"], cmds


if __name__ == "__main__":
    finish()
