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
    assert pulls(G) == [] and E.GATES.bridge_near_holds == 1
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
    assert not E.GATES.bridge_near_holds
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


@test("item2: can't tell (a unit unreadable): not held, a siege gate still closes")
def _():
    E, G = bridge_rig()
    unit(G, 107, 149, 171)
    E.dfhack.units.isDead = LUA.eval("function(u) error('gone') end")
    close(E)
    assert pulls(G) == [137]
    near, enemy = E.own_near_bridge(G.blds[9])
    assert near is False and enemy is False


finish()
