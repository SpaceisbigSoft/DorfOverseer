"""(r9 f2) Water findings of the 14 Nov audit (A4) left open:

  * A4 21: the shaft watcher takes a danger whose block has no cavern
    feature as unknown (judged by its levels), not as another cavern;
  * A4 23: the cavern scan's open test reads every seen sample over a few
    reports (OPEN_CHECKS a report, round the list), not the first ones only;
  * A4 26: a cavern well's shaft hatch the gates' scan took for a cavern
    entrance's hatch is marked, and the gate watcher neither counts it open
    nor shuts it (its own watcher works it).

(A4 19 is in test_r33_merge, A4 24 and 26's seal side in test_r47_wellsafe.)

    python tests/test_r9_f2.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from builder_wells_util import wells_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:  # pragma: no cover
    LuaRuntime = None


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


def lua_test(name):
    def deco(fn):
        def run():
            need_lua()
            fn()
        return test(name)(run)
    return deco


# --- A4 21: the shaft watcher and a block with no cavern feature -----------------------------------

WATCH_GAME = r"""
local src = ...
local T = {units = {}, feat = {}}
local e = setmetatable({T = T}, {__index = _G})
e.df = {global = {cur_year = 1, cur_year_tick = 0, world = {units = {active = T.units}}}}
e.dfhack = {units = {isActive = function() return true end, isDead = function() return false end,
                     isCitizen = function() return false end, isDanger = function(u) return u.danger == true end,
                     isGreatDanger = function(u) return u.great == true end, isAnimal = function() return false end,
                     isFortControlled = function() return false end, isTame = function() return false end},
            maps = {getTileBlock = function(x, y, z)
                        local f = T.feat[z]
                        if f == nil then return nil end
                        return {global_feature = f}
                    end}}
assert(load(src, 'ai-builder-wells', 't', e))()
return e
"""


@lua_test("A4 21: a danger in a block with no cavern feature is judged by its levels (it was ignored as 'another "
          "cavern'); one in another cavern's block still is ignored; one in the shaft's own cavern counts")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(WATCH_GAME, wells_src())
    t = lua.table_from
    # the well at z50, its shaft's bottom at z40 in cavern 7 (its block and the one under it)
    E.T.feat[39] = 7
    E.T.feat[40] = 7
    E.T.feat[37] = -1          # a rock tunnel under the shaft's bottom: no cavern feature
    E.T.feat[36] = 9           # another cavern
    E.T.units[1] = t({"id": 9, "danger": True, "flags1": t({}), "pos": t({"x": 105, "y": 100, "z": 37})})

    def hit():
        wells = t([t({"x": 100, "y": 100, "z": 50, "hz": 40})])
        r = E.shaft_threats(wells)
        return r[1]

    h = hit()
    assert h is not None and h.v.d == 5, "3 levels under the shaft in a featureless block: near (was ignored)"
    E.T.units[1].pos.z = 36
    assert hit() is None, "another cavern's block: walled off by rock"
    E.T.units[1].pos.z = 39
    assert hit() is not None and hit().v.d == 5
    # far down in a featureless block: past SHAFT_LEVELS, as for an unknown cavern
    E.T.feat[2] = -1
    E.T.units[1].pos.z = 2
    assert hit() is None


# --- A4 23: the cavern scan's open test --------------------------------------------------------------

SCAN_FAKE = _const("test_i6_speed.py", "SCAN_FAKE")


@lua_test("A4 23: the open test reads OPEN_CHECKS seen samples a report from where the last stopped, so a breach "
          "past the first OPEN_CHECKS is found within a few reports (it never was); found again at once after")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    SL = lua.execute("local src = ...; local env = setmetatable({}, {__index = _G}); "
                     "assert(load(src, 'ai-slices', 't', env))(); return env",
                     (ROOT / "lua" / "ai-slices.lua").read_text(encoding="utf-8"))
    C = lua.execute(SCAN_FAKE, (ROOT / "lua" / "ai-cavern-scan.lua").read_text(encoding="utf-8"), SL)
    C.SCAN_MS = 1e9
    C.OPEN_CHECKS = 3
    rows = lua.table_from([lua.table_from({"name": "C", "blocks": lua.table_from([lua.table_from([0, 0, 40])])})])
    groups, cit = lua.table_from({1: True}), lua.table_from([])
    # ten seen samples in the one block (all 16 hidden but these)
    seen = [(sx * 5, sy * 5) for sx in range(4) for sy in range(4)][:10]
    for x, y in seen:
        C.W.hidden[f"{x},{y},40"] = False
    out, _ = C.scan(rows, groups, cit, "m", 0)
    assert out["C"].seen == 10 and out["C"].open is False
    order = [(C.CAVERN_SCAN.caverns["C"].seen[i].x, C.CAVERN_SCAN.caverns["C"].seen[i].y) for i in range(1, 11)]
    bx, by = order[8]                                   # the 9th seen: past the first 3
    C.W.group[f"{bx},{by},40"] = 1
    found = None
    for n in range(1, 6):
        out, _ = C.scan(rows, groups, cit, "m", n)
        if out["C"].open:
            found = n
            break
    assert found is not None and found <= 4, found
    assert (out["C"].open_at.x, out["C"].open_at.y) == (bx, by)
    out, _ = C.scan(rows, groups, cit, "m", 10)          # still open: read first again
    assert out["C"].open is True
    C.W.group[f"{bx},{by},40"] = None                   # walled off: not open (every sample read in turn)
    for n in range(11, 16):
        out, _ = C.scan(rows, groups, cit, "m", n)
        assert out["C"].open is False


# --- A4 26: the gates and a cavern well's shaft hatch ----------------------------------------------

GATES_HARNESS = _const("test_gates.py", "HARNESS")
FORT = ast.literal_eval(next(ast.get_source_segment((ROOT / "tests" / "test_gates.py").read_text(encoding="utf-8"), n.value)
                             for n in ast.parse((ROOT / "tests" / "test_gates.py").read_text(encoding="utf-8")).body
                             if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "FORT"))


@lua_test("A4 26: the scan marks a cavern entrance's hatch that is a cavern well's shaft hatch (it still seals the "
          "way); a plain one is not marked")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M, W = lua.execute(GATES_HARNESS, module_src("ai-gates.lua"))
    level = lua.table()
    for y, r in enumerate(FORT):
        level[y] = r
    m = lua.table()
    m[0] = level
    W.map = m
    hatch = {"id": 5, "kind": "hatch", "x1": 13, "y1": 16, "x2": 13, "y2": 16, "z": 0}
    W.buildings = lua.table_from([lua.table_from(hatch)])
    starts = lua.table_from({1: lua.table_from({"x": 20, "y": 8, "z": 0})})

    def cavern():
        es, _, _ = M.find_entrances(starts, W.buildings)
        c = [es[i] for i in range(1, len(es) + 1) if es[i].kind == "cavern"][0]
        return c

    c = cavern()
    assert c.sealed and c.equipment[1].id == 5 and not c.equipment[1].well_shaft
    k = (0 * 4096 + 16) * 4096 + 13
    M.well_shaft_keys = lua.eval("function(k) return function() return {[k] = true} end end")(k)
    W.buildings = lua.table_from([lua.table_from(hatch)])
    c = cavern()
    assert c.sealed and c.equipment[1].id == 5 and c.equipment[1].well_shaft is True


_r32 = (ROOT / "tests" / "test_r32_gatesplit.py").read_text(encoding="utf-8")
_ns: dict = {"module_src": module_src, "sys": sys}
if LuaRuntime is not None:
    exec(compile(_r32[_r32.index("try:\n    from lupa"):_r32.index("\ndef lst")], "r32rig", "exec"), _ns)


@lua_test("A4 26: the gate watcher leaves a cavern well's shaft hatch to its own watcher: not counted open, not "
          "shut for a danger at the entrance (a plain hatch there is)")
def _():
    t = _ns["LUA"].table_from
    danger = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                "pos": t({"x": 112, "y": 149, "z": 171})})
    E, G = _ns["rig"]()
    G.units[1] = danger
    assert E.open_pieces(E.GATES.entrances[1]) == 1
    r = E.close_threatened_gates(False)
    assert r.ok and G.blds[7].door_flags.closed, dict(r)           # a plain gate: shut
    E, G = _ns["rig"]()
    E.GATES.entrances[1].equipment[1].well_shaft = True
    G.units[1] = t({"id": 99, "danger": True, "flags1": t({"caged": False, "chained": False}),
                    "pos": t({"x": 112, "y": 149, "z": 171})})
    assert E.open_pieces(E.GATES.entrances[1]) == 0
    E.close_threatened_gates(False)
    assert not G.blds[7].door_flags.closed and not G.blds[7].door_flags.forbidden
    assert len(G.pulled) == 0 and not (E.GATES.closed and E.GATES.closed[1])


if __name__ == "__main__":
    finish()
