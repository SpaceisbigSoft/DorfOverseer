"""(r8, code health s1) lua/ai-waterworks.lua (167 KB) split by theme into a hub
and three parts under 60 KB each, the ai-gates pattern: ai-waterworks.lua (the
hooks, the state, the tiles, the dry run, the far sources) loads
ai-waterworks-plans (the works' plans), ai-waterworks-power (the steps'
helpers and W7, the pump stack's power) and ai-waterworks-steps (step and the
report) into its own environment, in the old file's order. Behaviour
unchanged: the four files with the split's scaffolding taken out are the old
file's lines; loaded as the hub loads them they define the same names as the
text in one piece; the file-scope locals a later part uses are handed on in
WATERWORKS_PART_LOCALS (functions and tables never assigned again).

    python tests/test_r8_s1.py
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
HUB = "ai-waterworks"
PARTS = ["ai-waterworks-plans", "ai-waterworks-power", "ai-waterworks-steps"]
FAMILY = [HUB] + PARTS
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the four files are each under 60 KB (the one was 167 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS lists the three parts in the old file's order; the tests' helpers read the family")
def _():
    hub = text(HUB)
    assert re.search(r"^PARTS = \{'plans', 'power', 'steps'\}$", hub, re.M)
    assert "ai-waterworks.lua" in SPLIT and split_parts("ai-waterworks.lua") == PARTS
    assert split_src("ai-waterworks.lua") == "\n".join(text(n) for n in FAMILY)
    # still the module the bridge and the other modules take by name; the parts are no modules
    assert re.search(r"^--@module = true$", hub, re.M)
    # the loader stands last in the hub: nothing of the old file's after it
    assert hub.rstrip("\n").endswith("        assert(loadfile(path, 't', _ENV))()\n    end\nend")


@test("parts: each is a part (no module), refuses to run alone, carries its version mark; the hub its own")
def _():
    for n in PARTS:
        src = text(n)
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert f"if not WATERWORKS_PART_LOCALS then qerror('{n} is a part of ai-waterworks; run ai-waterworks') end" in src, n
        assert (f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'   -- (0.105.26) bumped "
                "with BRIDGE_VERSION") in src, n
        assert src.count(f"'{VERSION}'") == 1, n
    hub = text(HUB)
    assert f"PART_VERSIONS = {{['{HUB}'] = '{VERSION}'}}   -- (0.105.26) bumped with BRIDGE_VERSION" in hub
    assert hub.count(f"'{VERSION}'") == 1


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not WATERWORKS_PART_LOCALS then qerror\('ai-waterworks-\w+ is a part of ai-waterworks; run ai-waterworks'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-waterworks-\w+'\] = '[^']+'   -- .*",
    r"PART_VERSIONS = \{\['ai-waterworks'\] = '[^']+'\}   -- .*",
    r"PARTS = \{'plans', 'power', 'steps'\}",
    r"local [\w, ]+ = WATERWORKS_PART_LOCALS\.\w+(, WATERWORKS_PART_LOCALS\.\w+)*",
    r"WATERWORKS_PART_LOCALS = \{[\w =,]+\}",
    r"WATERWORKS_PART_LOCALS\.\w+(, WATERWORKS_PART_LOCALS\.\w+)* = [\w, ]+",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^local [\w, ]+ = WATERWORKS_PART_LOCALS\.[\w., ]+$")
LOADER_FROM = "local function part_path(name)"

# sha256 of lua/ai-waterworks.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "9155ebfa74db942c210ba0dd5acfe0169c79c9bd769829aa714ab44693ab19f1"
OLD_SIZE = 167104
SPLIT_VERSION = "0.105.63"


def _body(n: str, removed: list) -> str:
    """A file's text without the split's scaffolding: a part's header down to
    the locals it takes in; the "-- (r8)" block a file ends with (the hub's
    hand-over, part list and loader; the power part's hand-over). What was
    taken out goes to `removed`; the hub's loader is checked on its own."""
    lines = text(n).split("\n")
    if n != HUB:
        i = next(k for k, l in enumerate(lines) if TAKE_RE.match(l)) + 1
        assert all(not TAKE_RE.match(l) for l in lines[i:]), n
        while i < len(lines) and lines[i] == "":
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = next((k for k, l in enumerate(lines) if l.startswith("-- (r8)")), None)
    if t is not None:
        tail = lines[t:]
        if n == HUB:
            k = tail.index(LOADER_FROM)
            tail = tail[:k]                 # the loader: "hub: the loader is ai-gates' own"
        removed += tail
        lines = lines[:t]
    return "\n".join(lines)


def _whole(removed: list | None = None) -> str:
    removed = [] if removed is None else removed
    return "\n\n".join(_body(n, removed).rstrip("\n") for n in FAMILY) + "\n"


@test("hub: the loader is ai-gates' own, name for name (part_path, PART_SOURCES for the tests, load into _ENV)")
def _():
    gates, hub = text("ai-gates"), text(HUB)
    g = gates[gates.index(LOADER_FROM):].replace("ai-gates", "ai-waterworks")
    assert hub[hub.index(LOADER_FROM):] == g
    assert hub.count(LOADER_FROM) == 1


@test("unchanged: what was taken out of the four files is headers, marks, comments, the part list and the "
      "shared locals handed on; each file keeps the old file's lines in one run")
def _():
    removed = []
    whole = _whole(removed)
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    # nothing of the split's is left in what is kept
    assert "WATERWORKS_PART_LOCALS" not in whole and "PART_VERSIONS" not in whole and "(r8)" not in whole
    assert not re.search(r"^PARTS = ", whole, re.M)


@test("unchanged: the four files with the split's scaffolding taken out are, byte for byte, the one file of 0.105.63")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {VERSION})")
    whole = _whole().encode("utf-8")
    assert len(whole) == OLD_SIZE, len(whole)
    assert hashlib.sha256(whole).hexdigest() == OLD_SHA


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(src: str) -> set[str]:
    out = set()
    for l in src.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*(?:=|$)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


def _handed(src: str) -> list[str]:
    """The names a file puts into WATERWORKS_PART_LOCALS."""
    out = []
    m = re.search(r"^WATERWORKS_PART_LOCALS = \{([\w =,]+)\}$", src, re.M)
    if m:
        for pair in m.group(1).split(", "):
            k, v = pair.split(" = ")
            assert k == v, pair
            out.append(k)
    m = re.search(r"^((?:WATERWORKS_PART_LOCALS\.\w+(?:, )?)+) = ([\w, ]+)$", src, re.M)
    if m:
        keys = [k.split(".")[1] for k in m.group(1).split(", ")]
        assert keys == m.group(2).split(", "), m.group(0)
        out += keys
    return out


def _taken(src: str) -> list[str]:
    m = re.search(r"^local ([\w, ]+) = ((?:WATERWORKS_PART_LOCALS\.\w+(?:, )?)+)$", src, re.M)
    if not m:
        return []
    names = m.group(1).split(", ")
    assert [k.split(".")[1] for k in m.group(2).split(", ")] == names, m.group(0)     # each under its own name
    return names


@test("locals: no file uses a file-scope local another file declares without taking it in; what a part takes "
      "was handed on by a file loaded before it, under the same name")
def _():
    texts = {n: text(n) for n in FAMILY}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert {"key", "rock", "OWN", "BUILDER", "dug", "seg_cells", "power_wheel"} <= family, family
    handed = []
    for n in FAMILY:
        t = texts[n]
        taken = _taken(t)
        assert set(taken) <= set(handed), (n, set(taken) - set(handed))
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in sorted(family - mine):
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l) and "WATERWORKS_PART_LOCALS" not in l]
            # steps: wk.half_dug = {dug = ...}, a table's key (the local is taken in there all the same)
            assert not hits, (n, name, hits[:5])
        gives = _handed(t)
        assert set(gives) <= mine - set(taken), (n, gives)      # a file hands on its own locals only
        handed += gives
    assert len(handed) == len(set(handed)), handed


@test("locals: the ones handed on are never assigned again (a function or a table, the same object in every "
      "part); the two that are assigned again (BUILDER, OWN) stay in the file that declares them")
def _():
    texts = {n: text(n) for n in FAMILY}
    handed = [k for n in FAMILY for k in _handed(texts[n])]
    assert sorted(handed) == sorted(["OPEN", "key", "rock", "cavern_tile", "ground", "still_water", "l_path", "N4",
                                     "N8", "wet_beside", "seg_cells", "dug", "designate_all", "undug",
                                     "left_to_dig", "leak", "depth_at"]), handed
    for n, t in texts.items():
        for i, l in enumerate(t.split("\n"), 1):
            c = _strip(l)
            for name in handed:
                # an assignment to the bare name at any depth (not a field, not a table's key = value,
                # not its own declaration)
                if re.search(r"(?<![\w.:{,] )(?<![\w.:{(])" + re.escape(name) + r"\s*=[^=]", c) \
                        and not re.match(r"^local (function )?", c) and "WATERWORKS_PART_LOCALS" not in c \
                        and not re.search(r"[{,]\s*" + re.escape(name) + r"\s*=", c) \
                        and not re.match(r"^\s+" + re.escape(name) + r" = .*,$", c):
                    raise AssertionError((n, i, l))
    for name, home in (("BUILDER", HUB), ("OWN", "ai-waterworks-power")):
        pat = re.compile(r"(?<![\w.:])" + name + r"(?!\w)")
        for n, t in texts.items():
            used = any(pat.search(_strip(l)) for l in t.split("\n"))
            assert used == (n == home), (name, n)


ENV = r"""
local hub_src, part_srcs, part_names, whole_src, lua_dir = ...
local function fresh()
    local env = setmetatable({qerror = error}, {__index = _G})
    env.dfhack = {persistent = {saveSiteData = function() end, getSiteData = function(k, d) return d end}}
    return env
end
-- as the tests load it: the hub from its text, the parts' texts in PART_SOURCES
local split = fresh()
split.PART_SOURCES = {}
for i = 1, #part_names do split.PART_SOURCES[part_names[i]] = part_srcs[i] end
assert(load(hub_src, 'ai-waterworks', 't', split))()
-- as the game loads it: the hub from its file, the parts from the files beside it
local filed = fresh()
assert(loadfile(lua_dir .. '/ai-waterworks.lua', 't', filed))()
-- the old text in one piece
local whole = fresh()
assert(load(whole_src, 'whole', 't', whole))()
local SCAFFOLD = {PARTS = true, PART_VERSIONS = true, PART_SOURCES = true, WATERWORKS_PART_LOCALS = true}
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if not SCAFFOLD[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
local function values(e)        -- the settings (numbers, strings, booleans), by name
    local o = {}
    for k, v in pairs(e) do
        if type(v) ~= 'function' and type(v) ~= 'table' then o[#o + 1] = k .. '=' .. tostring(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
return keys(split), keys(filed), keys(whole), values(split), values(whole), split, filed
"""


@test("load: the hub with its parts (from texts as the tests do, from the files as the game does) defines the "
      "same names as the old text in one piece; every part marked; the shared locals are one set of objects")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, f, b, va, vb, env, filed = L.execute(ENV, text(HUB), L.table_from([text(n) for n in PARTS]),
                                            L.table_from(PARTS), _whole(), str(LUA_DIR).replace("\\", "/"))
    assert a == b and f == b, sorted(set(a.split()) ^ set(b.split()))
    assert va == vb
    g = set(a.split())
    for fn in ("T", "occupants", "designate", "building", "load_state", "save_state", "bypass", "far_route_check",
               "path_check", "far_sources", "stage_plan", "lever_spot", "plan_moat", "plan_pump", "cistern_feed",
               "plan_irrigation", "plan_magma", "plan_power", "power_step", "step", "report"):
        assert f"{fn}:function" in g, fn
    for tbl in ("KINDS", "MAGMA_SHOPS", "PLANNERS", "FAR", "MAGMA_RANK", "MAGMA_PARTS"):
        assert f"{tbl}:table" in g, tbl
    same = L.eval('rawequal')
    for e in (env, filed):
        assert dict(e.PART_VERSIONS) == {n: VERSION for n in FAMILY}, dict(e.PART_VERSIONS)
        assert list(e.PARTS.values()) == ["plans", "power", "steps"]
        # PLANNERS (plans) holds the plans' own functions, defined in the hub's environment
        assert same(e.PLANNERS.moat, e.plan_moat) and same(e.PLANNERS.magma, e.plan_magma)
        shared = e.WATERWORKS_PART_LOCALS
        assert len(list(shared.keys())) == 17
        assert shared.key(1, 2, 3) == "1,2,3"
        assert shared.OPEN.EMPTY is True and len(shared.N4) == 4 and len(shared.N8) == 8
    # a part run alone refuses
    try:
        L.execute("local src = ...; local e = setmetatable({qerror = error}, {__index = _G}); "
                  "assert(load(src, 'p', 't', e))()", text(PARTS[0]))
        raise AssertionError("ran alone")
    except Exception as e:  # noqa: BLE001
        assert "is a part of ai-waterworks; run ai-waterworks" in str(e), e


@test("load: a part missing beside the hub is said by name; a test's swap of a hub's hook reaches the parts")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    try:
        L.execute("local src = ...; local e = setmetatable({dfhack = {}}, {__index = _G}); "
                  "assert(load(src, 'ai-waterworks', 't', e))()", text(HUB))
        raise AssertionError("loaded without its parts")
    except Exception as e:  # noqa: BLE001
        assert "ai-waterworks-plans.lua is missing (it goes beside ai-waterworks.lua)" in str(e), e
    # module_src: the hub's text with the parts' texts before its first line (its line numbers kept)
    env = L.execute("local src = ...; local e = setmetatable({dfhack = {persistent = {"
                    "saveSiteData = function() end, getSiteData = function(k, d) return d end}}}, {__index = _G}); "
                    "assert(load(src, 'ai-waterworks', 't', e))(); return e", module_src("ai-waterworks.lua"))
    # step (ai-waterworks-steps) reads KINDS and load_state (the hub's) through the one environment
    r = env.step("nosuch")
    assert r.rejected and "unknown kind nosuch" in r.error, r.error
    env.KINDS = L.table_from({"nosuch": True})
    env.load_state = L.eval("function() error('swapped') end")
    try:
        env.step("nosuch")
        raise AssertionError("the swap did not reach the part")
    except Exception as e:  # noqa: BLE001
        assert "swapped" in str(e), e


@test("names: the bridge's module list still names ai-waterworks once; no other Lua file names a part")
def _():
    listed = re.search(r"^BRIDGE_MODULES = \{(.*?)^\}", BRIDGE, re.M | re.S).group(1)
    assert listed.count("'ai-waterworks'") == 1
    for p in LUA_DIR.rglob("*.lua"):
        if p.stem in FAMILY:
            continue
        src = p.read_text(encoding="utf-8")
        for n in PARTS:
            assert n not in src, (p.name, n)


if __name__ == "__main__":
    finish()
