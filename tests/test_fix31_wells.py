"""(0.105.31) Wells nobody channels. Shore wells in all six forts sat at "0
of 1 tiles dug" 14-80 days (E: a year, four times on one tile, x67 y124):
DF's DigChannel job with no worker, free_dig_jobs freeing nothing, and
dig_first unable to raise a channel. Now the bridge says why
(well_dig_check, in the report's dig as `well_check`), renew_well_dig takes
the unworked job away and designates the channel again at a higher
priority, a well given up as out of reach isn't placed on that spot again,
and the brain renews the job and names the cause in Needs you.

    python tests/test_fix31_wells.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, test as plain_test, finish  # noqa: E402
from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick  # noqa: E402
from planner_core import NEEDS_YOU  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None


def _const(path: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# ---- the bridge ------------------------------------------------------------------------

def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(_const("test_builder.py", "HARNESS"), layouts, builder)
    lua.execute("df = {global = {cur_year = 148, cur_year_tick = 100}}")
    return lua, B, W


if LuaRuntime is not None:
    LUA, B, W = boot()


def _reset():
    if LuaRuntime is None:
        return
    W.reset()
    B.well_miners = lambda: W.citizens          # every citizen a miner
    B.CAVERN_NO_SPOT = None


test = make_test(before=_reset)


def water_column(x, y, top, open_levels=2, depth=7):
    for k in range(1, open_levels + 1):
        W.set(x, y, top - k, LUA.table_from({"shape": "EMPTY"}))
    W.set(x, y, top - open_levels - 1, LUA.table_from({"shape": "EMPTY", "liquid": True, "depth": depth}))


def a_well():
    water_column(70, 58, 71)
    r = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 100}), False)
    assert r.ok and (r.x, r.y) == (70, 58), (r.ok, r.error)
    return r


def report_dig():
    return B.projects_report().open[1].dig


if LuaRuntime is not None:
    @test("wells 1: the report says why a well's channel waits (job unworked, no miners, unreached, gone)")
    def _():
        a_well()
        W.jobs = LUA.table_from({"70,58,71": LUA.table_from({"job_type": 0})})
        d = report_dig()
        assert d.dug == 0 and d.well_check.cause == "unworked", dict(d.well_check)
        assert (d.well_check.x, d.well_check.y) == (70, 58)
        B.well_miners = lambda: LUA.table()                           # nobody mines
        assert report_dig().well_check.cause == "no_miners"
        B.well_miners = lambda: LUA.table_from([LUA.table_from({"x": 5, "y": 5, "z": 90})])   # walled off
        assert report_dig().well_check.cause == "unreached"
        B.well_miners = lambda: W.citizens
        W.jobs = LUA.table()
        assert report_dig().well_check.cause == "waiting"
        LUA.eval("function(W) W.get(70, 58, 71).dig = 'Default' end")(W)
        assert report_dig().well_check.cause == "wrong_designation"
        LUA.eval("function(W) local t = W.get(70, 58, 71); t.dig = nil; t.designated = false end")(W)
        assert report_dig().well_check.cause == "no_designation"
        # dug: no check
        LUA.eval("function(W) local t = W.get(70, 58, 71); t.shape = 'EMPTY' end")(W)
        assert report_dig().well_check is None

    @test("wells 2: renew_well_dig designates the channel again at the priority; refused for other levels")
    def _():
        r = a_well()
        dry = B.renew_well_dig(r.project_id, 2, True)
        assert dry.ok and dry.dry_run and not W.get(70, 58, 71).dig_text.endswith("2")
        got = B.renew_well_dig(r.project_id, 2, False)
        assert got.ok and got.priority == 2 and got.times == 1, dict(got)
        assert W.get(70, 58, 71).dig_text == "h2" and W.get(70, 58, 71).designated
        assert report_dig().renewed == 1
        assert not B.renew_well_dig(999, 2, False).ok
        LUA.eval("function(W) W.get(70, 58, 71).shape = 'EMPTY' end")(W)
        r2 = B.renew_well_dig(r.project_id, 2, False)
        assert not r2.ok and r2.rejected and "nothing left" in r2.error
        # prioritize_project still refuses a channel (0.105.30)
        assert not B.prioritize_project(r.project_id, 2, False).ok

    @test("wells 3: a well given up as out of reach isn't placed on the same spot again")
    def _():
        water_column(70, 58, 71)
        water_column(74, 58, 71)
        r = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 100}), False)
        assert r.ok, r.error
        first = (r.x, r.y)
        assert B.cancel_project(r.project_id, True).ok
        r2 = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 200}), True)
        assert r2.ok and (r2.x, r2.y) != first, (r2.ok, r2.error, r2.x, r2.y)
        # given up as slow (not unreached): the spot may be used again
        r3 = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 300}), False)
        assert B.cancel_project(r3.project_id, False).ok
        r4 = B.place_well(LUA.table(), LUA.table_from({"year": 148, "tick": 400}), True)
        assert r4.ok and (r4.x, r4.y) == (r3.x, r3.y)


# ---- the bridge's registration ----------------------------------------------------------

@plain_test("wells 4: renew_well_dig is an action, dry-run safe, clears the registry, has short words")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "renew_well_dig = act_renew_well_dig" in src
    dry = src[src.index("DRY_OK = {}"):src.index("DRY_OK = {}") + 1500]
    assert "'renew_well_dig'" in dry
    assert "CACHE_INVALIDATES.renew_well_dig" in src
    from overseer import SHORT_WORDS
    assert "renew_well_dig" in SHORT_WORDS


# ---- the brain -------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def stuck_well(days, check=None, kind="well", urgent=False):
    s = copy.deepcopy(BASE)
    dig = {"total": 1, "dug": 0, "digging": 1}
    if check:
        dig["well_check"] = check
    s["projects"] = dict(s.get("projects") or {}, open=[{"id": 6, "kind": kind, "phase": "dig", "urgent": urgent,
                                                         "dig": dig}])
    m = Memory()
    m.dig_seen = {"6": {"dug": 0, "tick": abs_tick(s) - days * TICKS_PER_DAY}}
    return s, m


def run(s, m):
    from planner_building import _dig_stall_rule
    props, notes = [], []
    _dig_stall_rule(s, m, PLANNER_CONFIG, s["projects"]["open"], props, notes)
    return props, notes


UNWORKED = {"cause": "unworked", "text": "DF made the channel job but no miner takes it", "x": 67, "y": 122,
            "elevation": 42}


@plain_test("wells 5: a channel not dug in a week is renewed (priority 2, 1 when urgent), then weekly")
def _():
    s, m = stuck_well(3, UNWORKED)
    props, _ = run(s, m)
    assert not [p for p in props if p.action["type"] == "renew_well_dig"]
    s, m = stuck_well(10, UNWORKED)
    props, notes = run(s, m)
    got = [p for p in props if p.action["type"] == "renew_well_dig"]
    assert got and got[0].action == {"type": "renew_well_dig", "project_id": 6, "priority": 2}, props
    assert not [n for n in notes if n.startswith(NEEDS_YOU)]          # not yet: under dig_stall_days
    props, _ = run(s, m)                                                # the same cycle again: not twice
    assert not [p for p in props if p.action["type"] == "renew_well_dig"]
    s, m = stuck_well(10, UNWORKED, urgent=True)
    assert [p for p in run(s, m)[0] if p.action.get("priority") == 1]
    # never dig_first for a well (0.105.30), and never for another kind's level
    s, m = stuck_well(10, UNWORKED, kind="hospital")
    assert not [p for p in run(s, m)[0] if p.action["type"] == "renew_well_dig"]


@plain_test("wells 6: from dig_stall_days the cause and what is done go to Needs you")
def _():
    s, m = stuck_well(30, UNWORKED)
    props, notes = run(s, m)
    asks = [n for n in notes if n.startswith(NEEDS_YOU)]
    assert len(asks) == 1 and "x67 y122 elevation 42" in asks[0] and "renews the channel job" in asks[0], asks
    assert "given up in 26 days" in asks[0], asks
    s, m = stuck_well(30, {"cause": "no_miners", "text": "no citizen has the mining labour", "x": 1, "y": 2,
                           "elevation": 3})
    props, notes = run(s, m)
    asks = [n for n in notes if n.startswith(NEEDS_YOU)]
    assert asks and "Mining labour" in asks[0]
    assert not [p for p in props if p.action["type"] == "renew_well_dig"]   # renewing wouldn't help
    s, m = stuck_well(30, {"cause": "unreached", "text": "none of the 4 miners can walk to beside it"})
    asks = [n for n in run(s, m)[1] if n.startswith(NEEDS_YOU)]
    assert asks and "can walk to beside it" in asks[0] and "open the way" in asks[0].lower()


if __name__ == "__main__":
    sys.exit(finish())
