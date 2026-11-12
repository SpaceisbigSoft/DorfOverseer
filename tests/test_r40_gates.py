"""(0.105.40, 13e) lua/ai-gates.lua split into a hub and parts
(lua/ai-gates-<part>.lua), as ai-builder was: every name the one file had is
still reqscript('ai-gates').name, the parts load into the hub's environment
(from text in a test, from the files beside it in the game), and each carries
its version mark. Needs lupa.

    python tests/test_r40_gates.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"
from lua_modules_util import module_src, split_parts, with_util  # noqa: E402
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

BASE = "merge39"      # the round's base: ai-gates.lua still one file


def base_src() -> str | None:
    try:
        return subprocess.run(["git", "show", f"{BASE}:lua/ai-gates.lua"], cwd=ROOT, check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError):
        return None


BASE_SRC = base_src()

# the module loaded from text (as the tests do), its names listed
LOAD = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local names = {}
for k in pairs(env) do names[#names + 1] = k end
return env, names
"""


def names_of(src, lua):
    env, names = lua.execute(LOAD, src)
    return env, {names[i] for i in range(1, len(names) + 1)}


PARTS = split_parts("ai-gates.lua")
HUB = (LUA_DIR / "ai-gates.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"),
                    re.M).group(1)


@test("split: every ai-gates-<part>.lua beside the hub is in PARTS, in a load order")
def _():
    files = sorted(p.stem for p in LUA_DIR.glob("ai-gates-*.lua"))
    assert files == sorted(PARTS), (files, PARTS)
    assert len(PARTS) >= 5 and len(HUB.encode()) < 20000, (len(PARTS), len(HUB))
    # the save-aware wrappers capture the watcher's own arm/open_all/check/summary: last
    assert PARTS[-1] == "ai-gates-stuck", PARTS


@test("split: no part is a script of its own; each says it is ai-gates' and carries the version mark")
def _():
    for n in PARTS:
        src = (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")
        assert not re.search(r"^--@\s*module", src, re.M), n
        assert "A part of ai-gates" in src, n
        assert f"PART_VERSIONS['{n}'] = '{VERSION}'" in src, n
    assert f"PART_VERSIONS = {{['ai-gates'] = '{VERSION}'}}" in HUB


@test("split: every name the one-file ai-gates had is still the module's (and the parts' marks)")
def _():
    if BASE_SRC is None:
        return          # no git history here (a copy): nothing to compare with
    lua = LuaRuntime(unpack_returned_tuples=True)
    env_old, old = names_of(with_util(BASE_SRC, "ai-gates.lua"), lua)
    env, new = names_of(module_src("ai-gates.lua"), lua)
    assert old <= new, sorted(old - new)
    extra = new - old
    # the locals the parts share, the list of parts and their marks, the parts' texts (a test's)
    allowed = {"U", "key", "unkey", "STAIR_UP", "STAIR_DOWN", "ref_ids", "T", "interior", "moves", "treetop",
               "inside_or_courtyard", "seals", "ORTHO", "DOOR_GROUND", "WALL_GROUND", "open_ground",
               "citizen_starts", "gate_name", "pull", "set_entrance", "place", "entrance", "DAY_TICKS", "wgroup",
               "on_cavern_tile", "PARTS", "PART_VERSIONS", "PART_SOURCES",
               # (13e scan) the cheaper scan's helpers (tests/test_r40_gates_scan.py)
               "TK", "moves_k", "tile_is_ramp", "GAME_TILE", "porch_walk", "scan_map"}
    assert extra <= allowed, sorted(extra - allowed)
    marks = env.PART_VERSIONS
    assert {k for k in marks} == {"ai-gates", *PARTS}, list(marks)
    # the same kinds of value under every old name
    kind = lua.eval("function(e, k) return type(e[k]) end")
    for k in old:
        assert kind(env_old, k) == kind(env, k), k


@test("split: a swap on the hub (as the tests do) reaches the code in a part")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    seen = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-gates', 't', env))()
local seen = {n = 0}
env.tile = function(x, y, z) seen.n = seen.n + 1; return nil end
env.map_size = function() return 3, 3, 1 end
env.cache, env.edge_cache = {}, {}           -- (13e) the map's caches: module names the parts share
env.explore({{x = 1, y = 1, z = 0}})        -- ai-gates-scan, through T
return seen.n
""", module_src("ai-gates.lua"))
    assert seen > 0


@test("split: in the game the hub loads its parts from the files beside it (no PART_SOURCES)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    util = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
    env = lua.execute(r"""
local path, util = ...
local env = setmetatable({}, {__index = _G})
local u = setmetatable({}, {__index = env}); assert(load(util, 'ai-util', 't', u))()
env.reqscript = function(n) if n == 'ai-util' then return u end error('reqscript ' .. n) end
env.dfhack = {}            -- no findScript: the parts must come from the hub's own folder
assert(loadfile(path, 't', env))()
return env
""", str(LUA_DIR / "ai-gates.lua"), util)
    for fn in ("scan", "find_entrances", "check", "arm", "fortify", "link_lever", "build_wings", "summary",
               "gates_persist", "stranded_citizens", "unstick_gate", "free_gate_jobs"):
        assert lua.eval("type")(env[fn]) == "function", fn
    assert len(list(env.PART_VERSIONS)) == len(PARTS) + 1
    # the save-aware wrappers (stuck) call the watcher's own (watch)
    assert env.GATES_ORIG.arm is not env.arm and env.GATES_ORIG.summary is not env.summary


@test("split: each part compiles on its own (Lua 5.3)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for n in ["ai-gates", *PARTS]:
        ok = chk((LUA_DIR / f"{n}.lua").read_text(encoding="utf-8"), n)
        assert ok[0], (n, ok)


if __name__ == "__main__":
    finish()
