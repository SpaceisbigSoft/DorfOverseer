"""(r33a) The dead werebeasts' release never frees a living cursed dwarf's cell.

What the journal showed (B, 26 Nov 14:23 on): a citizen werellama (Olin,
Miner) killed 2 dwarves; B's other cursed dwarf Asob had no cell. Every
20-40 s two moon_cell calls alternated for good:
  - the reserve ("Asob ...: werebeast-cursed and no cell yet: one made ready
    now") reserved a cell for Asob;
  - the release ("the cells of dead werebeasts: unlock their doors and drop
    them", ids [] release true) freed every cell, Asob's reserved one with
    the dead's, so Asob never kept a cell;
  - and each call said "the drawbridge of Bomrek (a dead weresheep)'s cell
    stays up: no drawbridge on the cell's doorway": his cell was on record
    behind a drawbridge that was not there, free() refused it for good.

Now: the brain sends that release with dead_only (only the dead's cells),
the Rules-off release with all; a release keeps a living cursed dwarf's
reserved cell unless all; a were cell whose bridge isn't there (or gone) is
freed as a plain room with a note, and a living dwarf's such cell is dropped
for another room (rekind).

    python tests/test_r33a_were_release.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, plan  # noqa: E402

CH = [{"phase": 27, "tick": 110290156}]


def fort(were, settings=None):
    from test_threats import fort as tfort
    s = tfort({"were": were})
    if settings:
        s.setdefault("settings", {}).update(settings)
    return s


def moon(props):
    return [p for p in props if p.rule == "moon_cell"]


@test("B: Asob cursed, no cell, a dead were's cell on record, moon past: the reserve, and the release is dead_only")
def _():
    rows = [{"id": 5, "name": "Asob", "by_syndrome": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 8, "cells": [], "dead_cells": 1}), Memory())[0])
    res = [p for p in c if p.action.get("reserve")]
    rel = [p for p in c if p.action.get("release")]
    assert res and res[0].action["ids"] == [5], c
    assert rel and rel[0].action.get("dead_only") is True and "dead werebeasts" in rel[0].reason, c


@test("B: Asob's cell reserved: no reserve again; the dead's release still dead_only (Asob's cell not its)")
def _():
    rows = [{"id": 5, "name": "Asob", "by_syndrome": True, "cell": True, "reserved": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 8, "dead_cells": 1,
                        "cells": [{"unit_id": 5, "reserved": True, "kind": "jail"}]}), Memory())[0])
    assert not [p for p in c if p.action.get("reserve")], c
    assert all(p.action.get("dead_only") is True for p in c if p.action.get("release")), c


@test("the full moon past with living cells: a plain release (not dead_only); Rules off: all")
def _():
    rows = [{"id": 1, "name": "Litast", "by_syndrome": True, "cell": True, "locked": True}]
    c = moon(plan(fort({"list": rows, "changes": CH, "moon_phase": 8, "dead_cells": 2,
                        "cells": [{"unit_id": 1, "locked": True}]}), Memory())[0])
    rel = [p for p in c if p.action.get("release")]
    assert rel and not rel[0].action.get("dead_only") and "let 1 werebeast(s) out" in rel[0].reason, c
    s = fort({"list": rows, "changes": CH, "moon_phase": 8, "cells": [{"unit_id": 1, "locked": True}]},
             {"moon_cells": False})
    c = moon(plan(s, Memory())[0])
    assert c and c[0].action.get("release") and c[0].action.get("all") is True, c


@test("words: the dead-only release says what it does")
def _():
    import overseer_words as OW
    src = (ROOT / "brain" / "overseer_words.py").read_text(encoding="utf-8")
    assert "unlock and drop the cells of dead werebeasts" in src
    fn = getattr(OW, "short", None)
    if callable(fn):
        try:
            got = fn({"type": "moon_cell", "ids": [], "release": True, "dead_only": True})
        except TypeError:
            return
        if isinstance(got, str):
            assert "dead werebeasts" in got, got


@test("lua source: dead_only and all validated by the bridge and passed on; free() keeps the living's cells")
def _():
    w = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    act = (ROOT / "lua" / "ai-threats-actions.lua").read_text(encoding="utf-8")
    assert "moon_cell: dead_only is true or false" in w and "moon_cell: all is true or false" in w
    assert "reserve = a.reserve == true}, a)" in w
    assert "if raw.dead_only == true then opts.dead_only = true end" in act
    body = act[act.index("local function free(uid, c)"):act.index("local pre = {}")]
    assert "if dead_only and living then" in body and "c.reserved and not c.locked and opts.all ~= true" in body
    assert "were_unworkable(c)" in body and "freed as a plain room" in body
    assert "function were_unworkable(c)" in act and "out.rekind" in act


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

def env():
    try:
        from lupa.lua53 import LuaRuntime  # noqa: F401
    except ImportError:
        return None, None
    import test_item31_were_rooms as T31
    LUA, E = T31.need_env()
    # Asob (5) alive and cursed; Bomrek (6) a dead weresheep in a were cell with no bridge
    LUA.execute("""local E = ...; local G = E.G
        E.dfhack.units.isDead = function(u) return u.dead == true end
        G.units[5] = {id = 5, name = 'Asob', race = 1, enemy = {normal_race = -1}, pos = {x = 40, y = 40, z = 10}}
        G.units[6] = {id = 6, name = 'Bomrek', race = 1, dead = true, enemy = {normal_race = -1}, pos = {x = 0, y = 0, z = 0}}
        G.units[4] = nil
        G.W.list = {{key = 'were:3:1', x1 = 20, y1 = 20, x2 = 21, y2 = 21, z = 10,
                     bridge = {x = 20, y = 22, z = 10}, lever = {x = 20, y = 23, z = 10}}}
        -- no drawbridge on the doorway (never built, or gone): no bridge_id, not built
        G.W.cell_state = function() return {built = false, linked = false, lever_id = 901} end
        G.W.set_raised = function() return false, 'no drawbridge on the cell\\'s doorway' end
        G.saved['ai-overseer/threats'] = {cells = {['6'] = {zone = 'were:3:1', kind = 'were', locked = true, doors = {}}},
                                          digs = {}}""", E)
    return LUA, E


@test("lua (B): the reserve and the dead-only release alternating keep Asob's reservation; Bomrek's cell freed, noted")
def _():
    LUA, E = env()
    if LUA is None:
        return
    G = E.G
    T = LUA.table_from
    r = E.moon_cell(T([]), True, False, None, T({"dead_only": True}))
    st = G.saved["ai-overseer/threats"]
    assert st.cells["6"] is None and r.dead == 1 and not r.errors, dict(r)         # Bomrek dropped
    assert r.notes and "freed as a plain room" in r.notes[1] and "no drawbridge" in r.notes[1], dict(r)
    r = E.moon_cell(T([5]), False, False, None, T({"reserve": True}))
    c = G.saved["ai-overseer/threats"].cells["5"]
    assert c and c.reserved and c.zone == 77, dict(r)
    # another dead werebeast's cell on record beside Asob's reserved one: only the dead's freed
    LUA.execute("""local E = ...; local G = E.G
        G.units[7] = {id = 7, name = 'Olin', race = 1, dead = true, enemy = {normal_race = -1}, pos = {x = 0, y = 0, z = 0}}
        G.saved['ai-overseer/threats'].cells['7'] = {zone = 79, kind = 'jail', locked = true, doors = {}}""", E)
    r = E.moon_cell(T([]), True, False, None, T({"dead_only": True}))
    st = G.saved["ai-overseer/threats"]
    assert st.cells["5"] is not None and st.cells["5"].reserved, dict(r)          # Asob kept
    assert st.cells["7"] is None and r.dead == 1 and len(r.released) == 0, dict(r)
    for _ in range(3):
        r1 = E.moon_cell(T([5]), False, False, None, T({"reserve": True}))
        r2 = E.moon_cell(T([]), True, False, None, T({"dead_only": True}))
        assert r1.rejected and r1.nothing_to_do, dict(r1)                         # nothing to reserve again
        assert r2.rejected and r2.nothing_to_do, dict(r2)                         # nothing dead left
        assert G.saved["ai-overseer/threats"].cells["5"].reserved
    # a plain release (moon past) keeps the reserved cell too; all frees it
    E.moon_cell(T([]), True, False)
    assert G.saved["ai-overseer/threats"].cells["5"] is not None
    E.moon_cell(T([]), True, False, None, T({"all": True}))
    assert G.saved["ai-overseer/threats"].cells["5"] is None


@test("lua: the moon's call takes Asob's reserved jail: moved in and locked")
def _():
    LUA, E = env()
    if LUA is None:
        return
    G = E.G
    T = LUA.table_from
    E.moon_cell(T([5]), False, False, None, T({"reserve": True}))
    r = E.moon_cell(T([5]), False, False, None, T({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["5"]
    assert not c.reserved and c.kind == "jail" and G.moved == 1 and c.locked, dict(r)


@test("lua: a living cursed dwarf's were cell with no drawbridge: dropped for a jail (rekind), not 'stays up' forever")
def _():
    LUA, E = env()
    if LUA is None:
        return
    G = E.G
    T = LUA.table_from
    LUA.execute("""local E = ...; local G = E.G
        G.saved['ai-overseer/threats'].cells['5'] = {zone = 'were:3:1', kind = 'were', tick = 0, doors = {}}""", E)
    r = E.moon_cell(T([5]), False, False, None, T({"move_in": True}))
    c = G.saved["ai-overseer/threats"].cells["5"]
    assert r.rekind and "no drawbridge" in r.rekind[1], dict(r)
    assert c.zone == 77 and c.kind == "jail" and c.locked, dict(r)


finish()
