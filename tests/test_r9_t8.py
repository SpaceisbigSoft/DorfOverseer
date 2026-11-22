"""(r9, code health t8) lua/ai-blueprints.lua (74 KB) and lua/ai-layouts.lua
(68 KB) split by theme into a hub and parts under 60 KB each, as
lua/ai-gates.lua is:

- ai-blueprints (the format, its tables, the cell helpers, cost, the openings'
  order, check_format) loads ai-blueprints-translate (rotate, one_zone,
  to_layouts) and ai-blueprints-stages (E2: build_stages, the surface build
  order with scaffolding) into its own environment;
- ai-layouts (the kinds' tables, the shared helpers, the hall shapes and
  motifs, the hall in the making, decorate, orient_layout) loads
  ai-layouts-kinds (the hub round the stair, the rooms off it, every kind,
  make, tiles_from_dig, to_data).

Neither holds a table literal anywhere near 60 KB: both cut at section
boundaries. Behaviour unchanged: each family with the split's scaffolding taken
out is the old file's lines (two proofs, one per file, against 0.105.64 at
8183548); loaded as the hub does, it defines the same names as the text in one
piece; the file-scope locals a later part uses are handed on.

    python tests/test_r9_t8.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import SPLIT, split_parts, split_src, module_src  # noqa: E402

LUA_DIR = ROOT / "lua"
FAMILIES = {"ai-blueprints": ["ai-blueprints-translate", "ai-blueprints-stages"],
            "ai-layouts": ["ai-layouts-kinds"]}
PART_LIST = {"ai-blueprints": "{'translate', 'stages'}", "ai-layouts": "{'kinds'}"}
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)

# sha256 and size of each file at 0.105.64 (8183548), the last commit with it in one file
OLD = {"ai-blueprints": ("3ddc34c5159ad6adf80e3d72dad89b18be0ada893303aec277e1bfd933d8f15b", 73648),
       "ai-layouts": ("20d48d1fbb3ce3d8071fb0d8ae5c20dd53f06cb33245226685118a6ea5022f44", 67995)}
SPLIT_VERSION = "0.105.64"


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: every file of the two families is under 60 KB (the two were 74 and 68 KB)")
def _():
    for hub, parts in FAMILIES.items():
        for n in [hub] + parts:
            size = (LUA_DIR / f"{n}.lua").stat().st_size
            assert size < 60 * 1024, (n, size)


@test("hubs: PARTS lists the parts in order; the tests' helper reads each family (SPLIT, split_parts, split_src)")
def _():
    for hub, parts in FAMILIES.items():
        src = text(hub)
        assert re.search(r"^PARTS = " + re.escape(PART_LIST[hub]) + "$", src, re.M), hub
        assert f"{hub}.lua" in SPLIT and split_parts(f"{hub}.lua") == parts, hub
        assert split_src(f"{hub}.lua") == "\n".join(text(n) for n in [hub] + parts)
        # still the module; the loader is the last thing in it (nothing of the old file after it)
        assert re.search(r"^--@ module = true$", src, re.M), hub
        tail = src[src.index("for _, part in ipairs(PARTS) do"):]
        assert tail.rstrip("\n").endswith("    end\nend") and tail.count("\n") == 11, (hub, tail)
        assert "assert(load(src, name, 't', _ENV))()" in tail and "assert(loadfile(path, 't', _ENV))()" in tail


@test("parts: each new file is a part (no module), refuses to run alone, carries its version mark; the hub its own")
def _():
    for hub, parts in FAMILIES.items():
        assert f"PART_VERSIONS = {{['{hub}'] = '{VERSION}'}}" in text(hub), hub
        for n in parts:
            src = text(n)
            assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
            assert f"if not PART_LOCALS then qerror('{n} is a part of {hub}; run {hub}') end" in src, n
            assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'" in src, n
            assert src.count(f"'{VERSION}'") == 1, n


def scaffold_re(hub: str) -> re.Pattern:
    h = re.escape(hub)
    return re.compile("^(?:" + "|".join([
        r"",
        r"--.*",
        rf"if not PART_LOCALS then qerror\('{h}-\w+ is a part of {h}; run {h}'\) end",
        rf"PART_VERSIONS = PART_VERSIONS or \{{\}}; PART_VERSIONS\['{h}-\w+'\] = '[^']+'   -- .*",
        r"local [\w, ]+ = PART_LOCALS\.\w+(, PART_LOCALS\.\w+)*   -- \(r9\) .*",
        r"PART_LOCALS = \{[\w =,]+\}",
        r"PART_LOCALS\.\w+(, PART_LOCALS\.\w+)* = [\w, ]+",
    ]) + ")$")


def loader(hub: str) -> str:
    """The hub's end: the part list and the loader (lua/ai-gates.lua's, with this module's name)."""
    return f"""PARTS = {PART_LIST[hub]}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {{['{hub}'] = 'V'}}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = '{hub}-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('{hub}: ' .. name .. '.lua is missing (it goes beside {hub}.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
"""


def _bodies(hub: str) -> tuple[list[str], list[str]]:
    """A family's texts without the split's scaffolding, and the lines taken out."""
    sre = scaffold_re(hub)
    removed: list[str] = []
    src = text(hub)
    at = src.index("\n-- (r9) this file's locals the later parts use")
    tail = src[at + 1:]
    k = tail.index("PARTS = {")
    assert re.sub(r"'0\.105\.\d+'", "'V'", tail[k:]) == loader(hub), hub     # the loader, whole
    removed += tail[:k].split("\n")
    bodies = [src[:at]]
    for n in FAMILIES[hub]:
        lines = text(n).split("\n")
        i = next(j for j, l in enumerate(lines) if l.startswith("local ") and " = PART_LOCALS." in l) + 1
        assert lines[i] == "", n
        removed += lines[:i + 1]
        lines = lines[i + 1:]
        t = max((j for j, l in enumerate(lines) if l.startswith("-- (r9)")), default=None)
        if t is not None and all(sre.match(l) for l in lines[t:]):
            removed += lines[t:]
            lines = lines[:t]
        bodies.append("\n".join(lines))
    return bodies, removed


def old_text(hub: str) -> str:
    bodies, _ = _bodies(hub)
    return "\n\n".join(b.rstrip("\n") for b in bodies) + "\n"


def _proof(hub: str) -> None:
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
    _, removed = _bodies(hub)
    whole = old_text(hub).encode("utf-8")
    sha, size = OLD[hub]
    assert len(whole) == size, (hub, len(whole))
    assert hashlib.sha256(whole).hexdigest() == sha, hub
    bad = [l for l in removed if not scaffold_re(hub).match(l)]
    assert not bad, bad


@test("unchanged (1): ai-blueprints and its two parts with the split's scaffolding taken out are, byte for byte, "
      "the one file of 0.105.64; what was taken out is headers, marks, guards, comments, the loader, the locals handed on")
def _():
    _proof("ai-blueprints")


@test("unchanged (2): ai-layouts and its part with the split's scaffolding taken out are, byte for byte, "
      "the one file of 0.105.64; what was taken out is headers, marks, guards, comments, the loader, the locals handed on")
def _():
    _proof("ai-layouts")


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


@test("locals: no file uses a file-scope local another file of its family declares without taking it in; each "
      "taken name is handed on by an earlier file, under its own name, and none is assigned again (handed by value)")
def _():
    for hub, parts in FAMILIES.items():
        texts = {n: text(n) for n in [hub] + parts}
        family = set().union(*(_top_locals(t) for t in texts.values())) - {"part_path"}
        for n, t in texts.items():
            mine = _top_locals(t)
            code = [_strip(l) for l in t.split("\n")]
            for name in family - mine:
                pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
                hits = [i for i, l in enumerate(code, 1) if pat.search(l)
                        and not re.match(r"^\s*(PART_LOCALS = \{|PART_LOCALS\.)", l)]
                assert not hits, (n, name, hits[:5])
        handed: set[str] = set()
        given = re.search(r"^PART_LOCALS = \{([\w =,]+)\}$", texts[hub], re.M).group(1)
        for pair in given.split(", "):
            a, b = pair.split(" = ")
            assert a == b and a in _top_locals(texts[hub]), pair
            handed.add(a)
        used: set[str] = set()
        for n in parts:
            t = texts[n]
            take = re.search(r"^local ([\w, ]+) = (PART_LOCALS\.[\w., ]+?)   -- ", t, re.M)
            names, froms = take.group(1).split(", "), take.group(2).split(", ")
            assert froms == ["PART_LOCALS." + x for x in names], n
            assert set(names) <= handed, (n, set(names) - handed)
            used |= set(names)
            give = re.search(r"^(PART_LOCALS\.[\w., ]+) = ([\w, ]+)$", t, re.M)
            if give:
                a, b = give.group(1).split(", "), give.group(2).split(", ")
                assert a == ["PART_LOCALS." + x for x in b] and set(b) <= _top_locals(t), n
                handed |= set(b)
        assert used == handed, (hub, used ^ handed)                 # nothing handed that nobody takes
        whole = [_strip(l) for l in old_text(hub).split("\n")]
        for name in handed:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"\s*=(?!=)")
            writes = [l for l in whole if pat.search(l)
                      and not re.match(r"^local (function )?[\w, ]*\b" + name + r"\b", l)
                      and not re.match(r"^\s+local [\w, ]*\b" + name + r"\b", l)         # a function's own local
                      and not re.search(r"[{,]\s*" + name + r"\s*=", l)]                  # a table's key
            assert not writes, (hub, name, writes[:3])


ENV = r"""
local hub_name, hub, parts, whole_src, lay_split, lay_whole, first = ...
local function fresh(lay)
    local env = setmetatable({}, {__index = _G})
    env.reqscript = function(n) if n == 'ai-layouts' and lay then return lay end error('reqscript ' .. n) end
    env.qerror = error
    return env
end
local split = fresh(lay_split)
split.PART_SOURCES = parts
assert(load(hub, hub_name, 't', split))()
local whole = fresh(lay_whole)
assert(load(whole_src, 'whole', 't', whole))()
local scaffold = {PART_SOURCES = true, PARTS = true, PART_VERSIONS = true, PART_LOCALS = true}
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if not scaffold[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
local extra = {}
for k in pairs(scaffold) do if split[k] ~= nil then extra[#extra + 1] = k end end
table.sort(extra)
local alone = fresh(lay_split)
local ok, err = pcall(assert(load(parts[first], first, 't', alone)))
return keys(split), keys(whole), table.concat(extra, ' '), split, whole, ok, tostring(err)
"""


@test("load: each hub with its parts defines the same names as the text in one piece (and PARTS, PART_VERSIONS, "
      "PART_LOCALS); every part marked; a part alone refuses to run; the two give the same layouts and checks")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    lay = {}
    for hub in ("ai-layouts", "ai-blueprints"):
        parts = FAMILIES[hub]
        a, b, extra, env, whole, ok, err = L.execute(
            ENV, hub, text(hub), L.table_from({n: text(n) for n in parts}), old_text(hub),
            lay.get("split"), lay.get("whole"), parts[0])
        assert a == b, (hub, set(a.split()) ^ set(b.split()))
        assert extra == "PARTS PART_LOCALS PART_SOURCES PART_VERSIONS", extra
        assert dict(env.PART_VERSIONS) == {n: VERSION for n in [hub] + parts}, dict(env.PART_VERSIONS)
        assert not ok and f"{parts[0]} is a part of {hub}; run {hub}" in err, err
        if hub == "ai-layouts":
            lay = {"split": env, "whole": whole}
            assert "make:function" in a and "hall_mask:function" in a and "to_data:function" in a, a
            same = L.eval("""function(A, B)
                local function dump(v, out)
                    if type(v) ~= 'table' then out[#out + 1] = tostring(v) return end
                    local ks = {}
                    for k in pairs(v) do ks[#ks + 1] = k end
                    table.sort(ks, function(x, y) return tostring(x) < tostring(y) end)
                    for _, k in ipairs(ks) do out[#out + 1] = tostring(k) .. '='; dump(v[k], out) end
                end
                local n = 0
                for _, kind in ipairs(A.KINDS) do
                    for _, st in ipairs({false, {hall = 'nave', arms = 'ring', motif = {form = 'star'}, smooth = 3, orient = 2}}) do
                        local a, b = {}, {}
                        dump(A.make(kind, {style = st or nil}), a); dump(B.make(kind, {style = st or nil}), b)
                        if table.concat(a, ',') ~= table.concat(b, ',') then return kind end
                        n = n + 1
                    end
                end
                return n end""")(env, whole)
            assert isinstance(same, int) and same >= 10, same
        else:
            assert "check_format:function" in a and "to_layouts:function" in a and "build_stages:function" in a, a


@test("one environment: a name swapped on the module (as a test or another module does) reaches every part")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    LAY = L.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                    "assert(load(src, 'ai-layouts', 't', e))(); return e", module_src("ai-layouts.lua"))
    # make() (the kinds part) reaches the hub's scaled through the module: swapped, the swap is used
    assert LAY.make("dining", L.table_from({"tables": 8})) is not None
    L.execute("local E = ...; E.scaled = function() error('swapped scaled reached') end", LAY)
    ok, err = L.execute("local E = ...; return pcall(E.make, 'dining', {tables = 8})", LAY)
    assert not ok and "swapped scaled reached" in str(err), err
    BP = L.execute("local src, lay = ...; local e = setmetatable({reqscript = function() return lay end}, "
                   "{__index = _G}); assert(load(src, 'ai-blueprints', 't', e))(); return e",
                   module_src("ai-blueprints.lua"), LAY)
    # translate's to_layouts calls the hub's check_format and cost through the module
    L.execute("local E = ...; E.check_format = function() error('swapped check_format reached') end", BP)
    ok, err = L.execute("local E = ...; return pcall(E.to_layouts, {}, 0)", BP)
    assert not ok and "swapped check_format reached" in str(err), err


if __name__ == "__main__":
    finish()
