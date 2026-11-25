"""(0.105.114 item14) E's werepanther outbreak, 25 Nov 06:13-08:00: ~44 dead.

What the journal and read-only probes showed:
  - the curse WAS found from the bite on (Cog and Solon placed in cells at
    06:13:47, a cycle after the werepanther child bit them; the WERECURSE
    syndrome is on every bitten unit), but the were list stopped at 10 rows;
    with 30+ cursed, moon_cell named only those 10 and freed every cell it
    did not name;
  - the release "the full moon is past: let 33 werebeast(s) out" counted the
    cells of dead werebeasts (40 records, the oldest 2600 days): each release
    was refused "every cell is as it should be" (the dead in beast form were
    "kept"), 13-14 times in a row, and the refusal streak held moon_cell
    for ~300 days;
  - a door already locked when the cell was locked was left off the cell's
    record, so the cell read "doors 0", never held, and was relocked every
    cycle (relock wiped the record too).
Now: the list holds 60 and the cell of a living cursed dwarf is kept unless
released; dead werebeasts' cells are freed and never counted; every door
of the cell goes on the record (one locked before is left locked at the
release); the release waits for 2+ phases past the change, no werebeast in
beast form and none fighting; moon_cell is never held by the refusal
streak nor backed off by refusals.

    python tests/test_item14_were_moon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_threats as PT  # noqa: E402
from planner import Memory, plan, PLANNER_CONFIG, Proposal  # noqa: E402
import planner_refusal_streak as RS  # noqa: E402
import planner_core_refusals as CR  # noqa: E402

CH = [{"phase": 27, "tick": 110290156}]


def fort(were):
    from test_threats import fort as tfort
    return tfort({"were": were})


def moon(props):
    return [p for p in props if p.rule == "moon_cell"]


@test("moon_clearly_past: only 4+ phases on from every change phase and before the 8-phase lead; unread: no")
def _():
    got = [ph for ph in range(28) if PT.moon_clearly_past(CH, ph, PLANNER_CONFIG)]
    assert got == list(range(3, 19)), got
    assert not PT.moon_clearly_past(CH, None, PLANNER_CONFIG) and not PT.moon_clearly_past([], 10, PLANNER_CONFIG)
    two = CH + [{"phase": 1, "tick": 110320736}]
    assert not PT.moon_clearly_past(two, 4, PLANNER_CONFIG) and PT.moon_clearly_past(two, 5, PLANNER_CONFIG)


@test("E 07:20: phase 2 after the change at 27 - the cells stay shut (was: let out)")
def _():
    rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": True, "locked": True}]
    s = fort({"list": rows, "changes": CH, "moon_phase": 2, "cells": [{"unit_id": 1, "locked": True}]})
    props, notes = plan(s, Memory())
    assert not [p for p in moon(props) if p.action.get("release")], props
    s = fort({"list": rows, "changes": CH, "moon_phase": 5, "cells": [{"unit_id": 1, "locked": True}]})
    r = [p for p in moon(plan(s, Memory())[0]) if p.action.get("release")]
    assert r and "let 1 werebeast(s) out" in r[0].reason, r


@test("never let out while a werebeast is in beast form or a cursed one is fighting (and it is said why)")
def _():
    cells = [{"unit_id": 1, "locked": True}, {"unit_id": 2, "locked": True}]
    for extra, word in (({"changed": True}, "beast form"), ({"fighting": True}, "in a fight")):
        rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": True, "locked": True},
                dict({"id": 2, "name": "Cerol", "cell": True}, **extra)]
        s = fort({"list": rows, "changes": CH, "moon_phase": 8, "cells": cells})
        props, notes = plan(s, Memory())
        assert not [p for p in moon(props) if p.action.get("release")], props
        assert any(word in n for n in notes), notes


@test("the dead werebeasts' cells are not counted; only they left: one release to drop them")
def _():
    rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": True, "locked": True}]
    s = fort({"list": rows, "changes": CH, "moon_phase": 8, "cells": [{"unit_id": 1, "locked": True},
                                                                      {"unit_id": 99, "locked": True}],
              "dead_cells": 40})
    r = [p for p in moon(plan(s, Memory())[0]) if p.action.get("release")]
    assert r and "let 1 werebeast(s) out" in r[0].reason, r
    s = fort({"list": [], "changes": CH, "moon_phase": 8, "cells": [], "dead_cells": 3})
    r = moon(plan(s, Memory())[0])
    assert r and r[0].action.get("release") and "dead werebeasts" in r[0].reason, r
    s = fort({"list": [], "changes": CH, "moon_phase": 8, "cells": []})
    assert not moon(plan(s, Memory())[0])


@test("thirty cursed at once: every one is named in the moon_cell call")
def _():
    rows = [{"id": i, "name": f"D{i}", "by_syndrome": True} for i in range(1, 31)]
    s = fort({"list": rows, "changes": CH, "moon_phase": 22, "cells": []})
    c = [p for p in moon(plan(s, Memory())[0]) if not p.action.get("release")]
    assert c and sorted(c[0].action["ids"]) == list(range(1, 31)), c


@test("moon_cell: never held by the refusal streak, no refusal back-off either")
def _():
    p = Proposal("moon_cell", {"type": "moon_cell", "ids": [], "release": True}, "x", 3)
    assert RS.critical(p)
    assert "moon_cell" in CR.OWN_PACE
    mem = Memory()
    mem.refusals = {CR.refusal_key(p): {"until": 10 ** 9, "at": 0}}
    assert CR._refused_wait(mem, p, 1000) is None


@test("lua: the list holds 60 and counts all; dead cells counted apart; the release waits for beast form and fights")
def _():
    src = (ROOT / "lua" / "ai-threats.lua").read_text(encoding="utf-8")
    assert "WERE_LIST_MAX = 60" in src and "#out.list < WERE_LIST_MAX" in src
    assert "out.dead_cells" in src and "fighting = in_combat(u)" in src
    try:
        from lupa.lua53 import LuaRuntime  # noqa: F401
    except ImportError:
        return
    import test_threats as TT
    LUA, E = TT.LUA, TT.LUA.execute(TT.GAME, TT.SRC)
    LUA.execute("""local E = ...; local G = E.G
        E.dfhack.units.isDead = function(u) return u.dead == true end
        E.df.syndrome = {find = function(id) if id == 1 then return {syn_class = {'WERECURSE'}} end end}
        local z = {id = 77, x1 = 0, y1 = 0, x2 = 2, y2 = 2, z = 10}
        table.insert(G.buildings, z)
        local pre = {id = 30, door_flags = {forbidden = true}, getType = function() return 'Door' end}
        table.insert(G.buildings, pre)
        G.tiles['3,1,10'] = pre; G.pre = pre
        local z2 = {id = 78, x1 = 20, y1 = 0, x2 = 22, y2 = 2, z = 10}
        table.insert(G.buildings, z2)
        local d2 = {id = 31, door_flags = {forbidden = false}, getType = function() return 'Door' end}
        table.insert(G.buildings, d2)
        G.tiles['23,1,10'] = d2; G.d2 = d2
        G.units[4] = {id = 4, name = 'W', race = 1, enemy = {normal_race = -1}, pos = {x = 1, y = 1, z = 10}}
        G.units[8] = {id = 8, name = 'V', race = 1, enemy = {normal_race = -1}, pos = {x = 21, y = 1, z = 10}}
        G.units[6] = {id = 6, name = 'Dead', race = 9, dead = true, enemy = {normal_race = 1}, pos = {x = 0, y = 0, z = 0}}
        G.units[7] = {id = 7, name = 'Bitten', race = 1, enemy = {normal_race = -1}, pos = {x = 50, y = 50, z = 10},
                      syndromes = {active = {{type = 1}}}}
        G.saved['ai-overseer/threats'] = {cells = {['4'] = {zone = 77, doors = {}}, ['8'] = {zone = 78, doors = {}},
            ['6'] = {zone = 79, locked = true, doors = {}}, ['7'] = {zone = 80, doors = {}}}}""", E)
    G = E.G
    r = E.moon_cell(LUA.table_from([4, 8]), False, False)
    st = G.saved["ai-overseer/threats"]
    # the dead one's cell freed, the unnamed bitten one's kept
    assert st.cells["6"] is None and st.cells["7"] is not None and r.dead == 1, dict(r)
    c4, c8 = st.cells["4"], st.cells["8"]
    assert c4.locked and list(c4.doors.values()) == [30] and list(c4.pre.values()) == [30]
    assert E.cell_doors_held(c4) and c8.locked and G.d2.door_flags.forbidden
    # someone unlocks 31: relocked, its record kept (no second copy)
    LUA.execute("local E = ...; E.G.d2.door_flags.forbidden = false", E)
    r = E.moon_cell(LUA.table_from([4, 8]), False, False)
    assert r.relock and G.d2.door_flags.forbidden and list(st.cells["8"].doors.values()) == [31], dict(r)
    # a release while 7 fights: refused, nothing let out
    LUA.execute("local E = ...; E.G.units[7].opponent = {unit_id = 12}", E)
    r = E.moon_cell(LUA.table_from([]), True, False)
    assert r.rejected and r.wait and "fight" in r.error and st.cells["4"] is not None, dict(r)
    LUA.execute("local E = ...; E.G.units[7].opponent = {unit_id = -1}", E)
    r = E.moon_cell(LUA.table_from([]), True, False)
    st = G.saved["ai-overseer/threats"]
    assert st.cells["4"] is None and G.pre.door_flags.forbidden and not G.d2.door_flags.forbidden, dict(r)


finish()
