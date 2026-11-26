"""(r8, code health s9) lua/ai-threats.lua (105 KB) split by theme into a hub
and two parts under 60 KB each, as lua/ai-gates.lua is: the hub (the state,
the pure helpers, the reports of fire, prisoners, thieves, the undead, the
weather, werebeasts, the surface, the wounded) loads ai-threats-survey (the
cavern openings, who keeps the dwarves from drink and food, survey()) and
ai-threats-actions (fire_guard, the prisoners' room, the moon cell,
seal_cavern, the fire breathers) into its own environment. Behaviour
unchanged: the three files with the split's scaffolding taken out are the old
file's lines; loaded as the hub does, they define the same names as the text
in one piece; the file-scope locals a later part uses are handed on.

    python tests/test_r8_s9.py
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
HUB_NAME = "ai-threats"
PARTS = ["ai-threats-survey", "ai-threats-actions", "ai-threats-seal"]   # (0.105.119) -seal split off -actions
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the four files are each under 60 KB (the one was 105 KB)")
def _():
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS lists survey, actions, seal; the tests' helper reads the family (SPLIT, split_parts, split_src)")
def _():
    hub = text(HUB_NAME)
    assert re.search(r"^PARTS = \{'survey', 'actions', 'seal'\}$", hub, re.M)
    assert "ai-threats.lua" in SPLIT and split_parts("ai-threats.lua") == PARTS
    whole = split_src("ai-threats.lua")
    assert whole == "\n".join(text(n) for n in [HUB_NAME] + PARTS)
    # the hub is still the module; the loader is the last thing in it (nothing of the old file after it)
    assert re.search(r"^--@module = true$", hub, re.M)
    tail = hub[hub.index("for _, part in ipairs(PARTS) do"):]
    assert tail.rstrip("\n").endswith("    end\nend") and tail.count("\n") == 11, tail
    assert "assert(load(src, name, 't', _ENV))()" in tail and "assert(loadfile(path, 't', _ENV))()" in tail


@test("parts: each new file is a part (no module), refuses to run alone, carries its version mark; the hub its own")
def _():
    assert f"PART_VERSIONS = {{['ai-threats'] = '{VERSION}'}}" in text(HUB_NAME)
    for n in PARTS:
        src = text(n)
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert f"if not PART_LOCALS then qerror('{n} is a part of ai-threats; run ai-threats') end" in src, n
        assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'" in src, n
        assert src.count(f"'{VERSION}'") == 1, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not PART_LOCALS then qerror\('ai-threats-\w+ is a part of ai-threats; run ai-threats'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-threats-\w+'\] = '[^']+'   -- .*",
    r"local [\w, ]+ = PART_LOCALS\.\w+(, PART_LOCALS\.\w+)*   -- \((?:r8|0\.105\.119)\) .*",
    r"PART_LOCALS = \{[\w =,]+\}",
    r"PART_LOCALS\.\w+(, PART_LOCALS\.\w+)* = [\w, ]+",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
# the hub's end: the hand-over, the part list and the loader (lua/ai-gates.lua's, with this module's name)
LOADER = """PARTS = {'survey', 'actions', 'seal'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-threats'] = 'V'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-threats-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-threats: ' .. name .. '.lua is missing (it goes beside ai-threats.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
"""

# sha256 of lua/ai-threats.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "69a1d9399ec37134d5445f3822a93f8f19249e624f789295ab3594c2599959a0"
OLD_SIZE = 104688
SPLIT_VERSION = "0.105.63"


def _bodies() -> tuple[list[str], list[str]]:
    """The three files' texts without the split's scaffolding, and the lines taken out."""
    removed: list[str] = []
    hub = text(HUB_NAME)
    at = hub.index("\n-- (r8) this file's locals the later parts use")
    tail = hub[at + 1:]
    k = tail.index("PARTS = {")
    assert re.sub(r"'0\.105\.\d+'", "'V'", tail[k:]) == LOADER      # the loader, whole
    removed += tail[:k].split("\n")
    bodies = [hub[:at]]
    for n in PARTS:
        lines = text(n).split("\n")
        i = next(j for j, l in enumerate(lines) if l.startswith("local ") and " = PART_LOCALS." in l) + 1
        assert lines[i] == "", n
        removed += lines[:i + 1]
        lines = lines[i + 1:]
        t = max((j for j, l in enumerate(lines) if l.startswith(("-- (r8)", "-- (0.105.119)"))), default=None)
        if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
            removed += lines[t:]
            lines = lines[:t]
        bodies.append("\n".join(lines))
    return bodies, removed


def old_text() -> str:
    bodies, _ = _bodies()
    return "\n\n".join(b.rstrip("\n") for b in bodies) + "\n"


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file of "
      "0.105.63; what was taken out is headers, marks, guards, comments, the loader and the locals handed on")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {VERSION})")
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


@test("locals: no file uses a file-scope local another file declares without taking it in; each taken name "
      "is handed on by an earlier file, under its own name, and none is assigned again anywhere (handed by value)")
def _():
    texts = {n: text(n) for n in [HUB_NAME] + PARTS}
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
    hub = texts[HUB_NAME]
    given = re.search(r"^PART_LOCALS = \{([\w =,]+)\}$", hub, re.M).group(1)
    for pair in given.split(", "):
        a, b = pair.split(" = ")
        assert a == b and a in _top_locals(hub), pair
        handed.add(a)
    used: set[str] = set()
    for n in PARTS:
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
    assert used == handed, used ^ handed                       # nothing handed that nobody takes
    # a handed local is a function or a fixed value: no file assigns to one after its declaration
    whole = [_strip(l) for l in old_text().split("\n")]
    for name in handed:
        pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"\s*=(?!=)")
        writes = [l for l in whole if pat.search(l) and not re.match(r"^local (function )?[\w, ]*\b" + name + r"\b", l)
                  and not re.match(r"^\s+local [\w, ]*\b" + name + r"\b", l)        # a function's own local
                  and not re.search(r"[{,]\s*" + name + r"\s*=", l)]                 # a table's key
        assert not writes, (name, writes[:3])


ENV = r"""
local hub, parts, whole_src = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env.reqscript = function(n) return {name = n} end
    env.qerror = error
    return env
end
local split = fresh()
split.PART_SOURCES = parts
assert(load(hub, 'ai-threats', 't', split))()
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
local ok, err = pcall(assert(load(parts['ai-threats-survey'], 'ai-threats-survey', 't', alone)))
return keys(split, scaffold), keys(whole, scaffold), table.concat(extra, ' '), split, ok, tostring(err)
"""


@test("load: the hub with its parts defines the same names as the text in one piece (and PARTS, PART_VERSIONS, "
      "PART_LOCALS); every part marked; the locals handed on are all there; a part alone refuses to run")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, extra, env, ok, err = L.execute(ENV, text(HUB_NAME), L.table_from({n: text(n) for n in PARTS}), old_text())
    assert a == b, (set(a.split()) ^ set(b.split()))
    assert "survey:function" in a and "seal_cavern:function" in a and "fire_breath_of:function" in a, a
    assert extra == "PARTS PART_LOCALS PART_SOURCES PART_VERSIONS", extra
    assert dict(env.PART_VERSIONS) == {n: VERSION for n in [HUB_NAME] + PARTS}, dict(env.PART_VERSIONS)
    given = re.search(r"^PART_LOCALS = \{([\w =,]+)\}$", text(HUB_NAME), re.M).group(1)
    names = [p.split(" = ")[0] for p in given.split(", ")] + ["okey", "watcher_held", "lure_open_ids", "insane_held"]
    for n in names:
        assert env.PART_LOCALS[n] is not None, n
    assert len(list(env.PART_LOCALS.keys())) == len(names)
    assert not ok and "ai-threats-survey is a part of ai-threats; run ai-threats" in err, err


@test("one environment: a name swapped on the module (as a test or another module does) reaches every part")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    E = L.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                  "assert(load(src, 'ai-threats', 't', e))(); return e", module_src("ai-threats.lua"))
    # survey part -> hub's pure helpers and its own; actions part -> its own fire_job_ok
    assert E.parse_cancel("Urist, Miner cancels Drink: Interrupted by a human spearman.") is not None
    assert E.fire_job_ok("DigChannel") is True and E.fire_job_ok("Eat") is False
    # touches_zone (actions) is a module name; cluster (hub) too
    assert callable(E.touches_zone) and callable(E.cluster) and callable(E.openings_report)
    # the survey part's survey() reads load_state (the hub's) through the module: swapped, the swap is used
    L.execute("""local E = ...
        E.load_state = function() error('swapped load_state reached') end""", E)
    ok, err = L.execute("local E = ...; return pcall(E.seal_holds)", E)
    assert not ok and "swapped load_state reached" in str(err), err


if __name__ == "__main__":
    finish()
