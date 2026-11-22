"""(r9, code health t9) lua/ai-util.lua (68 KB), the helpers every module takes
with reqscript('ai-util'), split by theme into a hub and four parts, as
lua/ai-gates.lua is: the hub (the world and the fort, ticks, the save's site
data, the per-report shared walks, items free or forbidden, the dead) loads
ai-util-dig (the dig guard, the deep map, deep_hazard), ai-util-flows (the
flows walked once a report), ai-util-doors (doors, hatches and the walk map)
and ai-util-helpers (r6 c1: report_citizens, now_tick, name_of, enum_name and
their variants) into its own environment. Behaviour unchanged: the five
files with the split's scaffolding taken out are the old file's lines;
loaded as the hub does (from its files, from UTIL_SRC, through the prelude)
they define the same names as the text in one piece; no file-scope local
crosses a cut.

    python tests/test_r9_t9.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import SPLIT, split_parts, split_src, UTIL_SRC, module_src  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB_NAME = "ai-util"
PARTS = ["ai-util-dig", "ai-util-flows", "ai-util-doors", "ai-util-helpers"]
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the five files are each under 60 KB (the one was 68 KB)")
def _():
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS lists dig, flows, doors, helpers; the tests' helper reads the family (SPLIT, split_parts, "
      "split_src) and UTIL_SRC carries the parts' texts")
def _():
    hub = text(HUB_NAME)
    assert re.search(r"^PARTS = \{'dig', 'flows', 'doors', 'helpers'\}$", hub, re.M)
    assert "ai-util.lua" in SPLIT and split_parts("ai-util.lua") == PARTS
    assert split_src("ai-util.lua") == "\n".join(text(n) for n in [HUB_NAME] + PARTS)
    # UTIL_SRC: one line before the hub's first (its line numbers stay), the hub itself after it
    first, rest = UTIL_SRC.split("\n", 1)
    assert first.startswith("local PART_SOURCES = {") and first.endswith("}; " + hub.split("\n", 1)[0]), first[:80]
    assert rest == hub.split("\n", 1)[1]
    for n in PARTS:
        assert f'["{n}"] = "' in first, n
    # the hub is still the module; the loader is the last thing in it
    assert re.search(r"^--@module = true$", hub, re.M)
    tail = hub[hub.index("for _, part in ipairs(PARTS) do"):]
    assert tail.rstrip("\n").endswith("    end\nend") and tail.count("\n") == 11, tail
    assert "assert(load(src, name, 't', _ENV))()" in tail and "assert(loadfile(path, 't', _ENV))()" in tail


@test("parts: each new file is a part (no module), refuses to run alone, carries its version mark; the hub its own")
def _():
    assert f"PART_VERSIONS = {{['ai-util'] = '{VERSION}'}}" in text(HUB_NAME)
    for n in PARTS:
        src = text(n)
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert f"if not PARTS then qerror('{n} is a part of ai-util; run ai-util') end" in src, n
        assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'" in src, n
        assert src.count(f"'{VERSION}'") == 1, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not PARTS then qerror\('ai-util-\w+ is a part of ai-util; run ai-util'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-util-\w+'\] = '[^']+'   -- .*",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
LOADER_AT = "\n---------------------------------------------------------------------------\n-- (r9) The rest of ai-util"
# the hub's end: the part list and the loader (lua/ai-gates.lua's, with this module's name)
LOADER = """PARTS = {'dig', 'flows', 'doors', 'helpers'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['ai-util'] = 'V'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-util-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-util: ' .. name .. '.lua is missing (it goes beside ai-util.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
"""

# sha256 of lua/ai-util.lua at 0.105.64 (8183548), the last commit with it in one file
OLD_SHA = "feba768ecec72d739aa7fa27bfd2cabdda5cc960f40609c5e2877b0fd67ba6d2"
OLD_SIZE = 68284
SPLIT_VERSION = "0.105.64"


def _bodies() -> tuple[list[str], list[str]]:
    """The five files' texts without the split's scaffolding, and the lines taken out."""
    removed: list[str] = []
    hub = text(HUB_NAME)
    at = hub.index(LOADER_AT)
    tail = hub[at + 1:]
    k = tail.index("PARTS = {")
    assert re.sub(r"'0\.105\.\d+'", "'V'", tail[k:]) == LOADER      # the loader, whole
    removed += tail[:k].split("\n")
    bodies = [hub[:at]]
    for n in PARTS:
        lines = text(n).split("\n")
        i = next(j for j, l in enumerate(lines) if l.startswith("PART_VERSIONS = PART_VERSIONS or")) + 1
        assert lines[i] == "", n
        removed += lines[:i + 1]
        bodies.append("\n".join(lines[i + 1:]))
    return bodies, removed


def old_text() -> str:
    bodies, _ = _bodies()
    return "\n\n".join(b.rstrip("\n") for b in bodies) + "\n"


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file of "
      "0.105.64; what was taken out is headers, marks, guards, comments and the loader")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
    bodies, removed = _bodies()
    whole = old_text()
    assert len(whole.encode("utf-8")) == OLD_SIZE, len(whole.encode("utf-8"))
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(src: str) -> set[str]:
    out = set()
    for l in src.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*(=|$)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a file-scope local another file declares (nothing needs handing on)")
def _():
    texts = {n: text(n) for n in [HUB_NAME] + PARTS}
    family = set().union(*(_top_locals(t) for t in texts.values())) - {"part_path"}
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])


ENV = r"""
local hub, parts, whole_src, util_src = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env.qerror = error
    return env
end
local split = fresh()
split.PART_SOURCES = parts
assert(load(hub, 'ai-util', 't', split))()
local whole = fresh()
assert(load(whole_src, 'whole', 't', whole))()
local from_text = fresh()
assert(load(util_src, 'ai-util', 't', from_text))()
local function keys(e, skip)
    local o = {}
    for k, v in pairs(e) do
        if not skip[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
local scaffold = {PART_SOURCES = true, PARTS = true, PART_VERSIONS = true}
local extra = {}
for k in pairs(scaffold) do if split[k] ~= nil then extra[#extra + 1] = k end end
table.sort(extra)
-- a part run alone refuses
local alone = fresh()
local ok, err = pcall(assert(load(parts['ai-util-dig'], 'ai-util-dig', 't', alone)))
return keys(split, scaffold), keys(whole, scaffold), keys(from_text, scaffold), table.concat(extra, ' '),
       split, ok, tostring(err), from_text.PART_SOURCES == nil
"""


@test("load: the hub with its parts defines the same names as the text in one piece (and PARTS, PART_VERSIONS); "
      "UTIL_SRC loaded alone does too, without leaving PART_SOURCES in its env; every part marked; a part alone refuses")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, c, extra, env, ok, err, no_src = L.execute(
        ENV, text(HUB_NAME), L.table_from({n: text(n) for n in PARTS}), old_text(), UTIL_SRC)
    assert a == b, (set(a.split()) ^ set(b.split()))
    assert c == b, (set(c.split()) ^ set(b.split()))
    for n in ("fort_id:function", "item_unfree:function", "dig_forbidden:function", "deep_hazard:function",
              "flows_where:function", "lock_door:function", "enum_text:function", "now_tick:function"):
        assert n in a, n
    assert extra == "PARTS PART_SOURCES PART_VERSIONS", extra
    assert no_src is True
    assert dict(env.PART_VERSIONS) == {n: VERSION for n in [HUB_NAME] + PARTS}, dict(env.PART_VERSIONS)
    assert not ok and "ai-util-dig is a part of ai-util; run ai-util" in err, err


@test("files: loaded by loadfile from lua/ (as the game and ai-builder's util() do), the hub finds its parts beside it")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    E = L.execute("local p = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(loadfile(p, 't', e))(); return e", str(LUA_DIR / "ai-util.lua"))
    assert dict(E.PART_VERSIONS) == {n: VERSION for n in [HUB_NAME] + PARTS}, dict(E.PART_VERSIONS)
    assert E.enum_text(L.table_from({"A"}), 1) == "A" and E.GUARD_ERR == "the dig guard could not read the tile"


@test("one environment: a name swapped on the module (as a test or another module does) reaches every part; "
      "a module loaded through the prelude gets all of ai-util")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    U = L.execute("local s = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(load(s, 'ai-util', 't', e))(); return e", UTIL_SRC)
    # the helpers part's now_tick reads abs_tick (the hub's) through the module
    L.execute("local U = ...; U.abs_tick = function() return 4242 end", U)
    assert U.now_tick(0) == 4242
    # the doors part's repath reads abs_tick too
    L.execute("local U = ...; U.df = {global = {world = {reindex_pathfinding = false}}}", U)
    assert U.repath("t") is True and U.REPATH.last_tick == 4242
    # a module that takes ai-util at load (through the prelude) sees the parts' names
    M = L.execute("local s = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(load(s, 'ai-gates', 't', e))(); return e", module_src("ai-gates.lua"))
    Ug = M.reqscript("ai-util")
    assert Ug.dig_forbidden is not None and Ug.lock_door is not None and Ug.enum_name is not None
    assert dict(Ug.PART_VERSIONS) == {n: VERSION for n in [HUB_NAME] + PARTS}, dict(Ug.PART_VERSIONS)
    # the gates' own parts still load from the prelude's PART_SOURCES (its own names, not ai-util's)
    assert M.PART_VERSIONS["ai-gates-stuck"] == VERSION and M.PART_VERSIONS["ai-util"] is None


if __name__ == "__main__":
    finish()
