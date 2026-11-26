"""(item2) The gate drawbridge's guard (lua/ai-gates-watch.lua own_near_bridge,
set_bridge): E (26 Nov) lost 3 passers-by to a drawbridge despite an exact-tile
check (u.pos changes only on arrival). A gate bridge now also waits while one
of the fort's own is beside its footprint (its z, or beside it on the ramp
levels), or whose path's next steps or destination are on it; a close with an
enemy within IMMINENT of the bridge is decided by the old rules (only one of
the fort's own on the bridge's tiles holds it); can't tell: not held.

    python tests/test_item2_gate_near_bridge.py
"""

from __future__ import annotations

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

LUA = _ns["LUA"]
t = LUA.table_from
VEC = LUA.eval("""function(...)
    local n = select('#', ...)
    local v = setmetatable({}, {__len = function() return n end})
    for i = 1, n do v[i - 1] = select(i, ...) end
    return v end""")
CIV = 1


def bridge_rig(raised=False):
    """Entrance 1's gate: the AI's drawbridge 9 (x108 y149 z171) on lever 137; a pull flips it at once."""
    E, G = _ns["rig"]()
    G.blds[9] = t({"id": 9, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171, "jobs": t({}),
                   "gate_flags": t({"raised": raised, "raising": False, "lowering": False})})
    br = t({"id": 9, "kind": "bridge", "lever_id": 137, "x1": 108, "y1": 149, "x2": 108, "y2": 149, "z": 171})
    E.GATES.entrances[1].equipment = t([br])
    E.bridge_occupied = LUA.eval("function() return false end")
    E.df["global"].plotinfo = t({"civ_id": CIV})
    E.dfhack.units.isDead = LUA.eval("function(u) return u.dead == true end")
    E.dfhack.units.isCitizen = LUA.eval("function(u) return u.citizen == true end")
    LUA.execute("CR_OK = CR_OK or 0")
    E.dfhack.run_command_silent = LUA.eval("""function(G) return function(_, _, _, id)
        table.insert(G.pulled, tonumber(id))
        local f = G.blds[9].gate_flags; f.raised = not f.raised
        return '', CR_OK end end""")(G)
    return E, G


def unit(G, x, y, z, *, own=True, danger=False, path=(), dest=None):
    steps = list(path)
    u = t({"id": 500 + len(G.units), "citizen": own, "civ_id": CIV if own else 99, "danger": danger,
           "flags1": t({"caged": False, "chained": False}), "pos": t({"x": x, "y": y, "z": z}),
           "path": t({"dest": t({"x": dest[0], "y": dest[1], "z": dest[2]}) if dest
                              else t({"x": -30000, "y": -30000, "z": -30000}),
                      "path": t({"x": VEC(*[s[0] for s in steps]), "y": VEC(*[s[1] for s in steps]),
                                 "z": VEC(*[s[2] for s in steps])})})})
    G.units[len(G.units) + 1] = u
    return u


def close(E):
    E.set_entrance(E.GATES.entrances[1], True)


def lowered(E):
    E.set_entrance(E.GATES.entrances[1], False)


def pulls(G):
    return list(G.pulled.values())


@test("item2: a citizen beside the bridge holds its raise; once it walks off, the bridge is raised")
def _():
    E, G = bridge_rig()
    u = unit(G, 107, 149, 171)
    close(E)
    assert pulls(G) == [] and E.GATES.bridge_holds == 1
    assert not G.blds[9].gate_flags.raised
    u.pos.x = 100
    close(E)
    assert pulls(G) == [137] and G.blds[9].gate_flags.raised


@test("item2: a tame animal (the fort's civ) diagonal to the bridge holds it too; a stranger beside it doesn't")
def _():
    E, G = bridge_rig()
    pet = unit(G, 109, 150, 171)
    pet.citizen = False                    # civ_id stays the fort's
    close(E)
    assert pulls(G) == []
    E, G = bridge_rig()
    unit(G, 107, 149, 171, own=False)
    close(E)
    assert pulls(G) == [137]


@test("item2: beside it on the ramp level below holds it; right under it (a tunnel) doesn't")
def _():
    E, G = bridge_rig()
    unit(G, 107, 149, 170)
    close(E)
    assert pulls(G) == []
    E, G = bridge_rig()
    unit(G, 108, 149, 170)
    close(E)
    assert pulls(G) == [137]


@test("item2: a citizen whose next steps cross the bridge holds it; one whose path is elsewhere doesn't")
def _():
    E, G = bridge_rig()
    unit(G, 105, 149, 171, path=[(106, 149, 171), (107, 149, 171), (108, 149, 171), (109, 149, 171)])
    close(E)
    assert pulls(G) == [], pulls(G)
    # the crossing past the next BRIDGE_PATH_STEPS steps: not yet
    E, G = bridge_rig()
    unit(G, 104, 149, 171, path=[(105, 150, 171), (106, 150, 171), (107, 150, 171), (108, 149, 171)])
    close(E)
    assert pulls(G) == [137]
    E, G = bridge_rig()
    unit(G, 105, 149, 171, path=[(105, 150, 171), (105, 151, 171)])
    close(E)
    assert pulls(G) == [137]


@test("item2: a citizen a few tiles off whose destination is the bridge holds it")
def _():
    E, G = bridge_rig()
    unit(G, 105, 152, 171, dest=(108, 149, 171))
    close(E)
    assert pulls(G) == []


@test("item2: an enemy within IMMINENT: a citizen beside the bridge doesn't hold the close "
      "(the existing rules decide: one on the bridge's tiles still does)")
def _():
    E, G = bridge_rig()
    unit(G, 107, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)
    close(E)
    assert pulls(G) == [137] and G.blds[9].gate_flags.raised
    assert not E.GATES.bridge_holds
    # a path through the bridge is no hold then either
    E, G = bridge_rig()
    unit(G, 105, 149, 171, path=[(106, 149, 171), (107, 149, 171), (108, 149, 171)])
    unit(G, 115, 149, 171, own=False, danger=True)
    close(E)
    assert pulls(G) == [137]
    # on the bridge's tile: own_on_bridge holds, as before 0.105.120's rule
    E, G = bridge_rig()
    unit(G, 108, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)
    close(E)
    assert pulls(G) == []
    # a caged enemy, or one far (past IMMINENT): the citizen beside it holds again
    E, G = bridge_rig()
    unit(G, 107, 149, 171)
    unit(G, 108 + E.IMMINENT + 5, 149, 171, own=False, danger=True)
    caged = unit(G, 112, 149, 171, own=False, danger=True)
    caged.flags1.caged = True
    close(E)
    assert pulls(G) == []


@test("item2: lowering waits for a citizen beside the bridge even with an enemy near (it crushes what it lands on)")
def _():
    E, G = bridge_rig(raised=True)
    unit(G, 107, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)
    lowered(E)
    assert pulls(G) == [] and G.blds[9].gate_flags.raised
    G.units[1].pos.x = 100
    lowered(E)
    assert pulls(G) == [137] and not G.blds[9].gate_flags.raised


@test("item2 (2): a unit by the bridge that can't be read: a raise and a lowering with no enemy near wait")
def _():
    E, G = bridge_rig()
    u = unit(G, 107, 149, 171)
    u.pos = None                           # unreadable: where it is can't be told
    close(E)
    assert pulls(G) == [] and E.GATES.bridge_holds == 1
    E, G = bridge_rig(raised=True)
    unit(G, 107, 149, 171)
    E.dfhack.units.isDead = LUA.eval("function(u) error('gone') end")
    lowered(E)
    assert pulls(G) == []
    w = E.bridge_watch(G.blds[9])
    assert w.unknown is True and w.near is False and w.enemy is False
    assert E.own_on_bridge(G.blds[9]) is None
    # an unreadable unit far off (where it is still read): not a hold
    E, G = bridge_rig()
    E.dfhack.units.isDead = LUA.eval("function(u) if u.pos.x < 105 then error('gone') end return false end")
    unit(G, 103, 149, 171)                 # 5 tiles off: past NEAR_BOX
    close(E)
    assert pulls(G) == [137]


@test("item2 (2): can't tell, but a siege close: an enemy within IMMINENT read, or the units list "
      "unreadable: the gate still closes; a lowering waits")
def _():
    E, G = bridge_rig()
    u = unit(G, 107, 149, 171)
    u.pos = None
    unit(G, 115, 149, 171, own=False, danger=True)
    close(E)
    assert pulls(G) == [137]
    E, G = bridge_rig()
    E.df["global"].plotinfo = None         # nothing can be read
    close(E)
    assert pulls(G) == [137]
    w = E.bridge_watch(G.blds[9])
    assert w.enemy is None and w.unknown is True
    E, G = bridge_rig(raised=True)
    E.df["global"].plotinfo = None
    lowered(E)
    assert pulls(G) == []


def two_bridges(E, G):
    """A second bridge 10 (x108 y151) of entrance 1 on the same lever 137."""
    G.blds[10] = t({"id": 10, "x1": 108, "y1": 151, "x2": 108, "y2": 151, "z": 171, "jobs": t({}),
                    "gate_flags": t({"raised": False, "raising": False, "lowering": False})})
    br2 = t({"id": 10, "kind": "bridge", "lever_id": 137, "x1": 108, "y1": 151, "x2": 108, "y2": 151, "z": 171})
    E.GATES.entrances[1].equipment[2] = br2


@test("item2 (3): two of an entrance's bridges on one lever: pulled once per call (a second undoes the first)")
def _():
    E, G = bridge_rig()
    two_bridges(E, G)
    # the pull taken but nothing moved yet (and no job to see at the lever): both still read down
    E.dfhack.run_command_silent = LUA.eval("""function(G) return function(_, _, _, id)
        table.insert(G.pulled, tonumber(id)); return '', CR_OK end end""")(G)
    close(E)
    assert pulls(G) == [137], pulls(G)


def queue_pull(E, G):
    """A PullLever job queued at lever 137 (a dwarf on the way); removeJob takes it off the lever."""
    job = t({"job_type": "PullLever"})
    jobs = G.blds[137].jobs
    jobs[len(jobs) + 1] = job
    E.dfhack.job = t({"removeJob": LUA.eval("""function(lv) return function(j)
        for i = #lv.jobs, 1, -1 do if lv.jobs[i] == j then table.remove(lv.jobs, i) end end
        return true end end""")(G.blds[137])})
    return job


def pull_jobs(G):
    return [j for j in G.blds[137].jobs.values() if j.job_type == "PullLever"]


@test("item2 (1): a queued raise pull is taken away while a citizen is beside the bridge (its K2 mark dropped); "
      "kept with the bridge clear, and kept with an enemy within IMMINENT")
def _():
    E, G = bridge_rig()
    queue_pull(E, G)
    E.GATES.close_pulled = t({9: 1000})
    E.GATES.repulled = t({9: 900})
    unit(G, 107, 149, 171)
    assert E.hold_queued_bridge_pulls() == 1
    assert pull_jobs(G) == [] and E.GATES.close_pulled[9] is None and E.GATES.repulled[9] is None
    assert E.GATES.bridge_pulls_held == 1
    # clear: kept
    E, G = bridge_rig()
    queue_pull(E, G)
    unit(G, 100, 149, 171)
    assert E.hold_queued_bridge_pulls() == 0 and len(pull_jobs(G)) == 1
    # siege: a citizen beside it doesn't stop the raise
    E, G = bridge_rig()
    queue_pull(E, G)
    unit(G, 107, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)
    assert E.hold_queued_bridge_pulls() == 0 and len(pull_jobs(G)) == 1
    # ... one on its tile still does
    E, G = bridge_rig()
    queue_pull(E, G)
    unit(G, 108, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)
    assert E.hold_queued_bridge_pulls() == 1 and pull_jobs(G) == []


@test("item2 (1): a queued lowering pull is taken away while a citizen paths onto the bridge, even in a siege; "
      "the lure's bridges and a moving bridge are left alone")
def _():
    E, G = bridge_rig(raised=True)
    queue_pull(E, G)
    unit(G, 105, 149, 171, path=[(106, 149, 171), (107, 149, 171), (108, 149, 171)])
    unit(G, 115, 149, 171, own=False, danger=True)
    assert E.hold_queued_bridge_pulls() == 1 and pull_jobs(G) == []
    E, G = bridge_rig(raised=True)
    queue_pull(E, G)
    unit(G, 107, 149, 171)
    assert E.hold_queued_bridge_pulls(t({9: True})) == 0 and len(pull_jobs(G)) == 1
    G.blds[9].gate_flags.lowering = True
    assert E.hold_queued_bridge_pulls() == 0 and len(pull_jobs(G)) == 1


@test("item2 (1): the watcher's look takes the queued pulls to bridge_hold (with the lure's pieces)")
def _():
    E, G = bridge_rig()
    E.GATES_ORIG.arm()
    seen = LUA.eval("{}")
    E.hold_queued_bridge_pulls = LUA.eval("function(seen) return function(skip) seen.n = (seen.n or 0) + 1; "
                                          "seen.skip = skip; return 0 end end")(seen)
    E.GATES_ORIG.check()
    assert seen.n == 1 and seen.skip is not None


@test("item2 (1): the look's repull of a closed entrance's bridge found down waits for a citizen beside it")
def _():
    E, G = bridge_rig()
    E.GATES_ORIG.arm()
    E.GATES.closed = t({1: True})
    E.GATES.mine = t({9: True})
    unit(G, 107, 149, 171)
    unit(G, 115, 149, 171, own=False, danger=True)    # a danger near: no "found open, let go"
    E.bridge_hold = LUA.eval("function() return true, 'own near' end")
    E.GATES_ORIG.check()
    assert pulls(G) == [], pulls(G)


finish()
