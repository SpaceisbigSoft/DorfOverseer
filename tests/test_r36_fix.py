"""(0.105.36 fix) The v36 verifier's findings (review/v36.md):

- [bug] a gate the player already shut is never booked as the AI's: neither
  close_threatened_gates nor the watcher's own look books it (only a piece
  the AI found open and shut is the AI's), so open_entrance, the reopen and
  open_all never open it; an entrance with one piece of each opens only the
  AI's, and saves only the AI's;
- [risk] a refused cistern_shut backs off like any refusal (not every cycle);
- [risk] an entrance still being opened shut again: the PullLever job queued
  on its raised bridge's lever is taken away (it would lower the bridge);
- [risk] free_gate_jobs with ai_plan resumes an unrecorded piece only when it
  is older than the AI's records (gate_planned_since), never a later one the
  player planned;
- [nit] shelter_supply forgotten when the alarm's burrow is the player's (the
  report's civ_alert_shelter, or refresh_shelter's "not the AI shelter").

    python tests/test_r36_fix.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

_src = (ROOT / "tests" / "test_r32_gatesplit.py").read_text(encoding="utf-8")
_ns: dict = {"module_src": module_src, "sys": sys}
exec(compile(_src[_src.index("try:\n    from lupa"):_src.index("\ndef lst")], "r32rig", "exec"), _ns)

import planner_core  # noqa: E402
import planner_society  # noqa: E402
import planner_wells as pw  # noqa: E402
from planner import Memory, plan, select, record  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick, _record_any_outcome  # noqa: E402
import test_r36_builder as TB  # noqa: E402

LUA = _ns["LUA"]
t = LUA.table_from


def lst(x):
    return [x[i] for i in range(1, len(x) + 1)] if x is not None else []


def enemy(G, x=112, y=149, z=171):
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                    "pos": t({"x": x, "y": y, "z": z})})


def with_door(E, G, forbidden=False):
    """Entrance 1 gets a second piece: a plain door 8 (no lever), the AI locks it."""
    G.blds[8] = t({"id": 8, "x1": 109, "y1": 149, "x2": 109, "y2": 149, "z": 171, "jobs": t({}),
                   "door_flags": t({"closed": False, "forbidden": forbidden})})
    eq = E.GATES.entrances[1].equipment
    eq[len(eq) + 1] = t({"id": 8, "kind": "door", "x1": 109, "y1": 149, "x2": 109, "y2": 149, "z": 171})


# --- the bug: the player's shut gate ---------------------------------------------------

@test("bug: close_threatened_gates leaves a gate the player shut theirs (unbooked); open_entrance refuses it")
def _():
    E, G = _ns["rig"](player=True, closed=True)          # the player's lever, their hatch shut
    enemy(G)
    r = E.close_threatened_gates(False)
    assert not r.ok and r.waiting and not G.pulled[1], dict(r)
    assert not E.GATES.closed[1], "booked as the AI's"
    G.units[1] = None
    r = E.open_entrance(1, False)
    assert not r.ok and r.not_ai and not lst(G.pulled) and G.blds[7].door_flags.closed, dict(r)
    # the same entrance with its hatch open: shut by the AI and booked
    E, G = _ns["rig"](player=True, closed=False)
    enemy(G)
    r = E.close_threatened_gates(False)
    assert r.ok and r.closed == 1 and E.GATES.closed[1] and G.blds[7].door_flags.closed, dict(r)
    G.units[1] = None
    r = E.open_entrance(1, False)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)


@test("bug: the watcher's own look doesn't book the player's shut gate (nor pull, nor say 'closed')")
def _():
    E, G = _ns["rig"](player=True, closed=True)
    said = []
    E.dfhack.gui.showAnnouncement = LUA.eval("function(said) return function(m) table.insert(said, m) end end")(
        LUA.table_from([]))
    E.GATES.armed = True
    E.visible_dangers = LUA.eval("function() return {{pos = {x = 112, y = 149, z = 171}}} end")
    E.citizens_outside = LUA.eval("function() return 0 end")
    for _ in range(3):
        E.GATES_ORIG.check()
    assert not E.GATES.closed[1] and not lst(G.pulled) and G.blds[7].door_flags.closed
    # the danger gone: nothing of the player's is opened (open_all, the reopen)
    E.visible_dangers = LUA.eval("function() return {} end")
    E.GATES_ORIG.open_all()
    assert not lst(G.pulled) and G.blds[7].door_flags.closed


@test("bug: one piece of each: only the AI's is booked, saved, and opened; the player's hatch stays shut")
def _():
    E, G = _ns["rig"](player=True, closed=True)
    with_door(E, G)
    enemy(G)
    r = E.close_threatened_gates(False)
    assert r.ok and r.closed == 1 and E.GATES.closed[1], dict(r)
    assert G.blds[8].door_flags.forbidden and E.GATES.mine[8] and not E.GATES.mine[7]
    snap = E.gates_snapshot()
    assert [g.id for g in snap.gates.values()] == [8], list(snap.gates.values())
    G.units[1] = None
    r = E.open_entrance(1, False)
    assert r.ok and not r.still_shut and not E.GATES.closed[1], dict(r)
    assert not G.blds[8].door_flags.forbidden and G.blds[7].door_flags.closed and not lst(G.pulled)
    assert not E.GATES.mine[8]                                   # open again: no longer the AI's shut one
    # an entrance booked before (no piece record: an old save) still opens all, as then
    E, G = _ns["rig"](player=False, closed=True)
    E.GATES.closed[1] = True
    r = E.open_entrance(1, False)
    assert r.ok and not G.blds[7].door_flags.closed, dict(r)


@test("bug: re-closing an entrance the AI was opening keeps its own (still shut) pieces the AI's")
def _():
    E, G = _ns["rig"](player=False, closed=False)
    enemy(G)
    E.close_threatened_gates(False)
    assert E.GATES.closed[1] and E.GATES.mine[7] and G.blds[7].door_flags.closed
    E.GATES.opening = t({1: True})                     # being opened, still shut
    r = E.close_threatened_gates(False)
    assert r.ok and E.GATES.closed[1] and E.GATES.mine[7], dict(r)
    G.units[1] = None
    assert E.open_entrance(1, False).ok and not G.blds[7].door_flags.closed


# --- risk: closing while opening cancels the queued pull -------------------------------

def _opening_bridge():
    E, G = _ns["rig"]()
    G.blds[9] = t({"id": 9, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171, "jobs": t({}),
                   "gate_flags": t({"raised": True, "raising": False, "lowering": False})})
    E.GATES.entrances[1].equipment = t([t({"id": 9, "kind": "bridge", "lever_id": 137,
                                           "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171})])
    G.blds[137].jobs = t([t({"job_type": "PullLever"}), t({"job_type": "Link"})])
    E.dfhack.job = LUA.eval("""function(G) return {removeJob = function(j)
        local l = G.blds[137].jobs
        for i = #l, 1, -1 do if l[i] == j then table.remove(l, i) end end
        return true end} end""")(G)
    E.GATES.closed, E.GATES.opening = t({1: True}), t({1: True})
    return E, G


@test("risk: an entrance being opened shut again: the lever's queued pull is taken away (close_threatened_gates, the watcher)")
def _():
    E, G = _opening_bridge()
    enemy(G)
    r = E.close_threatened_gates(False)
    assert r.ok and E.GATES.closed[1] and not E.GATES.opening[1], dict(r)
    jobs = [j.job_type for j in lst(G.blds[137].jobs)]
    assert jobs == ["Link"], jobs
    assert G.blds[9].gate_flags.raised and E.GATES.pulls_cancelled == 1
    # the watcher's "closed again while opening" does the same
    E, G = _opening_bridge()
    E.GATES.armed = True
    E.visible_dangers = LUA.eval("function() return {{pos = {x = 112, y = 149, z = 171}}} end")
    E.citizens_outside = LUA.eval("function() return 0 end")
    E.GATES_ORIG.check()
    assert [j.job_type for j in lst(G.blds[137].jobs)] == ["Link"] and E.GATES.closed[1]
    # a plain close (not being opened) leaves the lever's jobs alone
    E, G = _opening_bridge()
    E.GATES.opening = t({})
    E.close_threatened_gates(False)
    assert [j.job_type for j in lst(G.blds[137].jobs)] == ["PullLever", "Link"]


# --- risk: free_gate_jobs ai_plan -------------------------------------------------------

def _pending(E, G, bid):
    job = t({"flags": t({"suspend": True})})
    G.blds[bid] = t({"id": bid, "x1": 30, "y1": 31, "x2": 30, "y2": 31, "z": 170, "jobs": t([job]),
                     "getBuildStage": LUA.eval("function() return 0 end"),
                     "getMaxBuildStage": LUA.eval("function() return 1 end")})
    E.GATES.entrances[1].pending_ids = t([bid])
    return job


@test("risk: free_gate_jobs ai_plan: an unrecorded piece planned after the records began is the player's")
def _():
    E, G = _ns["rig"]()
    E.df["global"].building_next_id = 100
    assert E.gate_planned_since(True) == 100 and G.saved[E.GATE_PLANNED_SINCE_KEY].id == 100
    E.df["global"].building_next_id = 200                 # later: the kept start stays
    job = _pending(E, G, 150)                               # the player's, planned since
    r = E.free_gate_jobs(1, False, True)
    assert not r.ok and r.players and job.flags.suspend, dict(r)
    job = _pending(E, G, 40)                                # older than the records: the AI's (pre-v35)
    r = E.free_gate_jobs(1, False, True)
    assert r.ok and not job.flags.suspend, dict(r)
    # without ai_plan, the older one isn't resumed either
    job = _pending(E, G, 40)
    assert not E.free_gate_jobs(1, False).ok and job.flags.suspend
    # the start can't be read: no unrecorded piece is the AI's
    E, G = _ns["rig"]()
    job = _pending(E, G, 40)
    assert not E.free_gate_jobs(1, False, True).ok and job.flags.suspend
    # a record's building older than the next id: the start is the lowest
    E, G = _ns["rig"]()
    E.df["global"].building_next_id = 100
    G.saved[E.GATE_PLANNED_KEY] = t({"tiles": t(["1,2,3@70"])})
    assert E.gate_planned_since(False) == 70


# --- risk: the refused cistern shut ------------------------------------------------------

@test("risk: a refused cistern_shut backs off (a few tries in 10 days, not every cycle); first try outside the cooldown")
def _():
    s = TB._cistern_state(stage="done", gate="open", depth=3, sealed_now=False, unsealed="x10 y10 z100")
    m = Memory()
    m.last_fired["cistern"] = abs_tick(s) - 300
    n = 0
    for c in range(40):
        s["date"]["tick"] += 300
        props, _ = plan(copy.deepcopy(s), m)
        allowed, _ = select(props, s, m)
        sh = [p for p in allowed if p.rule == pw.CISTERN_SHUT_RULE]
        if c == 0:
            assert sh, "first try waited"
        n += len(sh)
        record([(p, {"ok": False, "rejected": True, "error": "no cistern lever linked yet"}
                 if p.rule == pw.CISTERN_SHUT_RULE else {"ok": True}) for p in allowed], s, m)
    assert 1 <= n <= 6, n


# --- nit: shelter_supply ----------------------------------------------------------------

def _sup_memory(s):
    m = Memory()
    _record_any_outcome({"type": "civ_alert", "on": True},
                        {"ok": True, "on": True, "shelter": {"refreshed": True, "tiles": 400,
                                                             "no_food": "the shelter holds no food"}},
                        s, m, abs_tick(s) - 2 * TICKS_PER_DAY)
    assert m.shelter_supply.get("no_food")
    return m


@test("nit: shelter_supply forgotten when the alarm's burrow is the player's (on or off), or refresh_shelter says so")
def _():
    s = TB._cistern_state(stage="done")
    for on in (True, False):
        s["civ_alert"] = on
        s["civ_alert_shelter"] = "player"
        m = _sup_memory(s)
        props, notes = [], []
        planner_society._shelter_supply_rule(s, m, props, notes)
        assert not props and not notes and not m.shelter_supply, (on, notes)
    # the AI's shelter: kept and said
    s["civ_alert"], s["civ_alert_shelter"] = False, "ai"
    m = _sup_memory(s)
    props, notes = [], []
    planner_society._shelter_supply_rule(s, m, props, notes)
    assert any("next sounds the alarm" in x for x in notes) and m.shelter_supply
    # unread (an older bridge): kept
    s.pop("civ_alert_shelter")
    planner_society._shelter_supply_rule(s, m, [], [])
    assert m.shelter_supply
    _record_any_outcome({"type": "refresh_shelter"},
                        {"ok": False, "rejected": True, "error": "the civilian alert's burrow is not the AI shelter"},
                        s, m, abs_tick(s))
    assert not m.shelter_supply
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "civ_alert_shelter = function()" in src and "'civ_alert_shelter'," in src


@test("nit: the bridge's civ_alert_shelter reads 'ai', 'player', 'none'")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    i = src.index("civ_alert_shelter = function()")
    body = src[i + len("civ_alert_shelter = "):src.index("\n    end,", i) + len("\n    end")]
    fn = LUA.eval("""function(body)
        local env = {safe = function(f) return f() end, ipairs = ipairs, tostring = tostring, df = {global = {plotinfo = {}}}}
        return env, assert(load('return ' .. body, 'cas', 't', env))()
    end""")
    env, f = fn(body)
    pi = env.df["global"].plotinfo
    pi.burrows = t({"list": t([t({"id": 3, "name": "AI shelter"}), t({"id": 4, "name": "Hall"})])})
    # DF's alert list is 0-based (entry 1 is the civilian alert's, as civ_alert_ready reads it)
    vec = LUA.eval("function(a, b) return setmetatable({[0] = a, [1] = b}, {__len = function() return 2 end}) end")
    pi.alerts = t({"list": vec(t({"burrows": t([])}), t({"burrows": t([3])}))})
    assert f() == "ai"
    pi.alerts.list[1].burrows = t([3, 4])
    assert f() == "player"
    pi.alerts.list[1].burrows = t([])
    assert f() == "none"


if __name__ == "__main__":
    finish()
