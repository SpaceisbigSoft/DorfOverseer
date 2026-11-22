"""(r5 p5) Behaviour checks for the bridge's wiring, in place of tests that
read lua/ai-bridge*.lua and look for a line of its text.

The bridge hub (lua/ai-bridge.lua, its parts loaded from the files beside it)
runs on tests/test_hygiene_bridge.py's stub DFHack (read from that file, not
copied). A module the bridge asks for with reqscript is a stand-in that
records what it was called with, so a test says what the bridge DOES:

    section(name, module, fn)   SECTIONS[name] asks module.fn and hands its answer
                                on; a module that raises is that section's {error}
    forwarded(action, a, module, fn)
                                ACTIONS[action](a) calls module.fn: the arguments it
                                passed (Lua values turned into Python ones)

A refactor that keeps the behaviour (a local renamed, a line split, an
argument taken from another place) keeps these green; text asserts broke on
every such change (tests/test_r5_p5.py).

Not a test file itself (run_all runs test_*.py only).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LUA_DIR = ROOT / "lua"

try:
    from lupa.lua53 import LuaRuntime
except ImportError:                    # the callers skip (need_lua) before they ask
    LuaRuntime = None

_STATE: dict = {}


def _boot():
    if "H" not in _STATE:
        if LuaRuntime is None:
            from harness import skip
            skip("needs the lupa package (pip install lupa)")
        hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
        harness = re.search(r'HARNESS = r"""(.*?)"""', hyg, re.S).group(1)
        lua = LuaRuntime(unpack_returned_tuples=True)
        _STATE["LUA"] = lua
        _STATE["H"] = lua.execute(harness, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
        _STATE["rec"] = lua.eval("""function(log, answer, raise)
            return setmetatable({}, {__index = function(_, k)
                return function(...)
                    table.insert(log, {name = k, n = select('#', ...), args = table.pack(...)})
                    if raise then error('stand-in ' .. k .. ' broke') end
                    if type(answer) == 'function' then return answer(k, ...) end
                    return answer
                end
            end})
        end""")
    return _STATE["LUA"], _STATE["H"]


def lua():
    return _boot()[0]


def to_lua(v):
    L = lua()
    if isinstance(v, dict):
        return L.table_from({k: to_lua(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return L.table_from([to_lua(x) for x in v])
    return v


def to_py(v, depth=0):
    L = lua()
    if depth > 6 or L.eval("type")(v) != "table":
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [to_py(v[k], depth + 1) for k in sorted(keys)]
    return {k: to_py(v[k], depth + 1) for k in keys}


def hub(modules=None):
    """A fresh hub env; modules: {script name: Lua value} answered by reqscript."""
    L, H = _boot()
    H.scripts = L.table()
    H.halted = False
    for name, mod in (modules or {}).items():
        H.scripts[name] = mod
    return H.module()


def stand_in(answer=None, raise_=False):
    """A module whose every function records its call in .log and answers `answer`
    (a Lua value, or a Lua function(name, ...) giving the answer)."""
    L = lua()
    log = L.table()
    return _STATE["rec"](log, answer, raise_), log


def calls(log, name=None):
    """The calls a stand-in saw: [(name, [args...])], nil arguments kept as None."""
    out = []
    for i in range(1, len(log) + 1):
        c = log[i]
        if name is None or c.name == name:
            out.append((c.name, [to_py(c.args[j]) for j in range(1, int(c.n) + 1)]))
    return out


def section(name, module, fn="report", ctx=None, extra=None):
    """SECTIONS[name] on a hub where `module` is a stand-in: (its answer when the
    module answers a marker, the calls made, its answer when the module raises)."""
    L = lua()
    marker = L.table_from({"marker": "r5p5"})
    mod, log = stand_in(marker)
    env = hub(dict({module: mod}, **(extra or {})))
    got = env.SECTIONS[name](to_lua(ctx) if ctx is not None else None)
    seen = [c for c in calls(log) if c[0] == fn]
    bad, _ = stand_in(None, raise_=True)
    env2 = hub(dict({module: bad}, **(extra or {})))
    broke = env2.SECTIONS[name](to_lua(ctx) if ctx is not None else None)
    return got, seen, broke, env


def section_answers(name, module, fn="report", ctx=None, extra=None):
    """The common check: the section hands on the module's own answer, made by fn,
    and a module that raises leaves the section an {error} (the rest of the report
    stands). Returns the arguments fn was given (for the callers' own checks)."""
    got, seen, broke, env = section(name, module, fn, ctx, extra)
    assert seen, (name, "never asked", module, fn)
    assert got is not None and got["marker"] == "r5p5", (name, to_py(got))
    assert broke is not None and "stand-in" in str(broke["error"]), (name, to_py(broke))
    return seen[0][1], env


def forwarded(action, a, module, fn=None, answer=None, extra=None, fields=None):
    """ACTIONS[action](a) on a hub where `module` is a stand-in (with `fields` set on it as
    plain values: a table the handler reads): (the calls it made [(fn, args)], the action's
    answer, the hub env)."""
    L = lua()
    mod, log = stand_in(answer if answer is not None else L.table_from({"ok": True, "stand_in": True}))
    for k, v in (fields or {}).items():
        mod[k] = to_lua(v)
    env = hub(dict({module: mod}, **(extra or {})))
    handler = env.ACTIONS[action]
    assert handler is not None, ("no such action", action)
    out = handler(to_lua(a))
    return calls(log, fn), out, env


def txt_fn(env):
    """The hub's own txt (what a section passes its module to make text safe)."""
    return env.txt


def same(a, b) -> bool:
    """Lua's rawequal: the very same function or table."""
    return bool(lua().eval("rawequal")(a, b))


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def wired(section=None, module=None, fn="report", txt=None, ctx=None, actions=(), dry=(), pulse=None,
          cache_days=None, modules=(), invalidates=None, release=None, handlers=(), uncached=False):
    """The bridge's wiring read from the loaded hub's own tables, not its text:
    a section that asks module.fn (txt=True: given the hub's txt first) and is
    safe; actions that are ACTIONS handlers; dry runs on DRY_OK; the section in
    PULSE_SECTIONS or not (pulse True/False); its SECTION_CACHE_DAYS; modules
    in BRIDGE_MODULES; CACHE_INVALIDATES {action: [sections]}; RELEASE_WHILE_HALTED
    {action: mode}; handlers: actions whose ACTIONS entry is the part's act_<name>;
    uncached: the section is in no SECTION_CACHE_DAYS. Returns the hub env."""
    env = hub()
    if section is not None:
        args, env2 = section_answers(section, module, fn, ctx)
        if txt is not None:
            assert bool(args) and same(args[0], env2.txt) == txt, (section, "txt", args)
    for a in actions:
        assert lua().eval("type")(env.ACTIONS[a]) == "function", ("not an action", a)
    for a in dry:
        assert env.DRY_OK[a] is True, ("no dry run", a)
    for a in handlers:
        assert lua().eval("type")(env["act_" + a]) == "function" and same(env.ACTIONS[a], env["act_" + a]), \
            ("ACTIONS." + a + " is not act_" + a)
    if uncached:
        assert env.SECTION_CACHE_DAYS[section] is None, (section, "cached", env.SECTION_CACHE_DAYS[section])
    if pulse is not None:
        assert (section in lua_list(env.PULSE_SECTIONS)) == pulse, (section, "pulse", lua_list(env.PULSE_SECTIONS))
    if cache_days is not None:
        assert env.SECTION_CACHE_DAYS[section] == cache_days, (section, env.SECTION_CACHE_DAYS[section])
    listed = lua_list(env.BRIDGE_MODULES)
    for m in modules:
        assert m in listed, ("not in BRIDGE_MODULES", m)
    for a, secs in (invalidates or {}).items():
        got = lua_list(env.CACHE_INVALIDATES[a])
        assert all(s in got for s in secs), (a, got)
    for a, mode in (release or {}).items():
        assert env.RELEASE_WHILE_HALTED[a] == mode, (a, env.RELEASE_WHILE_HALTED[a])
    return env


def real_module(name):
    """lua/<name>.lua loaded as a module (a pure one: ai-layouts and the like), for a hub
    whose handler reads its tables."""
    L = lua()
    from lua_modules_util import SPLIT, module_src
    if ("mod", name) not in _STATE:
        _STATE[("mod", name)] = L.execute("""local src, name = ...
            local env = setmetatable({dfhack_flags = {module = true}}, {__index = _G})
            env.reqscript = function(n) error('no ' .. n .. ' for ' .. name) end
            assert(load(src, name, 't', env))()
            return env""", module_src(f"{name}.lua") if f"{name}.lua" in SPLIT     # (r9) a split hub: its parts' texts too
            else (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8"), name)
    return _STATE[("mod", name)]
