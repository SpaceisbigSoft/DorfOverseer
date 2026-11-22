"""(r9, code health t6) two standalone modules split by theme into a hub and
parts under 60 KB each, as lua/ai-gates.lua is (and round 8's ai-threats):

  * lua/ai-trade.lua (77 KB): the hub (caravans, the goods for the depot,
    survey, bring, unload, the automatic deal) loads ai-trade-screen (the
    trade screen's buttons pressed, the caravans done, the screen opened) and
    ai-trade-depot (someone called to the depot, the probe);
  * lua/ai-homes.lua (63 KB): the hub (the census, the citizens' taste,
    placement, house) loads ai-homes-furnish (rooms furnished in what the
    dwarf likes, the report's citizens_taste).

Two separate proofs, one for each module. Behaviour unchanged: the files with
the split's scaffolding taken out are the old file's lines (sha256 + size of
the file at 0.105.64, 8183548); loaded as the hub does, they define the same
names as the text in one piece; the file-scope locals a later part uses are
handed on.

    python tests/test_r9_t6.py
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
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)
SPLIT_VERSION = "0.105.64"

# each module: its parts, and the sha256 + size of the one file at 0.105.64 (8183548)
MODULES = {
    "ai-trade": {"parts": ["screen", "depot"],
                 "sha": "e898085680fcaf0a924f4582bddd24334f41eec7eec004c504eaad8e3091f47c", "size": 76894,
                 "was": 76894},
    "ai-homes": {"parts": ["furnish"],
                 "sha": "25d369ebeed9335d0c716a4c7ff9eec6bd94a042e5fcbd8ea01d10d10b92402a", "size": 63144,
                 "was": 63144},
}


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


def parts_of(hub: str) -> list[str]:
    return [f"{hub}-{p}" for p in MODULES[hub]["parts"]]


def scaffold_re(hub: str) -> re.Pattern:
    h = re.escape(hub)
    pats = [
        r"",
        r"--.*",
        rf"if not PART_LOCALS then qerror\('{h}-\w+ is a part of {h}; run {h}'\) end",
        rf"PART_VERSIONS = PART_VERSIONS or \{{\}}; PART_VERSIONS\['{h}-\w+'\] = '[^']+'   -- .*",
        r"local [\w, ]+ = PART_LOCALS\.\w+(, PART_LOCALS\.\w+)*   -- \(r9\) .*",
        r"PART_LOCALS = \{[\w =,]+\}",
        r"PART_LOCALS\.\w+(, PART_LOCALS\.\w+)* = [\w, ]+",
    ]
    return re.compile("^(?:" + "|".join(pats) + ")$")


def loader(hub: str) -> str:
    plist = ", ".join(f"'{p}'" for p in MODULES[hub]["parts"])
    return f"""PARTS = {{{plist}}}
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
    """The files' texts without the split's scaffolding, and the lines taken out."""
    removed: list[str] = []
    src = text(hub)
    at = src.index("\n-- (r9) this file's locals the later parts use")
    tail = src[at + 1:]
    k = tail.index("PARTS = {")
    assert re.sub(r"'0\.105\.\d+'", "'V'", tail[k:]) == loader(hub)      # the loader, whole
    removed += tail[:k].split("\n")
    bodies = [src[:at]]
    sre = scaffold_re(hub)
    for n in parts_of(hub):
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


ENV = r"""
local hub_name, first_part, hub, parts, whole_src = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env.reqscript = function(n) return {name = n} end
    env.require = function() return {} end
    env.qerror = error
    return env
end
local split = fresh()
split.PART_SOURCES = parts
assert(load(hub, hub_name, 't', split))()
local whole = fresh()
assert(load(whole_src, 'whole', 't', whole))()
local function keys(e, skip)
    local o = {}
    for k, v in pairs(e) do
        if not skip[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
local scaffold = {PART_SOURCES = true, PARTS = true, PART_VERSIONS = true, PART_LOCALS = true}
local extra = {}
for k in pairs(scaffold) do if split[k] ~= nil then extra[#extra + 1] = k end end
table.sort(extra)
-- a part run alone refuses
local alone = fresh()
local ok, err = pcall(assert(load(parts[first_part], first_part, 't', alone)))
return keys(split, scaffold), keys(whole, scaffold), table.concat(extra, ' '), split, ok, tostring(err)
"""


def make_tests(hub: str, names_expected: list[str]) -> None:
    parts = parts_of(hub)
    plist = ", ".join(f"'{p}'" for p in MODULES[hub]["parts"])

    @test(f"{hub}: sizes: the {1 + len(parts)} files are each under 60 KB (the one was {MODULES[hub]['was'] // 1024} KB)")
    def _():
        for n in [hub] + parts:
            size = (LUA_DIR / f"{n}.lua").stat().st_size
            assert size < 60 * 1024, (n, size)

    @test(f"{hub}: the hub's PARTS lists {plist} in order; the tests' helper reads the family (SPLIT, split_parts, split_src)")
    def _():
        src = text(hub)
        assert re.search(r"^PARTS = \{" + re.escape(plist) + r"\}$", src, re.M)
        assert f"{hub}.lua" in SPLIT and split_parts(f"{hub}.lua") == parts
        assert split_src(f"{hub}.lua") == "\n".join(text(n) for n in [hub] + parts)
        assert re.search(r"^--@module = true$", src, re.M)
        tail = src[src.index("for _, part in ipairs(PARTS) do"):]
        assert tail.rstrip("\n").endswith("    end\nend") and tail.count("\n") == 11, tail

    @test(f"{hub}: each new file is a part (no module), refuses to run alone, carries its version mark; the hub its own")
    def _():
        assert f"PART_VERSIONS = {{['{hub}'] = '{VERSION}'}}" in text(hub)
        assert text(hub).count(f"'{VERSION}'") == 1
        for n in parts:
            src = text(n)
            assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
            assert f"if not PART_LOCALS then qerror('{n} is a part of {hub}; run {hub}') end" in src, n
            assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'" in src, n
            assert src.count(f"'{VERSION}'") == 1, n

    @test(f"{hub}: unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file "
          f"of {SPLIT_VERSION}; what was taken out is headers, marks, guards, comments, the loader and the locals handed on")
    def _():
        if VERSION != SPLIT_VERSION:
            skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
        _, removed = _bodies(hub)
        whole = old_text(hub).encode("utf-8")
        assert len(whole) == MODULES[hub]["size"], len(whole)
        assert hashlib.sha256(whole).hexdigest() == MODULES[hub]["sha"]
        sre = scaffold_re(hub)
        bad = [l for l in removed if not sre.match(l)]
        assert not bad, bad

    @test(f"{hub}: locals: no file uses a file-scope local another declares without taking it in; each taken "
          "name is handed on by an earlier file under its own name, and none is assigned again (handed by value)")
    def _():
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
        assert used == handed, used ^ handed
        whole = [_strip(l) for l in old_text(hub).split("\n")]
        for name in handed:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"\s*=(?!=)")
            writes = [l for l in whole if pat.search(l)
                      and not re.match(r"^local (function )?[\w, ]*\b" + name + r"\b", l)
                      and not re.match(r"^\s+local [\w, ]*\b" + name + r"\b", l)
                      and not re.search(r"[{,]\s*" + name + r"\s*=", l)]
            assert not writes, (name, writes[:3])

    @test(f"{hub}: load: the hub with its parts defines the same names as the text in one piece (and PARTS, "
          "PART_VERSIONS, PART_LOCALS); every part marked; the locals handed on are there; a part alone refuses")
    def _():
        need_lua()
        from lupa.lua53 import LuaRuntime
        L = LuaRuntime(unpack_returned_tuples=True)
        a, b, extra, env, ok, err = L.execute(ENV, hub, parts[0], text(hub),
                                              L.table_from({n: text(n) for n in parts}), old_text(hub))
        assert a == b, (set(a.split()) ^ set(b.split()))
        for nm in names_expected:
            assert nm + ":function" in a, nm
        assert extra == "PARTS PART_LOCALS PART_SOURCES PART_VERSIONS", extra
        assert dict(env.PART_VERSIONS) == {n: VERSION for n in [hub] + parts}, dict(env.PART_VERSIONS)
        given = re.search(r"^PART_LOCALS = \{([\w =,]+)\}$", text(hub), re.M).group(1)
        names = [p.split(" = ")[0] for p in given.split(", ")]
        for n in names:
            assert env.PART_LOCALS[n] is not None, n
        assert len(list(env.PART_LOCALS.keys())) == len(names)
        assert not ok and f"{parts[0]} is a part of {hub}; run {hub}" in err, err


make_tests("ai-trade", ["survey", "deal", "press", "open_screen", "call_trader", "probe_screen"])
make_tests("ai-homes", ["census", "house", "taste_of", "furnish_plan", "furnish_liked", "citizens_taste"])


@test("ai-trade: one environment: a name swapped on the module reaches every part")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    E = L.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(load(src, 'ai-trade', 't', e))(); return e", module_src("ai-trade.lua"))
    assert callable(E.press) and callable(E.open_screen) and callable(E.call_trader) and callable(E.probe_screen)
    # the depot part's call_trader and probe_screen, the screen part's buttons: module names; the hub's survey too
    L.execute("""local E = ...
        E.buttons = function() error('swapped buttons reached') end""", E)
    ok, err = L.execute("local E = ...; return pcall(E.probe_screen, false)", E)
    assert not ok and "swapped buttons reached" in str(err), err


@test("ai-homes: one environment: a name swapped on the module reaches the part")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    E = L.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(load(src, 'ai-homes', 't', e))(); return e", module_src("ai-homes.lua"))
    assert callable(E.furnish_plan) and callable(E.citizens_taste) and callable(E.census)
    # the furnish part's citizen_tastes reads the hub's taste_of through the module: swapped, the swap is used
    L.execute("""local E = ...
        E.taste_of = function() error('swapped taste_of reached') end""", E)
    ok, err = L.execute("local E = ...; return pcall(E.citizen_tastes, {{id = 1}})", E)
    assert not ok and "swapped taste_of reached" in str(err), err


if __name__ == "__main__":
    finish()
