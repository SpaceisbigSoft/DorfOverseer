"""Tests for lua/ai-water.lua (the water survey) on fake map blocks, and the
planner's water notes (pip install lupa).

    python tests/test_water.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = (ROOT / "lua" / "ai-water.lua").read_text(encoding="utf-8")
FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local blocks = {}
local function blk(bx, by, bz)
  local k = bx .. ',' .. by .. ',' .. bz
  if not blocks[k] then
    local des, tt = {}, {}
    for x = 0, 15 do des[x] = {}; tt[x] = {}
      for y = 0, 15 do des[x][y] = {flow_size = 0, hidden = false}; tt[x][y] = 1 end end
    blocks[k] = {designation = des, tiletype = tt}
  end
  return blocks[k]
end
function env.WATER(x, y, z, fields)
  local b = blk(x // 16, y // 16, z)
  local d = b.designation[x % 16][y % 16]
  for k, v in pairs(fields) do d[k] = v end
  if fields.river then b.tiletype[x % 16][y % 16] = 2 end
end
env.df = {tiletype = {attrs = {[1] = {material = 1}, [2] = {material = 2}}},
          tiletype_material = {[1] = 'STONE', [2] = 'RIVER'}}
env.SAVED = {}
env.dfhack = {
  units = {getCitizens = function() return {{p = {50, 50, 100}}, {p = {52, 50, 102}}} end,
           getPosition = function(u) return u.p[1], u.p[2], u.p[3] end},
  maps = {getTileSize = function() return 192, 192, 200 end,
          getBlock = function(bx, by, bz) return blocks[bx .. ',' .. by .. ',' .. bz] end},
  persistent = {saveSiteData = function(k, v) env.SAVED[k] = v end,
                getSiteData = function(k, d) return env.SAVED[k] or d end},
}
assert(load(src, 'ai-water', 't', env))()
return env
"""


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def fields(**kw):
    return LUA.table_from(kw)


LUA = LuaRuntime(unpack_returned_tuples=True)


@test("water survey: a river, a surface pond, cavern water, an aquifer and magma, each by kind; saved")
def _():
    env = LUA.execute(FAKE, SRC)
    for x in range(40, 46):                                   # a river on the surface
        env.WATER(x, 60, 108, fields(flow_size=7, outside=True, river=True))
    env.WATER(60, 50, 106, fields(flow_size=3, outside=True, water_stagnant=True))   # a pond
    for x in range(50, 54):                                   # a cavern lake far down
        env.WATER(x, 52, 40, fields(flow_size=6, feature_local=True, hidden=True))
    env.WATER(51, 51, 90, fields(water_table=True))           # aquifer wall
    env.WATER(51, 52, 30, fields(flow_size=7, liquid_type=True))   # magma
    r = env.scan(1234)
    assert r.ok and r.tick == 1234 and env.SAVED["ai-overseer/water"] is not None
    kinds = {b.kind: b for b in r.bodies.values()}
    assert set(kinds) == {"river", "surface", "cavern"}, set(kinds)
    assert kinds["river"].tiles == 6 and kinds["river"].volume == 42 and kinds["river"].deep == 6
    assert kinds["surface"].stagnant_share == 100
    assert kinds["cavern"].seen_share == 0 and kinds["cavern"].z1 == 40
    assert r.aquifer.z1 == 90 and r.magma.tiles == 1
    assert env.last().tick == 1234


@test("water survey in slices: no call scans past its time; the finished survey is the same as all at once")
def _():
    env = LUA.execute(FAKE, SRC)
    for x in range(40, 46):
        env.WATER(x, 60, 108, fields(flow_size=7, outside=True, river=True))
    for x in range(50, 54):
        env.WATER(x, 52, 40, fields(flow_size=6, feature_local=True, hidden=True))
    whole = env.survey()
    calls, r = 0, None
    while True:
        calls += 1
        r = env.scan_step(99, 0)           # no time at all: one level a call
        if r.done:
            break
        assert env.scanning() and r.left > 0
    assert calls > 10 and not env.scanning() and r.tick == 99
    a = {b.kind: (b.tiles, b.volume) for b in whole.bodies.values()}
    b = {b.kind: (b.tiles, b.volume) for b in r.bodies.values()}
    assert a == b, (a, b)


@test("water summary: the planner's line, and a survey proposed when none or a season old")
def _():
    from planner import water_summary, _water_rules, PLANNER_CONFIG
    w = {"tick": 0, "bodies": [{"kind": "cavern", "tiles": 4, "salt_share": 0, "stagnant_share": 0,
                                "seen_share": 0, "nearest": {"d": 120, "z": 40}}],
         "aquifer": {"z1": 90, "z2": 92}}
    line = water_summary(w, -100)
    assert "cavern water (4 tiles, 0% seen, nearest 120 tiles away at elevation -60)" in line, line
    assert "aquifer at elevations -10--8" in line, line
    s = {"water": {"none": True}, "date": {"year": 50, "tick": 0}}
    props, notes = [], []
    _water_rules(s, PLANNER_CONFIG, props, notes)
    # (0.105.3) the cistern's tunnel reach rides on the survey
    assert props and props[0].action == {"type": "survey_water", "tunnel": 70} and not notes
    s["water"] = dict(w, tick=50 * 403200)
    props, notes = [], []
    _water_rules(s, PLANNER_CONFIG, props, notes)
    assert not props and notes and notes[0].startswith("water near the fort:"), (props, notes)


@test("magma (0.104.96): beneath a cavern -> said so (a risk left to the agent); no cavern between -> open")
def _():
    from planner import magma_access, water_summary
    w = {"magma": {"z1": 115, "z2": 135, "tiles": 2}}
    m = {"dwarves": {"z_bottom": 159}, "layers": [{"name": "Cavern1", "z_top": 143, "z_bottom": 136},
                                                   {"name": "MagmaSea", "z_top": 18, "z_bottom": 14}]}
    assert magma_access(w, m) == "cavern:Cavern1"
    m["layers"][0].update(z_bottom=135)                                # (0.104.98) the magma pool in the cavern's floor level
    assert magma_access(w, m) == "cavern:Cavern1"
    assert "reaching it opens the cavern" in water_summary(w, -128, m)
    m["layers"][0].update(z_top=100, z_bottom=90)                      # the cavern deeper than the magma
    assert magma_access(w, m) == "open" and "no cavern between" in water_summary(w, -128, m)
    assert magma_access({}, m) is None and magma_access(w, {}) is None


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
