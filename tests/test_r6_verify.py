"""(r6 verify) Proof tests for what the r6 code-health round's own tests do not
cover: the modules run inside real DFHack, where reqscript keeps ONE env per
script and re-runs a script in that same env only when its own file's time
changes (dfhack.lua run_script_with_env: `local env = scripts[file].env`).

V1  A module that copies an ai-util helper into a local at load time
    (`local report_citizens = U.report_citizens`, 20 modules after c1) keeps
    what it read then. If the module is (re)loaded while the ai-util in the
    game is the previous one (delivery writes the files one at a time while
    the game runs: ai-benches..ai-noble-demands are written before ai-util;
    a write and its touch in the same whole second do not reload it again),
    the local is nil for good: the later reload of ai-util does not reach it.
    Before r6 the module's own copy looked up U.citizens on every call, so the
    same sequence worked. (The wrapper form c1 used elsewhere,
    `local function now_tick() return U.now_tick(0) end`, heals itself.)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except Exception:  # noqa: BLE001
    LuaRuntime = None

LUA_DIR = ROOT / "lua"


R6_MARK = "-- (r6 c1, code health)"
OLD_COPY = """local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end"""
CAPTURE = "local report_citizens = U.report_citizens"
WRAPPER = "local function report_citizens(...) return U.report_citizens(...) end"   # (r6 fix)


def _old_util(new_util: str) -> str | None:
    """ai-util.lua as before r6 (the one in the game while a delivery of r6
    is being written): the file without the r6 block at its end."""
    i = new_util.find(R6_MARK)
    if i < 0:
        return None
    return new_util[:new_util.rfind("\n-- =====", 0, i)] + "\n"


def _old_module(new_mod: str) -> str | None:
    """The module with its pre-r6 copy back in place of the captured local."""
    lines = new_mod.split("\n")
    for k, line in enumerate(lines):
        if line.startswith(CAPTURE) or line.startswith(WRAPPER):
            lines[k] = OLD_COPY
            return "\n".join(lines)
    return None


# A DFHack-like reqscript: one env per script, kept across reloads (as
# dfhack.lua does), a script run again in that env when "its file changes"
# (here: when the test hands it a new text).
FAKE_DFHACK = r"""
local G = {}
setmetatable(G, {__index = _G})
G.df = {global = {world = {units = {active = {}}}}}
G.dfhack = {units = {getCitizens = function() return {} end,
                     getReadableName = function(u) return 'Urist' end,
                     getNoblePositions = function() return nil end},
            onStateChange = {}}
local ENVS, TEXT = {}, {}
G.reqscript = function(n)
    local e = ENVS[n]
    if e == nil then
        e = setmetatable({}, {__index = G})
        ENVS[n] = e
        assert(load(TEXT[n], n, 't', e))()
    end
    return e
end
-- (re)load a script from a new text in its kept env, as DFHack does when the
-- file's time changes
local function reload(n, src)
    TEXT[n] = src
    local e = ENVS[n]
    if e == nil then e = setmetatable({}, {__index = G}); ENVS[n] = e end
    assert(load(src, n, 't', e))()
    return e
end
return reload
"""


def _sequence(module_name: str, module_src: str, old_util: str, new_util: str):
    """The delivery window: the game has the old ai-util loaded; the module's
    new file is loaded (against it); then the new ai-util is loaded (in its
    same env). Returns the module's env."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    reload = lua.execute(FAKE_DFHACK)
    reload("ai-util", old_util)
    M = reload(module_name[:-4], module_src)
    reload("ai-util", new_util)
    return lua, M


@test("V1: a module loaded while the previous ai-util is in the game works once the new ai-util loads "
      "(ai-noble-demands survey; fails: its report_citizens local was read as nil and stays nil)")
def _():
    if LuaRuntime is None:
        skip("lupa.lua53 not installed")
        return
    new_util = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
    new_mod = (LUA_DIR / "ai-noble-demands.lua").read_text(encoding="utf-8")
    old_util, old_mod = _old_util(new_util), _old_module(new_mod)
    assert old_util and "function report_citizens" not in old_util, "the r6 block was not found in ai-util"
    assert old_mod, "ai-noble-demands has neither the captured local nor the wrapper for report_citizens"
    # before r6: the same sequence works
    lua, M = _sequence("ai-noble-demands.lua", old_mod, old_util, new_util)
    ok_before = lua.eval("function(M) return pcall(M.survey, tostring) end")(M)
    assert ok_before, "control: the pre-r6 module should survive the delivery window"
    # after r6: the same sequence
    lua, M = _sequence("ai-noble-demands.lua", new_mod, old_util, new_util)
    ok, err = lua.eval("function(M) return pcall(M.survey, tostring) end")(M)
    assert ok, f"survey fails after ai-util reloaded: {err}"


@test("V1 fixed: no module captures a shared helper into a local at load (each looks it up when called)")
def _():
    import re
    bad = [f"{p.name}:{i + 1}" for p in sorted(LUA_DIR.glob("*.lua"))
           for i, l in enumerate(p.read_text(encoding="utf-8").split("\n"))
           if re.match(r"^local [A-Za-z_]+ = U\.(report_citizens|report_units|now_tick|name_of\w*|enum_\w+)\s*(--|$)", l)]
    assert not bad, bad


if __name__ == "__main__":
    finish()
