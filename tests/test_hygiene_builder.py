"""(13c builder) The builder split into parts, and the shared helpers and
"search cut short" answers that came with it, on test_builder's fake fort
(its harness is read from that file, not copied). Needs lupa.

    python tests/test_hygiene_builder.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(ROOT / "lua")
    layouts = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    return lua, B, W


LUA, B, W = boot()


def test(name):
    def wrap(fn):
        W.reset()
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


@test("split: every ai-builder-<part>.lua beside the hub is in PARTS, and each part's names are the hub's")
def _():
    files = sorted(p.stem[len("ai-builder-"):] for p in (ROOT / "lua").glob("ai-builder-*.lua"))
    parts = sorted(B.PARTS[i] for i in range(1, len(B.PARTS) + 1))
    assert files == parts, (files, parts)
    # one name from each part, reached through the hub as the bridge does
    for name in ("choose_site", "start_project", "farm_plots", "place_well", "cistern_step",
                 "place_keep", "remove_workshops", "qf_try", "site_get", "item_held"):
        assert B[name] is not None, name


@test("split: a swap on the hub (as the tests and the bridge do) reaches the code in a part")
def _():
    real = B.walk_group
    seen = []
    B.walk_group = lambda x, y, z: seen.append(1) or 0
    try:
        B.find_farm_spots(4, LUA.table(), False)
    finally:
        B.walk_group = real
    assert seen, "find_farm_spots (ai-builder-farms) did not call the swapped walk_group"


@test("split: no part is a script of its own: none says --@ module, each says it is ai-builder's")
def _():
    for p in (ROOT / "lua").glob("ai-builder-*.lua"):
        src = p.read_text(encoding="utf-8")
        assert "@ module" not in src, p.name
        assert "A part of ai-builder" in src[:600], p.name


@test("dead code gone: find_pasture_spots, check_level, the first building_kind_at")
def _():
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "lua").glob("ai-builder*.lua"))
    assert "function find_pasture_spots" not in src
    assert "function check_level" not in src
    assert len(re.findall(r"^function building_kind_at", src, re.M)) == 1


QF_SPY = """
local B, mode = ...
local qf = reqscript('quickfort')
local real = qf.apply_blueprint
local calls = {}
qf.apply_blueprint = function(p)
  table.insert(calls, p.dry_run and 'dry' or 'real')
  local s = {zone_designated = {value = 1}, invalid_keys = {value = 0}}
  if mode == 'dry0' and p.dry_run then s.zone_designated.value = 0 end
  if mode == 'badkey' and p.dry_run then s.invalid_keys.value = 1 end
  if mode == 'real0' and not p.dry_run then s.zone_designated.value = 0 end
  if mode == 'error' then error('no quickfort') end
  return s
end
local ok, failed, res = B.qf_try('zone', {{x = 0, y = 0, text = 'm'}}, 70, 60, 60, mode == 'dryrun')
local ok2 = mode == 'badkey' and B.qf_try('zone', {{x = 0, y = 0, text = 'm'}}, 70, 60, 60, false, 1, true)
qf.apply_blueprint = real
return {ok = ok, failed = failed, calls = table.concat(calls, ','), res = type(res), ok2 = ok2}
"""


@test("qf_try: dry run then the real one; a refusal says which run refused; a dry run stops before the real one")
def _():
    r = LUA.execute(QF_SPY, B, "fine")
    assert r.ok and r.failed is None and r.calls == "dry,real", dict(r)
    r = LUA.execute(QF_SPY, B, "dryrun")
    assert r.ok and r.calls == "dry", dict(r)
    r = LUA.execute(QF_SPY, B, "dry0")
    assert not r.ok and r.failed == "dry" and r.calls == "dry", dict(r)
    r = LUA.execute(QF_SPY, B, "real0")
    assert not r.ok and r.failed == "run" and r.calls == "dry,real", dict(r)
    r = LUA.execute(QF_SPY, B, "error")
    assert not r.ok and r.failed == "dry" and r.res == "string", dict(r)
    # an unknown key refuses, unless loose (the bridge's and designate's way)
    r = LUA.execute(QF_SPY, B, "badkey")
    assert not r.ok and r.failed == "dry" and r.ok2, dict(r)


@test("item_held: forbidden, built in, dumped, a trader's... held; in a job is the caller's to say")
def _():
    held = LUA.eval("function(B, f) return B.item_held({flags = f}) and true or false end")
    assert not held(B, LUA.table_from({"in_job": True}))
    for flag in ("forbid", "in_building", "construction", "removed", "garbage_collect", "trader", "dump", "hostile"):
        assert held(B, LUA.table_from({flag: True})), flag
    assert not held(B, LUA.table())


@test("site_get / site_put: a missing or non-table record reads as {}")
def _():
    W.persist["k1"] = "junk"
    assert len(B.site_get("k1")) == 0 and len(B.site_get("k2")) == 0
    assert B.site_put("k3", LUA.table_from({"a": 1}))
    assert B.site_get("k3").a == 1


@test("workshop_name: DF's type, the AI's name for the soap maker's and the screw press, else Custom:<code>")
def _():
    r = LUA.execute("""local B = ...
      df = {workshop_type = {[0] = 'Carpenters', [1] = 'Custom'},
            building_def = {find = function(i) return {code = ({'SOAP_MAKERS', 'SCREW_PRESS', 'KILN2'})[i]} end}}
      local out = {B.workshop_name({type = 0}), B.workshop_name({type = 1, custom_type = 1}),
                   B.workshop_name({type = 1, custom_type = 2}), B.workshop_name({type = 1, custom_type = 3})}
      df = nil
      return table.concat(out, ',')""", B)
    assert r == "Carpenters,SoapMaker,ScrewPress,Custom:KILN2", r


def _cut(name):
    """Every search clock set to run out at once."""
    saved = {}
    for k in ("FARM_SEARCH_SECONDS", "PASTURE_SEARCH_SECONDS", "WELL_SEARCH_SECONDS", "SAND_SECONDS"):
        saved[k] = B[k]
        B[k] = -1
    return saved


def _uncut(saved):
    for k, v in saved.items():
        B[k] = v


@test("timed out: farm spots say 'search cut short' and timed_out, not 'nothing found'")
def _():
    s = _cut("farm")
    try:
        spots, why, cut = B.find_farm_spots(20, LUA.table(), False)
        r = B.farm_plots(LUA.table_from({"tiles": 20}), LUA.table_from({"year": 1, "tick": 1}), True)
    finally:
        _uncut(s)
    assert cut is True and len(spots) == 0, (cut, why)
    assert not r.ok and r.timed_out and "search cut short" in r.error, dict(r)
    # with time, the same fort is not cut short
    spots, why, cut = B.find_farm_spots(20, LUA.table(), False)
    assert not cut


@test("timed out: the outdoor pass's clock starts after surface_levels (it no longer eats the pass's time)")
def _():
    # a slow surface_levels: the outdoor pass still gets its own time (it searches, finds the soil)
    LUA.execute("""local B, W = ...
      for x = 40, 50 do for y = 40, 45 do W.set(x, y, 81, {shape = 'FLOOR', material = 'SOIL', outside = true}) end end
      REAL_SL = B.surface_levels
      B.surface_levels = function(area)
        local t = os.clock() + B.FARM_SEARCH_SECONDS + 0.05
        while os.clock() < t do end
        return {81}
      end""", B, W)
    real_wg = B.walk_group
    B.walk_group = LUA.eval("function(wg) return function(x, y, z) if z == 81 then return 1 end return wg(x, y, z) end end")(real_wg)
    saved = B.FARM_SEARCH_SECONDS
    B.FARM_SEARCH_SECONDS = 0.2
    try:
        spots, why, cut = B.find_farm_spots(9, LUA.table(), True)
    finally:
        B.FARM_SEARCH_SECONDS = saved
        B.walk_group = real_wg
        LUA.execute("local B = ...; B.surface_levels = REAL_SL", B)
    zs = [spots[i].z for i in range(1, len(spots) + 1)]
    assert 81 in zs and not cut, (zs, cut)


@test("timed out: pastures, wells, sand and surface spots say 'search cut short' and pass timed_out on")
def _():
    s = _cut("all")
    try:
        r, why, cut = B.find_pasture_rect(20, LUA.table())
        assert r is None and cut and why.startswith("search cut short"), why
        p = B.make_pasture(LUA.table_from({"tiles": 20}), True)
        assert not p.ok and p.timed_out and "search cut short" in p.error, dict(p)
        w, why, cut = B.find_well_spot(LUA.table())
        assert w is None and cut and why.startswith("search cut short"), why
        w, why, cut = B.find_sand_spot()
        assert w is None and cut and why.startswith("search cut short"), why
        r, why, cut = B.find_surface_rect(3, 3, 4, LUA.table())
        assert r is None and cut and why.startswith("search cut short"), why
    finally:
        _uncut(s)


@test("timed out: the cistern plan says 'search cut short' (and still 'ran out of time') with timed_out")
def _():
    LUA.execute("""local W = ...
      W.citizens = {}
      for i = 1, 20 do table.insert(W.citizens, {x = 50 + i % 10, y = 60, z = 80}) end
      for x = 112, 117 do for y = 55, 65 do W.set(x, y, 79, {shape = 'EMPTY', liquid = true, depth = 7}) end end
    """, W)
    saved = B.CISTERN_SECONDS
    B.CISTERN_SECONDS = -1
    try:
        plan, why, cut = B.plan_cistern(None, None, LUA.table_from({"tunnel": 70}))
    finally:
        B.CISTERN_SECONDS = saved
    assert plan is None and cut is True and why.startswith("search cut short") and "ran out of time" in why, why


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
