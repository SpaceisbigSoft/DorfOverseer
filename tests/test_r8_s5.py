"""(r8, code health s5) lua/ai-bridge.lua (132 KB) split by theme: the ACTIONS
table with DRY_OK, DISPLAY_ONLY and RELEASE_WHILE_HALTED in
ai-bridge-catalog.lua, the report's SECTIONS, the tiers and the section cache
in ai-bridge-sections.lua, the hub keeping the shared helpers, the loaders and
the commands. Each of the two is run by the hub where its lines stood
(HUB_PARTS, run_hub_part), so the top-level statements keep their order.
Behaviour unchanged: the hub with the two files' lines put back where they run
is, byte for byte, the one file of 0.105.63 (but the split's scaffolding and
the edits named below); the bridge loaded in parts defines the same globals as
the text in one piece.

Also here: `version` (stale_parts) and `modules` find a split module's parts
generically: every module of BRIDGE_MODULES whose file has a PARTS line.

    python tests/test_r8_s5.py
"""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src, split_src  # noqa: E402

LUA_DIR = ROOT / "lua"
NEW = ["ai-bridge-catalog", "ai-bridge-sections"]
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
TEXT = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in NEW}


def _version() -> str:
    return re.search(r"^BRIDGE_VERSION = '([^']+)'", HUB, re.M).group(1)


@test("sizes: the hub and its two new files are each under 60 KB (the one file was 132 KB)")
def _():
    for n in ["ai-bridge"] + NEW:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: HUB_PARTS names the two files; each is run once, where its lines stood: the catalog right "
      "after the BRIDGE_PARTS loop, the sections after the modules command and before build_state")
def _():
    listed = re.findall(r"'([\w-]+)'", re.search(r"^HUB_PARTS = \{(.*?)\}", HUB, re.M).group(1))
    assert listed == NEW, listed
    runs = re.findall(r"^run_hub_part\('([\w-]+)'\)", HUB, re.M)
    assert runs == NEW, runs
    at = HUB.index
    assert (at("for _, name in ipairs(BRIDGE_PARTS) do") < at("function run_hub_part(") < at("run_hub_part('ai-bridge-catalog')")
            < at("MAX_RUN_TICKS = ") < at("function version_info()") < at("local function cmd_modules()")
            < at("run_hub_part('ai-bridge-sections')") < at("function build_state(") < at("local COMMANDS = {")
            < at("if dfhack_flags.module then"))
    # BRIDGE_PARTS itself is as it was: the two are not loaded twice
    parts = re.findall(r"'([\w-]+)'", re.search(r"^BRIDGE_PARTS = \{(.*?)\}", HUB, re.M).group(1))
    assert not set(parts) & set(NEW), parts
    # the hub ends as the one file did: the module return, then the command printed
    assert HUB.rstrip().endswith("if dfhack_flags.module then\n    return\nend\n\n"
                                 "print(json.encode(main({...}), {pretty = false}))")


@test("parts: each new file is a bridge part (no module), refuses to run alone, carries its version mark; "
      "neither name reads as a later part of ai-bridge-report or ai-bridge-actions")
def _():
    for n in NEW:
        src = TEXT[n]
        assert "--@ module = true" not in src, n
        assert f"if not BRIDGE_VERSION then qerror('{n} is a part of ai-bridge; run ai-bridge') end" in src, n
        assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{_version()}'" in src, n
        assert not n.startswith(("ai-bridge-report-", "ai-bridge-actions-")), n


@test("themes: ACTIONS, DRY_OK, DISPLAY_ONLY, RELEASE_WHILE_HALTED are defined in the catalog only; "
      "SECTIONS, PULSE_SECTIONS, TIERS and the cache tables in the sections only; the commands in the hub")
def _():
    where = {"ai-bridge": HUB, **TEXT}

    def defs(pat):
        return [n for n, t in where.items() if re.search(pat, t, re.M)]
    for name in ("ACTIONS", "DRY_OK", "DISPLAY_ONLY", "RELEASE_WHILE_HALTED"):
        assert defs(rf"^{name} = ") == ["ai-bridge-catalog"], name
    for name in ("SECTIONS", "PULSE_SECTIONS", "TIERS", "SECTION_CACHE_DAYS", "SECTION_MAX_DAYS",
                 "CACHE_INVALIDATES", "SECTION_CACHE", "SECTION_REBUILDS"):
        assert defs(rf"^{name} = ") == ["ai-bridge-sections"], name
    for pat in (r"^local function safe\(", r"^function fort_key\(", r"^function deep_hazard_section\("):
        assert defs(pat) == ["ai-bridge-sections"], pat
    for pat in (r"^BRIDGE_VERSION = ", r"^BRIDGE_PARTS = ", r"^BRIDGE_MODULES = ", r"^function version_info\(",
                r"^function build_state\(", r"^function run_action\(", r"^function cmd_batch\(",
                r"^local COMMANDS = ", r"^local function main\("):
        assert defs(pat) == ["ai-bridge"], pat


# sha256 of lua/ai-bridge.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "9b4d6e679ee09e3de0d6f8c89263fcc98d95669eb6ad1719b7598686329acfcc"
SPLIT_VERSION = "0.105.63"

HEADER_RE = re.compile(
    r"^(?:|--.*"
    r"|if not BRIDGE_VERSION then qerror\('ai-bridge-[\w-]+ is a part of ai-bridge; run ai-bridge'\) end"
    r"|PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-bridge-[\w-]+'\] = '[^']+'   -- .*)$")

# The hub's edits beyond the cut itself, each (now, at 0.105.63): the header's
# words on what the file keeps; the hub's loader of its own two files; the
# split modules found from their files (this round's one change of behaviour,
# for the modules the other builders split); the two files counted with the
# parts by stale_parts and cmd_modules.
HUB_EDITS = [
    ("""-- (13c) The bridge is in parts. This file keeps the commands, BRIDGE_VERSION
-- and the loaders; (r8) the ACTIONS table (with DRY_OK and DISPLAY_ONLY, what
-- may pass while the AI is halted) is in ai-bridge-catalog.lua and the
-- report's SECTIONS and their cache in ai-bridge-sections.lua, each run where
-- it stood in this file (HUB_PARTS below). Beside it, loaded into
""",
     """-- (13c) The bridge is in parts. This file keeps the commands, BRIDGE_VERSION,
-- the ACTIONS table (with DRY_OK and DISPLAY_ONLY, what may pass while the AI
-- is halted), the report's SECTIONS and their cache. Beside it, loaded into
"""),
    (re.compile(r"-- \(r8\) The hub's own tables, each in a file beside this one:.*?\nHUB_PARTS = \{[^}\n]*\}\n"
                r"function run_hub_part\(name\)\n.*?\nend\n\n", re.S), ""),
    (re.compile(r"\n-- \(r8\) Any other module of BRIDGE_MODULES whose file has a PARTS line is a\n.*?"
                r"\nfunction split_modules\(\)\n.*?\nend\n", re.S), ""),
    ("    for _, n in ipairs(HUB_PARTS) do check(n, PART_VERSIONS) end\n", ""),
    ("    for _, n in ipairs(HUB_PARTS) do table.insert(parts, n) end\n", ""),
    ("for _, mod in ipairs(split_modules()) do", "for _, mod in ipairs(SPLIT_MODULES) do", 2),
]


def _body(name: str, removed: list) -> str:
    """A new file's lines without its header (to the version mark and the blank after it)."""
    lines = TEXT[name].split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
    assert lines[i] == "", name
    removed += lines[:i + 1]
    return "\n".join(lines[i + 1:])


@test("unchanged: the hub with the two files' lines put back where they are run and the named edits undone "
      "is, byte for byte, the one file of 0.105.63; the files add only headers, guards and marks")
def _():
    if _version() != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {_version()})")
    removed: list = []
    whole = HUB
    for edit in HUB_EDITS:
        now, old, want = edit[0], edit[1], (edit[2] if len(edit) > 2 else 1)
        if isinstance(now, str):
            assert whole.count(now) == want, (now[:60], whole.count(now))
            whole = whole.replace(now, old)
        else:
            whole, n = now.subn(old, whole)
            assert n == want, (now.pattern[:60], n)
    for n in NEW:
        line = re.search(rf"^run_hub_part\('{n}'\)   -- \(r8\) .*\n", whole, re.M)
        assert line, n
        body = _body(n, removed)
        assert body.endswith("\n") and not body.endswith("\n\n"), n
        # the run line stands for the file's lines; the blank after it is the old file's own
        whole = whole[:line.start()] + body + whole[line.end():]
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not HEADER_RE.match(l)]
    assert not bad, bad
    # the helper the other tests read the hub with gives the same code (headers kept)
    assert "ACTIONS = {" in bridge_hub_src() and bridge_hub_src() == split_src("ai-bridge.lua")
    h = bridge_hub_src()
    assert (h.index("for _, name in ipairs(BRIDGE_PARTS) do") < h.index("\nACTIONS = {") < h.index("\nDRY_OK = {}")
            < h.index("function version_info()") < h.index("\nSECTIONS = {") < h.index("function build_state("))
    assert "run_hub_part('ai-bridge-" not in h


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(text: str) -> set[str]:
    out = set()
    for l in text.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file of the three uses a top-level local another declares (none had to be handed on): "
      "`safe` is used in the sections file only, the hub's json, utils, file names and cmd_* in the hub only")
def _():
    texts = {"ai-bridge": HUB, **TEXT}
    locs = {n: _top_locals(t) for n, t in texts.items()}
    assert locs["ai-bridge-catalog"] == set(), locs["ai-bridge-catalog"]
    assert locs["ai-bridge-sections"] == {"safe"}, locs["ai-bridge-sections"]
    assert {"json", "utils", "STATE_FILE", "EVENTS_FILE", "MEMORY_FROM_SAVE", "HERE", "cancel_run", "cmd_modules",
            "build_state_body", "COMMANDS", "main"} <= locs["ai-bridge"], locs["ai-bridge"]
    family = set().union(*locs.values())
    for n, t in texts.items():
        code = [_strip(l) for l in t.split("\n")]
        for name in family - locs[n]:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])


ENV = r"""
local hub, whole_src, lua_dir = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env._G = env
    env.qerror = error
    env.dfhack_flags = {module = true}
    env.dfhack = {getDFPath = function() return 'df' end,
                  findScript = function(n) return lua_dir .. '/' .. n .. '.lua' end,
                  filesystem = {mtime = function() return 1 end}}
    env.require = function(n) return {n = n} end
    env.reqscript = function(n) return {} end
    return env
end
-- as the game runs it: the hub, its parts read from the files beside it
local split = fresh()
assert(load(hub, '@' .. lua_dir .. '/ai-bridge.lua', 't', split))()
-- the hub's text in one piece (the two files' lines where they are run)
local whole = fresh()
assert(load(whole_src, '@' .. lua_dir .. '/ai-bridge.lua', 't', whole))()
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if k ~= '_G' and k ~= 'PART_CHUNKS' then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
local chunks = {}
for path in pairs(split.PART_CHUNKS) do chunks[#chunks + 1] = path:match('([%w-]+)%.lua$') end
table.sort(chunks)
return keys(split), keys(whole), split, whole, table.concat(chunks, ' '), count
"""


def _load():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    return L, L.execute(ENV, HUB, bridge_hub_src(), str(LUA_DIR).replace("\\", "/"))


@test("load: the hub loaded with its parts defines the same globals as the text in one piece; ACTIONS, "
      "DRY_OK, SECTIONS and the cache tables are the same in both; each new file is compiled once")
def _():
    L, (a, b, split, whole, chunks, count) = _load()
    assert a == b
    g = set(a.split())
    for name, kind in (("ACTIONS", "table"), ("DRY_OK", "table"), ("DISPLAY_ONLY", "table"),
                       ("RELEASE_WHILE_HALTED", "table"), ("SECTIONS", "table"), ("PULSE_SECTIONS", "table"),
                       ("TIERS", "table"), ("SECTION_CACHE_DAYS", "table"), ("SECTION_MAX_DAYS", "table"),
                       ("CACHE_INVALIDATES", "table"), ("SECTION_CACHE", "table"), ("SECTION_CACHE_VERSION", "string"),
                       ("SECTION_REBUILDS", "number"), ("fort_key", "function"), ("deep_hazard_section", "function"),
                       ("version_info", "function"), ("build_state", "function"), ("run_action", "function"),
                       ("cmd_batch", "function"), ("BRIDGE_COMMANDS", "table"), ("HUB_PARTS", "table"),
                       ("run_hub_part", "function"), ("split_modules", "function"), ("MAX_RUN_TICKS", "number")):
        assert f"{name}:{kind}" in g, name
    assert "safe:function" not in g      # still a local
    same = L.eval("""function(x, y, names)
        local function ks(t) local o = {} for k, v in pairs(t) do
            o[#o + 1] = tostring(k) .. ':' .. (type(v) == 'table' and 'table' or type(v) == 'function' and 'function' or tostring(v)) end
            table.sort(o) return table.concat(o, ' ') end
        local out = {}
        for i = 1, #names do if ks(x[names[i]]) ~= ks(y[names[i]]) then out[#out + 1] = names[i] end end
        return table.concat(out, ' ') end""")
    names = ["ACTIONS", "DRY_OK", "DISPLAY_ONLY", "RELEASE_WHILE_HALTED", "SECTIONS", "PULSE_SECTIONS", "TIERS",
             "SECTION_CACHE_DAYS", "SECTION_MAX_DAYS", "CACHE_INVALIDATES", "BRIDGE_COMMANDS"]
    assert same(split, whole, L.table_from(names)) == ""
    assert count(split.ACTIONS) > 200 and count(split.SECTIONS) > 60, (count(split.ACTIONS), count(split.SECTIONS))
    assert count(split.DRY_OK) > 40 and split.DRY_OK["work_order"] is None
    listed = re.findall(r"'([\w-]+)'", re.search(r"^BRIDGE_PARTS = \{(.*?)\}", HUB, re.M).group(1))
    assert chunks.split() == sorted(listed + NEW), chunks
    for n in listed + NEW:
        assert split.PART_VERSIONS[n] == split.BRIDGE_VERSION, n


@test("order: with ai-bridge-sections missing the hub stops there, the catalog and the version command "
      "already defined, build_state and the commands not yet (each file runs where its lines stood)")
def _():
    L, (_a, _b, _split, _whole, _chunks, _count) = _load()
    out = L.execute(r"""
        local hub, lua_dir = ...
        local env = setmetatable({}, {__index = _G})
        env.qerror = error
        env.dfhack_flags = {module = true}
        env.dfhack = {getDFPath = function() return 'df' end, findScript = function(n) return nil end}
        env.require = function(n) return {} end
        local real_open = io.open
        env.io = setmetatable({open = function(p, m)
            if p:find('ai%-bridge%-sections') then return nil end
            return real_open(p, m) end}, {__index = io})
        local ok, err = pcall(assert(load(hub, '@' .. lua_dir .. '/ai-bridge.lua', 't', env)))
        return {ok, tostring(err), type(env.ACTIONS), type(env.DRY_OK), type(env.version_info), type(env.stale_parts),
                type(env.SECTIONS), type(env.build_state), type(env.BRIDGE_COMMANDS)}
    """, HUB, str(LUA_DIR).replace("\\", "/"))
    got = [out[i] for i in range(1, 10)]
    assert got[0] is False and "ai-bridge-sections.lua is missing (it goes beside ai-bridge.lua)" in got[1], got
    assert got[2:] == ["table", "table", "function", "function", "nil", "nil", "nil"], got


GENERIC = r"""
local hub, dir = ...
local env = setmetatable({}, {__index = _G})
env.qerror = error
env.dfhack_flags = {module = true}
local mtimes = {}
env.dfhack = {getDFPath = function() return 'df' end, findScript = function(n) return nil end,
              filesystem = {mtime = function(p) return mtimes[p] or 1 end}}
env.require = function(n) return {} end
local mods = {}
env.reqscript = function(n)
    if mods[n] == nil then error('no such module: ' .. n) end
    return mods[n]
end
local reads = {}
local real_open = io.open
env.io = setmetatable({open = function(p, m)
    local name = p:match('([%w-]+)%.lua$')
    if name then reads[name] = (reads[name] or 0) + 1 end
    return real_open(p, m) end}, {__index = io})
assert(load(hub, '@' .. dir .. '/ai-bridge.lua', 't', env))()
return env, mods, reads, mtimes
"""


def _write(d: Path, name: str, text: str):
    (d / f"{name}.lua").write_text(text, encoding="utf-8", newline="\n")


@test("generic: a module of BRIDGE_MODULES whose file has a PARTS line is a hub with parts for `version` "
      "and `modules` (stale_parts, the parts compiled), with no line naming it; one without is not; each "
      "module's file is read once until it changes")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    v = _version()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        # the bridge and all its own parts, as delivered
        for p in LUA_DIR.glob("ai-bridge*.lua"):
            _write(d, p.stem, p.read_text(encoding="utf-8"))
        # a split hub the bridge has no line for (ai-gates' way), one of its parts, a plain module
        _write(d, "ai-waterworks", "--@ module = true\nPARTS = {'pumps',   -- the pump stacks\n    'drains'}\n")
        _write(d, "ai-waterworks-pumps", "x = 1\n")
        _write(d, "ai-waterworks-drains", "x = = 2\n")             # does not compile
        _write(d, "ai-water", "--@ module = true\nlocal PARTS = {'a'}\n    PARTS = {'b'}\n")   # no PARTS line of a hub
        _write(d, "ai-builder", "--@ module = true\nPARTS = {'sites'}\n")
        _write(d, "ai-builder-sites", "y = 1\n")
        _write(d, "ai-gates", "--@ module = true\nPARTS = {'scan'}\n")
        _write(d, "ai-gates-scan", "y = 1\n")
        M, mods, reads, mtimes = L.execute(GENERIC, HUB, str(d).replace("\\", "/"))
        lt = L.eval("function(py) local t = {} for k, v in python.iter(py) do t[k] = v end return t end")

        def lst(t):
            return [t[i] for i in range(1, len(t) + 1)]
        assert lst(M.split_modules()) == ["ai-builder", "ai-gates", "ai-waterworks"], lst(M.split_modules())
        assert M.module_has_parts("ai-waterworks") is True and M.module_has_parts("ai-water") is False
        assert M.module_has_parts("ai-society") is False        # no file here: not a hub, no error
        assert lst(M.split_part_names("ai-waterworks")) == ["ai-waterworks-pumps", "ai-waterworks-drains"]
        # read once, and again only when the file changes
        _write(d, "ai-water", "--@ module = true\nPARTS = {'pipes'}\n")
        assert M.module_has_parts("ai-water") is False          # same modification time: the kept answer
        mtimes[str(d).replace("\\", "/") + "/ai-water.lua"] = 2
        assert M.module_has_parts("ai-water") is True
        _write(d, "ai-water", "--@ module = true\n")
        mtimes[str(d).replace("\\", "/") + "/ai-water.lua"] = 3
        assert M.module_has_parts("ai-water") is False

        # version's stale_parts: the hub's own mark and each part's, from the hub's PART_VERSIONS
        def marks(names, version=v):
            return L.table_from({"PART_VERSIONS": L.table_from({n: version for n in names})})
        mods["ai-builder"] = marks(["ai-builder", "ai-builder-sites"])
        mods["ai-gates"] = marks(["ai-gates", "ai-gates-scan"])
        for m in lst(M.MARKED_MODULES):
            mods[m] = marks([m])
        mods["ai-waterworks"] = marks(["ai-waterworks", "ai-waterworks-pumps", "ai-waterworks-drains"])
        assert lst(M.stale_parts()) == [], lst(M.stale_parts())
        mods["ai-waterworks"] = L.table_from({"PARTS": L.table_from(["pumps", "drains"]), "PART_VERSIONS": L.table_from(
            {"ai-waterworks": v, "ai-waterworks-pumps": "0.0.1"})})
        assert lst(M.stale_parts()) == ["ai-waterworks-pumps (0.0.1)", "ai-waterworks-drains (no version mark)"], \
            lst(M.stale_parts())
        mods["ai-waterworks"] = None
        stale = lst(M.stale_parts())
        assert len(stale) == 1 and stale[0].startswith("ai-waterworks (does not load: "), stale
        # the hub's own two files are checked with the bridge's parts
        M.PART_VERSIONS["ai-bridge-sections"] = "0.0.2"
        assert "ai-bridge-sections (0.0.2)" in lst(M.stale_parts())
        M.PART_VERSIONS["ai-bridge-sections"] = v

        # modules: the new hub's parts compiled with the rest; the broken one named
        mods["ai-waterworks"] = marks(["ai-waterworks", "ai-waterworks-pumps", "ai-waterworks-drains"])
        for m in lst(M.BRIDGE_MODULES):
            if m not in mods or mods[m] is None:
                mods[m] = L.table()
        r = M.BRIDGE_COMMANDS.modules()
        n_bridge = len(lst(M.BRIDGE_PARTS)) + len(lst(M.HUB_PARTS))
        assert r.parts == n_bridge + 1 + 1 + 2, r.parts
        failed = {f.name: f.error for f in lst(r.failed)}
        assert list(failed) == ["ai-waterworks-drains"], failed
        assert r.ok is False and r.stale_parts is None
        _write(d, "ai-waterworks-drains", "x = 2\n")
        r = M.BRIDGE_COMMANDS.modules()
        assert r.ok is True and r.failed is None and r.parts == n_bridge + 4, dict(r)
        del lt


@test("generic, the real files: every lua module with a PARTS line of its own is found (ai-builder and "
      "ai-gates at least), each of its parts' files is there, and the hub and the parts carry the version")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    M, _mods, _reads, _mt = L.execute(GENERIC, HUB, str(LUA_DIR).replace("\\", "/"))
    found = [M.split_modules()[i] for i in range(1, len(M.split_modules()) + 1)]
    assert found[:2] == ["ai-builder", "ai-gates"], found
    modules = [M.BRIDGE_MODULES[i] for i in range(1, len(M.BRIDGE_MODULES) + 1)]
    want = [m for m in modules if re.search(r"^PARTS = \{", (LUA_DIR / f"{m}.lua").read_text(encoding="utf-8"), re.M)]
    assert sorted(found) == sorted(want), (found, want)
    v = _version()
    for mod in found:
        hub = (LUA_DIR / f"{mod}.lua").read_text(encoding="utf-8")
        assert re.search(rf"^PART_VERSIONS = \{{\['{re.escape(mod)}'\] = '{re.escape(v)}'\}}", hub, re.M), \
            f"{mod}: the hub marks itself in PART_VERSIONS (as ai-gates does), or `version` lists it as stale"
        names = M.split_part_names(mod)
        parts = [names[i] for i in range(1, len(names) + 1)]
        assert parts, mod
        for p in parts:
            src = (LUA_DIR / f"{p}.lua").read_text(encoding="utf-8")
            assert f"PART_VERSIONS['{p}'] = '{v}'" in src, p


if __name__ == "__main__":
    finish()
