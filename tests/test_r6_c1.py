"""(r6 c1, code health) The Lua helper copies (report_citizens, report_units,
now_tick, name_of, enum_name) moved into lua/ai-util.lua.

Proves: no module (but ai-bridge-report / ai-bridge-actions, c3's) keeps a
copy of its own beyond a one-line call into ai-util, except the few kept on
purpose (a module that takes no ai-util at load); every variant the modules
had gives, through ai-util, what the old copy gave on the same inputs (the
same value, or an error where it threw); the copies kept local agree with
ai-util's rule; and the modules changed still load.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except Exception:  # noqa: BLE001
    try:
        from lupa import LuaRuntime
    except Exception:  # noqa: BLE001
        LuaRuntime = None

LUA_DIR = ROOT / "lua"
NAMES = ("report_citizens", "report_units", "now_tick", "name_of", "enum_name")
C3 = ("ai-bridge-report.lua", "ai-bridge-actions.lua")
# kept local on purpose, each with an (r6) comment saying why
KEPT = {("ai-builder.lua", "now_tick"), ("ai-well-safety.lua", "now_tick"),
        ("ai-bans.lua", "enum_name"), ("ai-threat-facts.lua", "enum_name"),
        ("ai-missions.lua", "enum_name"), ("ai-missions.lua", "name_of"),
        ("ai-raids.lua", "enum_name"), ("ai-raids.lua", "name_of")}
DEF = re.compile(r"^(local\s+)?function\s+(%s)\b(.*)$|^local\s+(%s)\s*=\s*(.*)$" % ("|".join(NAMES), "|".join(NAMES)),
                 re.M)


def module_defs():
    out = []
    for p in sorted(LUA_DIR.glob("*.lua")):
        if p.name in C3 or p.name == "ai-util.lua":
            continue
        for m in DEF.finditer(p.read_text(encoding="utf-8")):
            out.append((p.name, m.group(2) or m.group(4), m.group(0)))
    return out


@test("no module keeps its own copy: each definition is one line into ai-util (U.), or one of the kept few")
def _():
    defs = module_defs()
    assert len(defs) >= 60, len(defs)
    seen_kept = set()
    for f, name, line in defs:
        if (f, name) in KEPT:
            seen_kept.add((f, name))
            src = (LUA_DIR / f).read_text(encoding="utf-8")
            i = src.index(line)
            assert "(r6) kept here" in src[max(0, i - 1200):i], (f, name)
            continue
        assert "U." in line and (line.rstrip().split("--")[0].rstrip().endswith("end") or line.startswith("local " + name)), \
            (f, line)
        assert "pcall" not in line and "getReadableName" not in line and "getCitizens" not in line, (f, line)
    assert seen_kept == KEPT, KEPT - seen_kept


@test("ai-util has the helpers, once each, in the marked block")
def _():
    src = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
    assert "(r6 c1, code health)" in src
    for n in ("report_citizens", "report_units", "now_tick", "name_of", "name_of_raw", "name_of_then",
              "name_of_conv", "enum_name", "enum_name_num", "enum_value", "enum_text"):
        assert len(re.findall(r"^function %s\(" % n, src, re.M)) == 1, n


# ---------------------------------------------------------------------------
# The old copies (0.105.61), word for word, against ai-util's on the same inputs

OLD = {
    "rc": """function(...) if U.REPORT_CTX and U.citizens then return U.citizens(...) end
             return dfhack.units.getCitizens(...) end""",
    "rc_true": """function() if U.REPORT_CTX and U.citizens then return U.citizens(true) end
             return dfhack.units.getCitizens(true) end""",
    "ru": """function() if U.REPORT_CTX and U.units_active then return U.units_active() end
             return df.global.world.units.active end""",
    "nt0": "function() local ok, t = pcall(U.abs_tick) return ok and t or 0 end",
    "ntnil": "function() local ok, t = pcall(U.abs_tick) return ok and t or nil end",
    "ntnum": "function() local ok, t = pcall(U.abs_tick) return ok and type(t) == 'number' and t or nil end",
    "ntint": "function() local ok, t = pcall(function() return U.abs_tick() end) return ok and math.tointeger(t) or 0 end",
    "ntdf": "function() local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end) "
            "return ok and t or 0 end",
    "n_camera": """function(u) local ok, n = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
             return ok and n or 'a dwarf' end""",
    "n_v2": """function(u, txt) local ok, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
             return ok and n or ('unit ' .. tostring(u.id)) end""",
    "n_raw": "function(u, txt) return (txt or tostring)(dfhack.units.getReadableName(u)) end",
    "n_then": """function(u, txt) local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
             n = ok and n or ('unit ' .. tostring(u.id)) return txt and txt(n) or n end""",
    "n_conv": """function(u) local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
             return ok and TXT(n) or ('unit ' .. tostring(u.id)) end""",
    "n_siege": """function(u, txt) local ok, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
             return ok and n or ('#' .. tostring(u.id)) end""",
    "n_welfare": """function(u) local ok, n = pcall(function() return TXT(dfhack.units.getReadableName(u)) end)
             return ok and n or ('unit ' .. tostring(u and u.id)) end""",
    "e1": """function(enum, v) if v == nil then return nil end local ok, n = pcall(function() return enum[v] end)
             if ok and type(n) == 'string' then return n end return nil end""",
    "e2": """function(enum, v) if v == nil then return nil end local ok, n = pcall(function() return enum[v] end)
             if ok and type(n) == 'string' then return n end return tonumber(v) and tostring(v) or nil end""",
    "e_homes": "function(enum, v) local ok, n = pcall(function() return enum[v] end) return ok and n or nil end",
    "e_killers": """function(enum, v) local ok, n = pcall(function() return enum[v] end)
             if ok and n ~= nil then return tostring(n) end return tostring(v) end""",
    "e_send": """function(enum, v) if v == nil or enum == nil then return nil end local ok, n = pcall(function() return enum[v] end)
             if ok and type(n) == 'string' then return n end return nil end""",
}
# the modules' new one-liners (as written in them), over the same U
NEW = {
    "rc": "U.report_citizens", "rc_true": "function() return U.report_citizens(true) end",
    "ru": "U.report_units",
    "nt0": "function() return U.now_tick(0) end", "ntnil": "function() return U.now_tick(nil) end",
    "ntnum": "function() return U.now_tick(nil, true) end", "ntint": "function() return U.now_tick(0, false, true) end",
    "ntdf": "function() return U.now_tick(0) end",   # (the same reading: builder and well-safety keep theirs)
    "n_camera": "function(u) return U.name_of(u, function(s) return dfhack.df2utf(s) end, 'a dwarf') end",
    "n_v2": "function(u, txt) return U.name_of(u, txt) end",
    "n_raw": "function(u, txt) return U.name_of_raw(u, txt) end",
    "n_then": "function(u, txt) return U.name_of_then(u, txt) end",
    "n_conv": "function(u) return U.name_of_conv(u, TXT) end",
    "n_siege": "function(u, txt) return U.name_of(u, txt, function(u) return '#' .. tostring(u.id) end) end",
    "n_welfare": "function(u) return U.name_of(u, TXT, function(u) return 'unit ' .. tostring(u and u.id) end) end",
    "e1": "function(e, v) return U.enum_name(e, v) end", "e2": "function(e, v) return U.enum_name_num(e, v) end",
    "e_homes": "function(e, v) return U.enum_value(e, v) end", "e_killers": "function(e, v) return U.enum_text(e, v) end",
    "e_send": "function(e, v) return U.enum_name(e, v) end",
}

FAKE = r"""
local util_src, old, new = ...
local W = {names = {}, cits = 0, year = 3, tick = 77}
local env = setmetatable({}, {__index = _G})
env.dfhack = {units = {getReadableName = function(u)
                           local n = W.names[u and u.id]
                           if n == 'ERR' then error('no name') end
                           return n end,
                       getCitizens = function(...) W.cits = W.cits + 1; return {n = select('#', ...), a = (...)} end},
              df2utf = function(s) if s == 'BAD' then error('bad utf') end return 'u:' .. tostring(s) end}
env.df = {global = {world = {units = {active = {'a1', 'a2'}}}}}
setmetatable(env.df.global, {__index = function(_, k)
    if k == 'cur_year' then return W.year elseif k == 'cur_year_tick' then return W.tick end end})
assert(load(util_src, 'ai-util', 't', env))()
local fenv = setmetatable({U = env, TXT = function(s) if s == 'X' then return nil end return '<' .. tostring(s) .. '>' end},
                          {__index = env})
local O, N = {}, {}
for k, s in pairs(old) do O[k] = assert(load('return ' .. s, 'old ' .. k, 't', fenv))() end
for k, s in pairs(new) do N[k] = assert(load('return ' .. s, 'new ' .. k, 't', fenv))() end
local function show(v, d)
    d = d or 0
    if type(v) ~= 'table' or d > 2 then return type(v) .. ':' .. tostring(v) end
    local o = {}
    for k, x in pairs(v) do o[#o + 1] = tostring(k) .. '=' .. show(x, d + 1) end
    table.sort(o)
    return '{' .. table.concat(o, ',') .. '}'
end
-- one call: "ok:<value>" or "err"
local function call(f, ...)
    local r = table.pack(pcall(f, ...))
    if not r[1] then return 'err' end
    local o = {}
    for i = 2, math.max(r.n, 2) do o[#o + 1] = show(r[i]) end
    return 'ok:' .. table.concat(o, '|')
end
return {W = W, U = env, O = O, N = N, call = call}
"""


def runtime():
    lua = LuaRuntime(unpack_returned_tuples=True)
    T = lua.table_from
    R = lua.execute(FAKE, (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8"), T(OLD), T(NEW))
    return lua, R


def same(lua, R, key, args_list, setup=None):
    for args in args_list:
        if setup:
            setup()
        o = R.call(R.O[key], *args)
        if setup:
            setup()
        n = R.call(R.N[key], *args)
        assert o == n, (key, args, o, n)


if LuaRuntime is not None:
    @test("report_citizens / report_units: the same lists, inside a report (its one walk) and outside; captives' (true)")
    def _():
        lua, R = runtime()
        for ctx in (False, True):
            if ctx:
                R.U.report_begin(None)
            same(lua, R, "rc", [(), (True,), (True, False)])
            same(lua, R, "rc_true", [(), (False,)])
            same(lua, R, "ru", [()])
            if ctx:
                R.U.report_end()
        # inside a report the citizens are asked once per set of arguments, through ai-util's
        R.W.cits = 0
        R.U.report_begin(None)
        R.N.rc(True); R.N.rc(True); R.N.rc_true()
        R.U.report_end()
        assert R.W.cits == 1, R.W.cits

    @test("now_tick: every variant as it was (0 / nil / number only / integer), the date read or not")
    def _():
        lua, R = runtime()
        cases = [(3, 77), (None, 5), (2, 1.5), (2.0, 4.0), ("x", 1)]
        for key in ("nt0", "ntnil", "ntnum", "ntint", "ntdf"):
            for y, t in cases:
                def setup(y=y, t=t):
                    R.W.year, R.W.tick = y, t
                same(lua, R, key, [()], setup)
        # ai-util's abs_tick swapped (as a test may): the protected variants follow it, as before
        saved = R.U.abs_tick
        for fake in ("function() return nil end", "function() return 'soon' end", "function() return 7.0 end",
                     "function() error('no world') end"):
            R.U.abs_tick = lua.eval(fake)
            for key in ("nt0", "ntnil", "ntnum", "ntint"):
                same(lua, R, key, [()])
        R.U.abs_tick = saved

    @test("name_of: every variant as it was (protected or not, the conversion, the fallback text)")
    def _():
        lua, R = runtime()
        T = lua.table_from
        R.W.names = T({1: "Urist", 2: "ERR", 3: "BAD", 4: "X"})
        units = [T({"id": i}) for i in (1, 2, 3, 4, 5)]
        convs = [None, lua.eval("function(s) return 'c:' .. tostring(s) end"), lua.eval("function() return nil end"),
                 lua.eval("function() error('conv') end"), lua.eval("function(s) return dfhack.df2utf(s) end")]
        for key in ("n_camera", "n_conv", "n_welfare"):
            same(lua, R, key, [(u,) for u in units] + [(None,)])
        for key in ("n_v2", "n_raw", "n_then", "n_siege"):
            same(lua, R, key, [(u, c) for u in units for c in convs] + [(None, None)])

    @test("enum_name: every variant as it was (names, numbers, nil, no enum, a throwing enum)")
    def _():
        lua, R = runtime()
        enums = [lua.eval("{[0] = 'NONE', [1] = 'DWARF', [2] = 5, [3] = false}"), None,
                 lua.eval("setmetatable({}, {__index = function() error('bad') end})")]
        vals = [0, 1, 2, 3, 9, "1", "x", None]
        for key in ("e1", "e2", "e_homes", "e_killers", "e_send"):
            same(lua, R, key, [(e, v) for e in enums for v in vals])
        # the kept local copies agree with ai-util's rule
        for f, rule, wrap in (("ai-bans.lua", "e1", None), ("ai-threat-facts.lua", "e1", None),
                              ("ai-missions.lua", "e2", None), ("ai-raids.lua", "e2", True)):
            src = (LUA_DIR / f).read_text(encoding="utf-8")
            i = src.index("local function enum_name(enum, v)")
            body = src[i:src.index("\nend\n", i) + 5]
            local = lua.execute(body + "\nreturn enum_name")
            for e in enums:
                for v in vals:
                    a = R.call(local, e, v)
                    b = R.call(R.N[rule], e, v) if not (wrap and e is None) else "ok:nil:nil"
                    assert a == b, (f, v, a, b)

    @test("the modules changed still compile (with the ai-util prelude the tests use)")
    def _():
        from lua_modules_util import module_src
        import subprocess
        changed = subprocess.run(["git", "diff", "--name-only", "de94504", "--", "lua"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split()
        names = [Path(c).name for c in changed if c.endswith(".lua")] or \
            ["ai-threats.lua", "ai-captives.lua", "ai-hunt.lua", "ai-traffic.lua"]
        lua = LuaRuntime(unpack_returned_tuples=True)
        for n in names:
            if n == "ai-util.lua":
                continue
            src = module_src(n)
            fn = lua.execute("local s, n = ... return load(s, n, 't', setmetatable({}, {__index = _G}))", src, n)
            assert fn is not None, n
else:
    @test("lua tests")
    def _():
        skip("no lupa")


if __name__ == "__main__":
    finish()
