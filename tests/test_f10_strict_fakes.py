"""(F1b) Strict df fakes (tests/strict_fakes.py) and their data
(tests/fixtures/df_fields_53_17.json, brain/tools/gen_df_fields.py), and
tools/refresh_real_fixtures.py.

The Lua part runs on lupa (the PC) or, without it, on texlua (Lua 5.3) when
that is installed; else it is skipped.

    python tests/test_f10_strict_fakes.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, skip  # noqa: E402
import strict_fakes as S  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
import refresh_real_fixtures as R  # noqa: E402

NAMES = json.loads((ROOT / "tests" / "fixtures" / "df-names.json").read_text(encoding="utf-8"))


@test("df fields: the tag of df-names.json; the roots there; item, unit, building agree with df-names.json")
def _():
    d = S.data()
    assert d["tag"] == NAMES["tag"], (d["tag"], NAMES["tag"])
    for r in d["roots"]:
        assert r in d["types"], r
    for n in ("item", "unit", "building", "building_actual", "job"):
        mine, theirs = set(d["types"][n]["f"]), set(NAMES["types"][n].get("f", {}))
        assert not theirs or mine == theirs, (n, mine ^ theirs)


@test("df fields: the bugs the hand-written fakes missed are told apart (forbid, fish and egg mat_type)")
def _():
    assert S.known("item_flags", "forbid") and not S.known("item_flags", "forbidden")
    assert not S.known("item_fishst", "mat_type") and not S.known("item_eggst", "mat_type")
    assert S.known("item_plantst", "mat_type") and S.known("item_foodst", "mat_type")   # item_crafted's
    for m in ("getStackSize", "getActualMaterial", "getActualMaterialIndex", "getSubtype", "getType"):
        assert S.known("item_fishst", m), m                                               # item's vmethods
    assert S.known("unit", "flags1") and S.known("unit_flags1", "caged") and S.known("unit", "pos")
    assert S.fields("unit")["pos"] == "coord" and S.fields("item")["flags"] == "item_flags"
    assert S.known("building_tradedepotst", "contained_items") and S.known("building_tradedepotst", "getBuildStage")
    assert S.known("item", "_type") and S.known("item_flags", "whole") and not S.known("item", "whole")


LUA_CHECK = r"""
local out = {}
local function try(f) local ok, e = pcall(f); return ok and 'ok' or (tostring(e):gsub('^[^\n]-:%d+: ', '', 1)) end
local fish = strict('item_fishst', {flags = {}, race = 3, pos = {x = 1, y = 2, z = 3}})
out[#out + 1] = tostring(fish.race) .. ' ' .. tostring(fish.flags.forbid) .. ' ' .. tostring(fish.caste)
out[#out + 1] = strict_type(fish) .. ' ' .. strict_type(fish.flags) .. ' ' .. strict_type(fish.pos)
out[#out + 1] = try(function() return fish.mat_type end)
out[#out + 1] = try(function() return fish.flags.forbidden end)
out[#out + 1] = try(function() fish.made_up = 1 end)
out[#out + 1] = try(function() return strict('item_foodst', {v = 3}) end)
local food = strict('item_foodst', {mat_type = 5})
function food:getStackSize() return 4 end
out[#out + 1] = tostring(food.mat_type) .. ' ' .. tostring(food.stack_size) .. ' ' .. food:getStackSize()
out[#out + 1] = try(function() function food:getMadeUp() end end)
local u = strict('unit', {flags1 = {caged = true}, id = 7})
out[#out + 1] = tostring(u.flags1.caged) .. ' ' .. tostring(u.flags1.chained) .. ' ' .. try(function() return u.flags1.cagedd end)
out[#out + 1] = try(function() return strict('no_such_type', {}) end)
return table.concat(out, '\n')
"""

EXPECT = [
    "3 false nil",
    "item_fishst item_flags coord",
    "Cannot read field item_fishst.mat_type: not found.",
    "Cannot read field item_flags.forbidden: not found.",
    "Cannot write field item_fishst.made_up: not found.",
    "strict: the item_foodst fake has a field 'v' DFHack's item_foodst has not (keep test scaffolding in a side table)",
    "5 nil 4",
    "Cannot write field item_foodst.getMadeUp: not found.",
    "true false Cannot read field unit_flags1.cagedd: not found.",
    "strict: no df type no_such_type",
]


def run_lua() -> str:
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        LuaRuntime = None
    if LuaRuntime is not None:
        lua = LuaRuntime(unpack_returned_tuples=True)
        return lua.execute(S.lua_source() + LUA_CHECK)
    texlua = shutil.which("texlua")
    if not texlua:
        skip("needs lupa (pip install lupa) or texlua")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "check.lua"
        p.write_text(S.lua_source() + "print((function()\n" + LUA_CHECK + "\nend)())\n", encoding="utf-8")
        r = subprocess.run([texlua, str(p)], capture_output=True, text=True, cwd=d, timeout=60)
        assert r.returncode == 0, r.stderr
        return r.stdout.rstrip("\n")


@test("strict fakes (Lua): unknown fields raise as DFHack does; known ones read nil/false; nested tables typed")
def _():
    got = run_lua().split("\n")
    assert got == EXPECT, "\n".join(f"{'  ' if a == b else '!!'} {a!r} / {b!r}" for a, b in zip(got, EXPECT))


@test("strict fakes: the Lua source of every type compiles (names only, no odd characters)")
def _():
    src = S.lua_types()
    assert src.startswith("{") and '["item_fishst"]' in src and src.count("\n") == len(S.data()["types"]) + 1


@test("refresh_real_fixtures: copies a fort's state.json under its letter; skips a missing or broken one")
def _():
    real = sorted((ROOT / "tests" / "fixtures" / "real").glob("*.json"))
    if not real:
        skip("no real fixture to copy")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        g = d / "game A" / R.REL
        g.parent.mkdir(parents=True)
        shutil.copy(real[0], g)
        bad = d / "game C" / R.REL
        bad.parent.mkdir(parents=True)
        bad.write_text("{not json", encoding="utf-8")
        out = d / "out"
        rc = R.main([f"A={d / 'game A'}", f"B={d / 'none'}", f"C={d / 'game C'}", "--out", str(out)])
        files = [p.name for p in out.glob("*.json")]
        s = json.loads(real[0].read_text(encoding="utf-8"))
        assert rc == 0 and files == [R.fixture_name("A", s)], files
        assert files[0].startswith("a-") and f"-y{s['date']['year']}-" in files[0]
        assert json.loads((out / files[0]).read_text(encoding="utf-8")) == s
        # a DF-AI folder's config.json names the game by its exe
        cfgdir = d / "DF-AI-B"
        cfgdir.mkdir()
        (cfgdir / "config.json").write_text(json.dumps({"df_launch": str(d / "game A" / "Dwarf Fortress.exe")}))
        assert R.from_config(cfgdir) == d / "game A"
    assert R.DEFAULT_GAMES["A"].endswith("Dwarf Fortress") and R.DEFAULT_GAMES["D"] == r"D:\DF-D"


if __name__ == "__main__":
    finish()
