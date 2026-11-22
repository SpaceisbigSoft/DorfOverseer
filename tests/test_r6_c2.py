"""(r6 c2, 13c) The Python helper copies (`_int`, `_num`, `_c`, `_clamp`, `_d`,
`_l`, `_whole`, `_id`, `_h9`, `_site`, `_date`, `state_run`) now live once,
in brain/util.py. Each module imports the variant its copy was under its old
name; copies that differed from every shared helper stay local, marked
"kept local". This proves:

- no brain module defines one of these names identically to another module
  any more (every remaining definition is a marked, distinct variant);
- each module's name still exists and is util's helper;
- util's helpers answer as the old copies did on sample inputs.

    python tests/test_r6_c2.py
"""

from __future__ import annotations

import ast
import collections
import importlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import util  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402

BRAIN = ROOT / "brain"
NAMES = ("_int", "_num", "_c", "_clamp", "_d", "_l", "_whole", "_id", "_h9", "_site", "_date", "state_run")

# module -> {old name: util helper}
MOVED = {
    "alarm_caution": {"_clamp": "clamp"},
    "atlas": {"_date": "date_text"},
    "blueprint": {"_int": "whole_or_none"},
    "culture": {"_clamp": "clamp"},
    "design": {"_int": "is_int", "_clamp": "clamp"},
    "design_rules": {"_clamp": "clamp"},
    "digest": {"_d": "as_dict", "_l": "as_list", "_num": "is_num"},
    "fields": {"_int": "int_or_none"},
    "floor_soil": {"_whole": "is_int", "_d": "as_dict", "_l": "as_list"},
    "learning": {"_date": "date_text"},
    "masterplan_floors": {"_whole": "is_int", "_d": "as_dict", "_l": "as_list"},
    "order_check": {"_int": "int_or_none"},
    "overseer": {"state_run": "state_run", "_site": "site_of"},
    "perf": {"_d": "as_dict", "_num": "is_num"},
    "planner_alarm": {"_c": "conf_get", "_int": "is_int"},
    "planner_artifacts": {"_id": "int_or_none"},
    "planner_captives": {"_c": "conf_lookup", "_int": "trunc_or_zero"},
    "planner_cleanup": {"_int": "int_or_zero"},
    "planner_defence_floor": {"_num": "num_or_none"},
    "planner_food": {"_int": "int_or_zero"},
    "planner_growth": {"_h9": "conf_lookup"},
    "planner_hauling": {"_int": "int_or_zero"},
    "planner_hazards": {"_c": "conf_get", "_int": "is_int"},
    "planner_holdfast": {"_int": "int_or_none", "_num": "float_or_none"},
    "planner_hunt": {"_num": "float_or_none", "_id": "int_or_none"},
    "planner_husbandry": {"_int": "int_or_zero"},
    "planner_ice": {"_num": "num_or_none"},
    "planner_killzone": {"_c": "conf_get"},
    "planner_lure": {"_c": "conf_soft", "_num": "is_num"},
    "planner_matchup": {"_num": "num_or_none"},
    "planner_missions": {"_int": "int_or_none"},
    "planner_outside": {"_c": "conf_lookup"},
    "planner_piles": {"_int": "int_or_zero"},
    "planner_provisions": {"_int": "int_or_zero"},
    "planner_raids": {"_num": "num_or_none", "_int": "int_or_none"},
    "planner_recovery": {"_c": "conf_lookup"},
    "planner_shelter": {"_int": "int_or_none"},
    "planner_siege": {"_num": "is_num"},
    "planner_stuck": {"_int": "int_or"},
    "planner_syndromes": {"_int": "trunc_or_zero"},
    "planner_threats": {"_num": "is_num"},
    "planner_traffic": {"_int": "int_or_zero"},
    "planner_training": {"_d": "as_dict", "_l": "as_list", "_int": "int_or_none"},
    "planner_visitors": {"_h9": "conf_lookup"},
    "planner_war_hold": {"_int": "is_int"},
    "planner_weather": {"_c": "conf_get", "_num": "is_num"},
    "planner_welfare": {"_c": "conf_lookup"},
    "planner_wellsafe": {"_c": "conf_soft"},
    "scorecard": {"state_run": "state_run", "_site": "site_of", "_whole": "is_int"},
    "strategist": {"_int": "whole_or_none"},
    "timeline": {"_num": "num_or_none"},
}


def _norm(node: ast.FunctionDef) -> str:
    n = ast.parse(ast.unparse(node)).body[0]
    n.returns = None
    for a in n.args.args + n.args.kwonlyargs:
        a.annotation = None
    if n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
        n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(n)


def _defs():
    out = collections.defaultdict(list)
    for p in sorted(BRAIN.glob("*.py")):
        if p.name == "util.py":
            continue
        src = p.read_text(encoding="utf-8")
        for n in ast.parse(src).body:
            if isinstance(n, ast.FunctionDef) and n.name in NAMES:
                above = src.split("\n")[n.lineno - 2] if n.lineno > 1 else ""
                out[n.name].append((p.stem, _norm(n), above))
    return out


@test("no helper is defined the same way in two brain modules; each local one left is marked")
def _():
    for name, defs in _defs().items():
        bodies = collections.Counter(b for _, b, _ in defs)
        twice = [b for b, c in bodies.items() if c > 1]
        assert not twice, (name, [m for m, b, _ in defs if b in twice])
        for m, _, above in defs:
            assert "kept local" in above, (m, name)


@test("no left definition equals a util helper (util's would have been used)")
def _():
    usrc = (BRAIN / "util.py").read_text(encoding="utf-8")
    canon = set()
    for n in ast.parse(usrc).body:
        if isinstance(n, ast.FunctionDef) and n.name != "_planner_config":
            for old in NAMES:
                n2 = ast.parse(ast.unparse(n).replace("_planner_config()", "PLANNER_CONFIG")
                               .replace("as_dict(", "_d(")).body[0]
                n2.name = old
                canon.add(_norm(n2))
    for name, defs in _defs().items():
        for m, b, _ in defs:
            assert b not in canon, (m, name)


@test("every moved name is still importable from its module, and is util's helper")
def _():
    for mod, names in MOVED.items():
        m = importlib.import_module(mod)
        for old, new in names.items():
            assert getattr(m, old) is getattr(util, new), (mod, old, new)
    import planner_core
    assert planner_core._clamp(2.6, 0, 10) == 3      # planner_core's own variant (rounds), kept


SAMPLES = [None, True, False, 0, 3, -2, 2.0, 2.5, float("nan"), float("inf"), "3", [], {}, [1], {"a": 1}]


def _same(a, b):
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return True
    return type(a) is type(b) and a == b


@test("util's helpers answer as the old copies did")
def _():
    old = {
        "as_dict": lambda v: v if isinstance(v, dict) else {},
        "as_list": lambda v: v if isinstance(v, list) else [],
        "is_int": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "int_or_none": lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None,
        "int_or_zero": lambda v: v if isinstance(v, int) and not isinstance(v, bool) else 0,
        "trunc_or_zero": lambda v: int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0,
        "is_num": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "num_or_none": lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None,
        "float_or_none": lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None,
    }

    def whole(v):
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        return None
    old["whole_or_none"] = whole
    for name, f in old.items():
        for v in SAMPLES:
            try:
                want = f(v)
            except (ValueError, OverflowError):
                want = "raise"
            try:
                got = getattr(util, name)(v)
            except (ValueError, OverflowError):
                got = "raise"
            assert _same(got, want), (name, v, got, want)
    for v in SAMPLES:
        assert util.int_or(v, 7) == (v if util.is_int(v) else 7) and util.int_or(v) == util.int_or_none(v)
    assert util.clamp(5, 0, 3) == 3 and util.clamp(-1, 0, 3) == 0 and util.clamp(1.5, 0, 3) == 1.5


@test("the config lookups keep their three behaviours")
def _():
    k = next(iter(PLANNER_CONFIG))
    assert util.conf_get({}, k) == PLANNER_CONFIG[k] and util.conf_get({k: "x"}, k) == "x"
    try:
        util.conf_get({"zz_none": 1}, "zz_none")       # eager: the table must have the key
        raise AssertionError("conf_get read a key the table lacks")
    except KeyError:
        pass
    assert util.conf_lookup({"zz_none": 1}, "zz_none") == 1      # lazy
    assert util.conf_lookup({}, k) == PLANNER_CONFIG[k]
    assert util.conf_soft(None, k) == PLANNER_CONFIG[k] and util.conf_soft(None, "zz_none") is None
    assert util.conf_soft({k: None}, k) is None


@test("site_of, date_text and state_run answer as before")
def _():
    assert util.site_of("civ#Boatmurdered") == "Boatmurdered" and util.site_of(None) == "None"
    assert util.date_text({"date": {"day": 3, "month": "Granite", "year": 105}}) == "3 Granite y105"
    assert util.date_text({"date": [1]}) == "None None yNone"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "s.json"
        p.write_text(json.dumps({"_run": "r7", "x": 1}), encoding="utf-8")
        assert util.state_run(p) == "r7"
        p.write_text(json.dumps({"x": 1}), encoding="utf-8")
        assert util.state_run(p) is None
        assert util.state_run(Path(d) / "none.json") is None


if __name__ == "__main__":
    finish()
