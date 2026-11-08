"""(0.105.26, group bridge) The bridge's parts compiled once, not on every
command; the `modules` command and the parts' version marks for the
self-test; the tests on Lua 5.3 (DFHack's); the split modules' forwarders
without a reqscript a call; dry runs refused for actions that would act; the
dead `tidy` action and `instruments` section gone. On a stub DFHack in a real
Lua 5.3 engine (pip install lupa).

    python tests/test_fix26_bridge.py
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
from pathlib import Path

from harness import ROOT, finish, test

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package with Lua 5.3 (pip install lupa)")
    sys.exit(0)

sys.path.insert(0, str(ROOT / "brain"))

LUA_DIR = ROOT / "lua"
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
BRIDGE_PARTS = ["ai-bridge-report", "ai-bridge-orders", "ai-bridge-actions", "ai-bridge-probes"]
BUILDER_PARTS = ["ai-builder-" + p for p in ("sites", "projects", "farms", "wells", "cistern", "surface", "rooms", "halls")]
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", HUB, re.M).group(1)

# the stub DFHack of tests/test_hygiene_bridge.py, read from it (not copied)
_hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
HARNESS = re.search(r'HARNESS = r"""(.*?)"""', _hyg, re.S).group(1)
# with what this file needs besides: file times (H.mtimes, by path), findScript
# (none), loadfile counted (H.compiled) and a rerun of the hub in its own env
HARNESS = HARNESS.replace("return H\n", r"""
H.mtimes, H.compiled = {}, {}
dfhack.filesystem.mtime = function(p) return H.mtimes[p] or 1 end
dfhack.findScript = function() return nil end
dfhack.getDFHackVersion = function() return 'x' end
dfhack.getDFVersion = function() return 'y' end
function H.count_compiles(env)
  env.loadfile = function(p, m, e)
    local name = tostring(p):match('([%w_-]+)%.lua$')
    H.compiled[name] = (H.compiled[name] or 0) + 1
    return loadfile(p, m, e)
  end
end
function H.rerun(env, ...)
  env.dfhack_flags = {module = select('#', ...) == 0}
  H.printed = nil
  assert(load(src, '@' .. lua_dir .. '/ai-bridge.lua', 't', env))(...)
  return H.printed
end
return H
""")

LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, HUB, str(LUA_DIR))


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def fresh():
    H.scripts = LUA.table()
    H.halted = False
    H.mtimes = LUA.table()
    H.compiled = LUA.table()
    return H.module()


def lua_list(v) -> list:
    return [] if v is None else [v[i] for i in range(1, len(v) + 1)]


# --- 1. parts compiled once ---------------------------------------------------

@test("hub: each part is compiled once and run on every command; again only when its file changes")
def _():
    M = fresh()
    H.count_compiles(M)
    for _ in range(3):
        M.get_dwarves = None                  # a part's function: back if the part ran
        H.rerun(M)
        assert M.get_dwarves is not None, "the parts did not run"
    assert dict(H.compiled) == {}, dict(H.compiled)
    H.mtimes[str(LUA_DIR / "ai-bridge-orders.lua")] = 2
    H.rerun(M)
    assert dict(H.compiled) == {"ai-bridge-orders": 1}, dict(H.compiled)
    H.rerun(M)
    assert dict(H.compiled) == {"ai-bridge-orders": 1}, dict(H.compiled)
    assert len(lua_list(LUA.eval("function(M) local o = {} for k in pairs(M.PART_CHUNKS) do o[#o+1] = k end return o end")(M))) == 4


@test("hub: without file times (an old DFHack) the parts are compiled each time, as before")
def _():
    M = fresh()
    H.count_compiles(M)
    M.dfhack = LUA.eval("function(d) return setmetatable({filesystem = {}}, {__index = d}) end")(H.dfhack)
    H.rerun(M)
    assert dict(H.compiled) == {n: 1 for n in BRIDGE_PARTS}, dict(H.compiled)


# --- 2. version marks and `modules` ------------------------------------------

MARKED = BRIDGE_PARTS + ["ai-builder"] + BUILDER_PARTS + ["ai-military-gear", "ai-society-burrows", "ai-constructions"]


@test("marks: every part carries one version mark, the same string as BRIDGE_VERSION")
def _():
    for n in MARKED:
        src = (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")
        marks = re.findall(r"PART_VERSIONS(?:\['([\w-]+)'\]|\s*=\s*\{\['([\w-]+)'\])\s*=\s*'([^']+)'", src)
        assert len(marks) == 1, (n, marks)
        name = marks[0][0] or marks[0][1]
        assert name == n and marks[0][2] == VERSION, (n, marks)


@test("marks: one find-replace of the quoted version bumps BRIDGE_VERSION and every mark, nothing else")
def _():
    hits = {}
    for p in sorted(LUA_DIR.rglob("*.lua")):
        n = p.read_text(encoding="utf-8").count(f"'{VERSION}'")
        if n:
            hits[p.stem] = n
    assert hits == {"ai-bridge": 1, **{n: 1 for n in MARKED}}, hits


@test("version: lists a part whose mark differs or is missing; none when all match")
def _():
    M = fresh()
    good = {"PARTS": LUA.table_from(["sites", "rooms"]),
            "PART_VERSIONS": t({"ai-builder": VERSION, "ai-builder-sites": VERSION, "ai-builder-rooms": VERSION})}
    H.scripts["ai-builder"] = t(good)
    H.scripts["ai-military-gear"] = t({"PART_VERSIONS": {"ai-military-gear": VERSION}})
    H.scripts["ai-society-burrows"] = t({"PART_VERSIONS": {"ai-society-burrows": VERSION}})
    H.scripts["ai-constructions"] = t({"PART_VERSIONS": {"ai-constructions": VERSION}})   # (0.105.30)
    assert lua_list(M.stale_parts()) == []
    H.scripts["ai-builder"].PART_VERSIONS["ai-builder-rooms"] = "0.0.1"
    H.scripts["ai-society-burrows"].PART_VERSIONS = None
    M.PART_VERSIONS["ai-bridge-probes"] = "0.0.1"
    stale = lua_list(M.stale_parts())
    assert stale == ["ai-bridge-probes (0.0.1)", "ai-builder-rooms (0.0.1)", "ai-society-burrows (no version mark)"], stale
    H.scripts["ai-layouts"] = t({"KINDS": [], "STOCKPILES": {}, "WORKSHOPS": {}})
    v = H.rerun(M, "version")                 # the probes part ran again with the command: marked
    assert v.ok and v.bridge_version == VERSION, dict(v)
    assert lua_list(v.stale_parts) == ["ai-builder-rooms (0.0.1)", "ai-society-burrows (no version mark)"], \
        lua_list(v.stale_parts)
    H.scripts["ai-builder"].PART_VERSIONS["ai-builder-rooms"] = VERSION
    H.scripts["ai-society-burrows"].PART_VERSIONS = t({"ai-society-burrows": VERSION})
    v = H.rerun(M, "version")
    assert v.ok and v.stale_parts is None, lua_list(v.stale_parts)


@test("modules: BRIDGE_MODULES is every module in lua/ (not ai-bridge, not the parts)")
def _():
    M = fresh()
    want = set()
    for p in LUA_DIR.rglob("*.lua"):
        if re.search(r"^--@\s*module\s*=\s*true", p.read_text(encoding="utf-8"), re.M) and p.stem != "ai-bridge":
            want.add(p.relative_to(LUA_DIR).with_suffix("").as_posix())
    assert set(lua_list(M.BRIDGE_MODULES)) == want, set(lua_list(M.BRIDGE_MODULES)) ^ want


@test("modules: a module that fails to load and a part that is missing are both listed; ok when all load")
def _():
    M = fresh()
    for m in lua_list(M.BRIDGE_MODULES):
        H.scripts[m] = t({"PART_VERSIONS": {m: VERSION}})
    H.scripts["ai-builder"] = t({"PARTS": [p[len("ai-builder-"):] for p in BUILDER_PARTS],
                                 "PART_VERSIONS": {n: VERSION for n in ["ai-builder"] + BUILDER_PARTS}})
    r = H.rerun(M, "modules")
    assert r.ok and r.failed is None and r.stale_parts is None, dict(r)
    assert r.parts == len(BRIDGE_PARTS) + len(BUILDER_PARTS) and r.modules == len(lua_list(M.BRIDGE_MODULES)), dict(r)
    H.scripts["ai-society"] = None                    # the harness's reqscript errors for it
    H.scripts["ai-builder"].PARTS = LUA.table_from(["sites", "nosuch"])
    r = H.rerun(M, "modules")
    failed = {x.name: x.error for x in lua_list(r.failed)}
    assert not r.ok and set(failed) == {"ai-society", "ai-builder-nosuch"}, failed
    assert "missing" in failed["ai-builder-nosuch"], failed


@test("modules: a part or a module whose file doesn't compile is listed (a module DFHack loaded before, too)")
def _():
    M = fresh()
    for m in lua_list(M.BRIDGE_MODULES):
        H.scripts[m] = t({})
    H.scripts["ai-builder"] = t({"PARTS": ["broken"]})
    old = H.dfhack.findScript
    H.dfhack.findScript = LUA.eval("""function(n)
        if n == 'ai-builder-broken' or n == 'ai-trade' then
          local p = os.tmpname(); local f = io.open(p, 'w'); f:write('local x = = 1'); f:close(); return p
        end
        return nil end""")
    try:
        r = H.rerun(M, "modules")
    finally:
        H.dfhack.findScript = old
    failed = {x.name: x.error for x in lua_list(r.failed)}
    assert set(failed) == {"ai-builder-broken", "ai-trade"} and "unexpected symbol" in failed["ai-trade"], failed


# --- the self-test ------------------------------------------------------------

import selftest  # noqa: E402


@test("selftest: an error nested in a section (society.hospital_burrow) is found; a reason beside a stage is not")
def _():
    st = {"society": {"pastures": 2, "hospital_burrow": {"error": "attempt to index nil"}},
          "logistics": {"feeders": {"error": "x"}, "storage": {"n": 1}, "counts": {}},
          "farms": {"error": "boom"}, "projects": [{"id": 1, "stage": "dig", "error": "waiting for miners"}],
          "_timing": {"error": 1}, "date": {"year": 3}}
    errs = selftest.report_errors(st)
    assert errs == ["society.hospital_burrow.error: attempt to index nil", "logistics.feeders.error: x",
                    "farms.error: boom"], errs
    assert selftest.report_errors({"date": {}, "society": {"ok": 1}}) == []


class FakeBridge:
    def __init__(self, reply):
        self.reply = reply

    def _call(self, *args, **kw):
        assert args == ("modules",), args
        return self.reply


@test("selftest: a module or part that fails to load is a FAIL; all loading is a PASS")
def _():
    selftest.RESULTS.clear()
    with contextlib.redirect_stdout(io.StringIO()):          # (its lines would read as this file's)
        selftest.check_modules(FakeBridge({"ok": False, "modules": 30, "parts": 11,
                                           "failed": [{"name": "ai-society", "error": "syntax error near 'end'"}]}))
        selftest.check_modules(FakeBridge({"ok": False, "error": "unknown command: modules"}))
        selftest.check_modules(FakeBridge({"ok": True, "modules": 31, "parts": 11}))
    levels = [lv for lv, _, _ in selftest.RESULTS]
    assert levels == ["FAIL", "FAIL", "PASS"], selftest.RESULTS
    assert "ai-society" in selftest.RESULTS[0][2]


@test("selftest: section errors and stale parts are FAILs (not WARNs)")
def _():
    src = (ROOT / "brain" / "selftest.py").read_text(encoding="utf-8")
    i = src.index('errs = report_errors(state)')
    assert '"FAIL"' in src[i:i + 300] and '"WARN"' not in src[i:i + 300]
    i = src.index('stale = info.get("stale_parts")')
    assert '"FAIL"' in src[i:i + 300] and "check_modules(bridge)" in src[i:i + 600]


# --- 3. Lua 5.3 ---------------------------------------------------------------

@test("tests: every Lua engine in the tests is Lua 5.3, DFHack's (lupa.lua53)")
def _():
    assert LUA.eval("_VERSION") == "Lua 5.3"
    bad = []
    for p in sorted((ROOT / "tests").glob("*.py")):
        if p.name == Path(__file__).name:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"from lupa import LuaRuntime|lupa\.LuaRuntime\(|lupa\.lua5[^3]|lupa\.luajit", line):
                bad.append(f"{p.name}:{n}")
    assert not bad, bad


# --- 4. the forwarders' lookup ------------------------------------------------

def forwarder(file: str, fn: str):
    src = (LUA_DIR / file).read_text(encoding="utf-8")
    m = re.search(r"(local [A-Z]+, [A-Z]+_PATH, [A-Z]+_MTIME\n)?local function " + fn
                  + r"\(\)(?: return [^\n]*end\n|.*?\nend\n)", src, re.S)
    assert m, (file, fn)
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.eval("""function(chunk)
        local S = {calls = 0, mtime = 5, mod = {}}
        S.check = function(x) return rawequal(x, S.mod) end
        local env = setmetatable({S = S}, {__index = _G})
        env.reqscript = function(n) S.calls = S.calls + 1; S.name = n; return S.mod end
        env.dfhack = {findScript = function(n) return '/scripts/' .. n .. '.lua' end,
                      filesystem = {mtime = function(p) S.path = p; return S.mtime end}}
        S.fn = assert(load(chunk .. ' return ' .. '""" + fn + """', 'f', 't', env))()
        return S end""")(m.group(0))
    return env


for _file, _fn, _mod in (("ai-military.lua", "gear", "ai-military-gear"),
                         ("ai-society.lua", "burrows", "ai-society-burrows")):
    @test(f"{_file}: {_fn}() looks {_mod} up once; again (the same table, reloaded) when its file changes")
    def _(file=_file, fn=_fn, mod=_mod):
        S = forwarder(file, fn)
        a, b, c = S.fn(), S.fn(), S.fn()
        assert S.calls == 1 and S.name == mod, (S.calls, S.name)
        assert S.check(a) and S.check(b) and S.check(c)
        assert S.path == f"/scripts/{mod}.lua", S.path
        S.mtime = 6                               # the part's file changed: reqscript reloads it
        assert S.check(S.fn()) and S.calls == 2, S.calls
        S.fn()
        assert S.calls == 2, S.calls


@test("ai-military / ai-society: the forwarders still go through the kept lookup")
def _():
    mil = (LUA_DIR / "ai-military.lua").read_text(encoding="utf-8")
    soc = (LUA_DIR / "ai-society.lua").read_text(encoding="utf-8")
    assert "_ENV[name] = function(...) return gear()[name](...) end" in mil
    assert "_ENV[name] = function(...) return burrows()[name](...) end" in soc


# --- 5. dry runs --------------------------------------------------------------

@test("act: a dry run of an action without one is refused, not done; a DRY_OK one goes to its handler")
def _():
    M = fresh()
    H.scripts["ai-gates"] = LUA.eval("{arm = function() ARMED = (ARMED or 0) + 1; return {ok = true} end}")
    r = H.act(M, t({"type": "arm_gates", "dry_run": True}))
    assert not r.ok and r.rejected and "no dry run" in r.error, dict(r)
    assert LUA.eval("ARMED") is None, "arm_gates acted on a dry run"
    r = H.act(M, t({"type": "arm_gates"}))
    assert r.ok and LUA.eval("ARMED") == 1, dict(r)
    r = H.act(M, t({"type": "arm_gates", "dry_run": "yes"}))
    assert not r.ok and r.rejected and "true or false" in r.error, dict(r)
    r = H.act(M, t({"type": "arm_gates", "dry_run": False}))
    assert r.ok and LUA.eval("ARMED") == 2, dict(r)
    H.scripts["ai-joins"] = LUA.eval("{join_levels = function(dry) return {ok = true, dry_run = dry} end}")
    r = H.act(M, t({"type": "join_levels", "dry_run": True}))
    assert r.ok and r.dry_run is True, dict(r)
    for name in ("report_status", "set_culture", "save_memory", "unpause", "pull_gate", "narrow_detail", "work_order"):
        assert M.DRY_OK[name] is None, name


@test("act: the brain's own dry runs are all on DRY_OK (set_rules, apply_preset, the self-test's, try_building)")
def _():
    M = fresh()
    sent = set()
    for p in list((ROOT / "brain").rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        for m in re.finditer(r'\{"type": "(\w+)"[^}]*"dry_run": (?!False)', src):
            sent.add(m.group(1))
        for m in re.finditer(r'act\(\w*,? ?\{"type": "(\w+)", "dry_run": True', src):
            sent.add(m.group(1))
    assert {"set_rules", "apply_preset", "start_project", "found_fort", "link_lever"} <= sent, sent
    missing = sorted(n for n in sent if M.DRY_OK[n] is None)
    assert not missing, missing


# --- 6. dead code -------------------------------------------------------------

@test("gone: the tidy action and the instruments section, everywhere")
def _():
    M = fresh()
    assert M.ACTIONS.tidy is None and M.DRY_OK.tidy is None and M.SECTIONS.instruments is None
    assert M.SECTION_CACHE_DAYS.instruments is None and M.act_tidy is None and M.get_instruments is None
    from overseer import SHORT_WORDS
    from digest import SECTION_DEFAULTS
    assert "tidy" not in SHORT_WORDS and "instruments" not in SECTION_DEFAULTS
    assert M.ACTIONS.order_instrument is not None          # ordering instruments stays


if __name__ == "__main__":
    finish()
