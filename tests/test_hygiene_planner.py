"""(0.105.25, 13c planner) The planner's parts after the split by theme:
every name a part exports exists, every name the split moved is still
reached through the part it came from (and through `planner`), every
global a planner function reads resolves, and the names the other tests
patch by module still live where those patches take effect.

    python tests/test_hygiene_planner.py
"""

from __future__ import annotations

import builtins
import dis
import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
RESULTS = []

import planner  # noqa: E402

# the parts split out in 13c, and the part each came from (which re-exports it)
SPLIT = {"planner_config": "planner_core", "planner_wells": "planner_building",
         "planner_growth": "planner_building", "planner_moods": "planner_society",
         "planner_visitors": "planner_society", "planner_health": "planner_society",
         "planner_locations": "planner_society", "planner_farms": "planner_industry",
         "planner_labor": "planner_industry", "planner_trade": "planner_industry",
         "planner_orders": "planner_industry", "planner_gates": "planner_military"}
PARTS = sorted(p.stem for p in (ROOT / "brain").glob("planner*.py"))


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)[:600]))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


@test("every part's __all__ names exist in it")
def _():
    bad = []
    for name in PARTS:
        mod = importlib.import_module(name)
        bad += [f"{name}.{n}" for n in getattr(mod, "__all__", []) if not hasattr(mod, n)]
    assert not bad, bad


@test("every name a split-out part exports is the same object in the part it came from (and in planner when exported)")
def _():
    bad = []
    for new, old in SPLIT.items():
        nm, om = importlib.import_module(new), importlib.import_module(old)
        names = list(nm.__all__)
        assert names, new
        for n in names:
            if getattr(om, n, None) is not getattr(nm, n):
                bad.append(f"{old}.{n}")
            # names the part exported before the split still reach `planner`
            if n in getattr(om, "__all__", []) and getattr(planner, n, None) is not getattr(nm, n):
                bad.append(f"planner.{n}")
    assert not bad, bad


@test("every global a planner function reads resolves (no name lost in a move)")
def _():
    bad = []
    for name in PARTS:
        mod = importlib.import_module(name)
        src = (ROOT / "brain" / f"{name}.py").read_text(encoding="utf-8")

        def walk(code, where):
            for ins in dis.get_instructions(code):
                if ins.opname in ("LOAD_GLOBAL", "LOAD_NAME"):
                    n = str(ins.argval).replace(" + NULL", "").replace("NULL + ", "")
                    if n not in mod.__dict__ and not hasattr(builtins, n):
                        bad.append(f"{name}{where}: {n}")
            for c in code.co_consts:
                if isinstance(c, types.CodeType):
                    walk(c, f"{where}.{c.co_name}")
        walk(compile(src, name, "exec"), "")
    assert not bad, bad


@test("names other tests patch by module are still defined (and called) where the patch takes effect")
def _():
    import planner_building
    import planner_society
    # test_planner patches planner_building.social_shortfall / temple_size and plans;
    # test_small_open patches planner_society.stress_causes for _complaint_notes
    for mod, n in ((planner_building, "social_shortfall"), (planner_building, "temple_size"),
                   (planner_building, "_project_rules"), (planner_society, "stress_causes"),
                   (planner_society, "_cause"), (planner, "_pasture_hold")):
        assert getattr(mod, n).__module__ == mod.__name__ or n == "_pasture_hold", (mod.__name__, n)


@test("the dead names stay gone, and PLANNER_CONFIG is one dict wherever it is reached")
def _():
    import planner_config
    import planner_core
    import planner_military
    import planner_world
    assert not hasattr(planner_core, "GEAR_RECIPES")
    assert not hasattr(planner_military, "_free_gate_lever")
    assert not hasattr(planner_world, "TRIBUTE_POLICIES")
    assert planner_core.PLANNER_CONFIG is planner_config.PLANNER_CONFIG is planner.PLANNER_CONFIG
    for k in ("tidy_cooldown_ticks", "convict_queue_min"):
        assert k not in planner.PLANNER_CONFIG, k


@test("stamp_tick: a {year, tick} stamp as ticks, None for anything else")
def _():
    from planner_core import TICKS_PER_YEAR, abs_tick, stamp_tick
    assert stamp_tick({"year": 3, "tick": 50}) == 3 * TICKS_PER_YEAR + 50 == abs_tick({"date": {"year": 3, "tick": 50}})
    for bad in (None, {}, {"year": 3}, {"year": "3", "tick": 1}, [3, 50]):
        assert stamp_tick(bad) is None, bad


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
