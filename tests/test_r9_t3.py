"""(r9, code health 13c, t3) lua/ai-military-gear.lua (85 KB) split by theme
into a hub and four parts under 60 KB each, the ai-gates pattern:
ai-military-gear.lua (the metals, the claim sets, stray gear, weapons handed
out, gear_report) loads ai-military-gear-why (why an entry stays empty),
-ammo (quivers, flasks, ammunition, bolts), -fixes (fix_gear_gaps, spares
unforbidden) and -kit (the armour slots, army_gear) into its own environment,
in the old file's order. Behaviour unchanged: the five files with the split's
scaffolding taken out are the old file's lines (the hub's version mark moved
from its top to the part list, as ai-gates has it); loaded as the hub loads
them they define the same names as the text in one piece; the file-scope
locals a later part uses are handed on in GEAR_PART_LOCALS (functions and
module tables never assigned again). ai-military-gear stays the COMPANION of
ai-military (tests/lua_modules_util.py): the prelude feeds the companion's
parts too, and every name is still reqscript('ai-military-gear').<name> and
ai-military's through its forwarders.

    python tests/test_r9_t3.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import COMPANIONS, SPLIT, split_parts, split_src, module_src, prelude  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB = "ai-military-gear"
PARTS = ["ai-military-gear-why", "ai-military-gear-ammo", "ai-military-gear-fixes", "ai-military-gear-kit"]
FAMILY = [HUB] + PARTS
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)
PL = "GEAR_PART_LOCALS"


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the five files are each under 60 KB (the one was 85 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS lists the four parts in the old file's order; the tests' helpers read the family; still "
      "ai-military's companion")
def _():
    hub = text(HUB)
    assert re.search(r"^PARTS = \{'why', 'ammo', 'fixes', 'kit'\}$", hub, re.M)
    assert "ai-military-gear.lua" in SPLIT and split_parts("ai-military-gear.lua") == PARTS
    assert split_src("ai-military-gear.lua") == "\n".join(text(n) for n in FAMILY)
    assert COMPANIONS["ai-military.lua"] == ["ai-military-gear"]
    # the prelude of ai-military (and of the gear itself) hands the gear's parts' texts in PART_SOURCES
    for name in ("ai-military.lua", "ai-military-gear.lua"):
        pre = prelude(name)
        assert pre.startswith("PART_SOURCES = {"), name
        for n in PARTS:
            assert f'["{n}"] = ' in pre, (name, n)
    assert re.search(r"^--@module = true$", hub, re.M)
    # the loader stands last in the hub: nothing of the old file's after it
    assert hub.rstrip("\n").endswith("        assert(loadfile(path, 't', _ENV))()\n    end\nend")


@test("parts: each is a part (no module), refuses to run alone, carries its version mark; the hub its own")
def _():
    for n in PARTS:
        src = text(n)
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert f"if not {PL} then qerror('{n} is a part of ai-military-gear; run ai-military-gear') end" in src, n
        assert (f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'   -- (0.105.26) bumped "
                "with BRIDGE_VERSION") in src, n
        assert src.count(f"'{VERSION}'") == 1, n
    hub = text(HUB)
    assert f"PART_VERSIONS = {{['{HUB}'] = '{VERSION}'}}   -- (0.105.26) bumped with BRIDGE_VERSION" in hub
    assert hub.count(f"'{VERSION}'") == 1


SCAFFOLD = [
    r"",
    r"--.*",
    rf"if not {PL} then qerror\('ai-military-gear-\w+ is a part of ai-military-gear; run ai-military-gear'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-military-gear-\w+'\] = '[^']+'   -- .*",
    r"PART_VERSIONS = \{\['ai-military-gear'\] = '[^']+'\}   -- .*",
    r"PARTS = \{'why', 'ammo', 'fixes', 'kit'\}",
    rf"local [\w, ]+ = {PL}\.\w+(, {PL}\.\w+)*   -- .*",
    rf"{PL} = \{{[\w =,]+\}}",
    rf"{PL}\.\w+(, {PL}\.\w+)* = [\w, ]+",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(rf"^local [\w, ]+ = {PL}\.[\w., ]+   -- .*$")
LOADER_FROM = "local function part_path(name)"
# the old file's line 11, the hub's mark (now beside PARTS, ai-gates' way: started afresh at each load)
OLD_MARK = "PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear'] = '%s'   -- (0.105.26) bumped " \
           "with BRIDGE_VERSION"

# sha256 of lua/ai-military-gear.lua at 0.105.64 (8183548), the last commit with it in one file
OLD_SHA = "bbedd22381e2de7c7c128013aaded46607cf69a36207483b7bcd28ced3b25a6b"
OLD_SIZE = 85313
SPLIT_VERSION = "0.105.64"


def _body(n: str, removed: list) -> str:
    """A file's text without the split's scaffolding: a part's header down to
    the locals it takes in; the "-- (r8)" block a file ends with (the hub's
    hand-over, part list, mark and loader; the why part's hand-over). What was
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
            tail = tail[:tail.index(LOADER_FROM)]      # the loader: "hub: the loader is ai-gates' own"
        removed += tail
        lines = lines[:t]
    if n == HUB:
        assert lines[9].startswith("local M = reqscript('ai-military')"), lines[9]
        lines.insert(10, OLD_MARK % VERSION)
    return "\n".join(lines)


def _whole(removed: list | None = None) -> str:
    removed = [] if removed is None else removed
    return "\n\n".join(_body(n, removed).rstrip("\n") for n in FAMILY) + "\n"


@test("hub: the loader is ai-gates' own, name for name (part_path, PART_SOURCES for the tests, load into _ENV)")
def _():
    gates, hub = text("ai-gates"), text(HUB)
    g = gates[gates.index(LOADER_FROM):].replace("ai-gates", "ai-military-gear")
    assert hub[hub.index(LOADER_FROM):] == g
    assert hub.count(LOADER_FROM) == 1


@test("unchanged: what was taken out of the five files is headers, marks, comments, the part list and the "
      "shared locals handed on; each file keeps the old file's lines in one run")
def _():
    removed = []
    whole = _whole(removed)
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    assert PL not in whole and "(r8)" not in whole
    assert whole.count("PART_VERSIONS") == 3          # only the old line 11 (put back for the proof)
    assert not re.search(r"^PARTS = ", whole, re.M)


@test("unchanged: the five files with the split's scaffolding taken out are, byte for byte, the one file of 0.105.64")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
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
    """The names a file puts into GEAR_PART_LOCALS."""
    out = []
    m = re.search(rf"^{PL} = \{{([\w =,]+)\}}$", src, re.M)
    if m:
        for pair in m.group(1).split(", "):
            k, v = pair.split(" = ")
            assert k == v, pair
            out.append(k)
    m = re.search(rf"^((?:{PL}\.\w+(?:, )?)+) = ([\w, ]+)$", src, re.M)
    if m:
        keys = [k.split(".")[1] for k in m.group(1).split(", ")]
        assert keys == m.group(2).split(", "), m.group(0)
        out += keys
    return out


def _taken(src: str) -> list[str]:
    m = re.search(rf"^local ([\w, ]+) = ((?:{PL}\.\w+(?:, )?)+)   -- ", src, re.M)
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
    assert {"U", "M", "fort_squads", "memo", "item_stage", "danger_spots", "glove_side"} <= family, family
    handed = []
    for n in FAMILY:
        t = texts[n]
        taken = _taken(t)
        assert set(taken) <= set(handed), (n, set(taken) - set(handed))
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in sorted(family - mine):
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l) and PL not in l]
            assert not hits, (n, name, hits[:5])
        gives = _handed(t)
        assert set(gives) <= mine - set(taken), (n, gives)      # a file hands on its own locals only
        handed += gives
    assert len(handed) == len(set(handed)), handed


@test("locals: the ones handed on are never assigned again (a function or a module's table, the same object in "
      "every part)")
def _():
    texts = {n: text(n) for n in FAMILY}
    handed = [k for n in FAMILY for k in _handed(texts[n])]
    assert sorted(handed) == sorted(["U", "M", "fort_squads", "memo", "eq_ids", "gear_items", "claimed_items",
                                     "free_gear", "vec_remove", "vec_add",
                                     "is_ranged_spec", "claim_map", "item_stage", "item_fits"]), handed
    for n, t in texts.items():
        for i, l in enumerate(t.split("\n"), 1):
            c = _strip(l)
            for name in handed:
                if re.search(r"(?<![\w.:])" + re.escape(name) + r"\s*=[^=]", c) \
                        and not re.match(r"^local (function )?", c) and PL not in c \
                        and not re.search(r"[{,]\s*" + re.escape(name) + r"\s*=", c):
                    raise AssertionError((n, i, l))


ENV = r"""
local hub_src, part_srcs, part_names, whole_src, lua_dir = ...
local function fresh()
    local env = setmetatable({qerror = error}, {__index = _G})
    local mods = {}
    env.reqscript = function(n) mods[n] = mods[n] or {DANGER_TILES = 20}; return mods[n] end
    env.dfhack = {}
    return env
end
-- as the tests load it: the hub from its text, the parts' texts in PART_SOURCES
local split = fresh()
split.PART_SOURCES = {}
for i = 1, #part_names do split.PART_SOURCES[part_names[i]] = part_srcs[i] end
assert(load(hub_src, 'ai-military-gear', 't', split))()
-- as the game loads it: the hub from its file, the parts from the files beside it
local filed = fresh()
assert(loadfile(lua_dir .. '/ai-military-gear.lua', 't', filed))()
-- the old text in one piece
local whole = fresh()
assert(load(whole_src, 'whole', 't', whole))()
local SCAFFOLD = {PARTS = true, PART_VERSIONS = true, PART_SOURCES = true, GEAR_PART_LOCALS = true}
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
    for fn in ("metal_token", "stray_report", "free_stray_gear", "weapon_gaps", "assign_weapons", "gear_report",
               "gaps_why", "quiver_report", "flask_report", "assign_quivers", "squad_ammo", "free_bolts",
               "bolts_free_count", "assign_bolts", "squad_bolts", "unforbid_spares", "fix_gear_gaps",
               "kit_report", "assign_kit", "army_gear"):
        assert f"{fn}:function" in g, fn
    for tbl in ("GEAR_METALS", "STRAY_KINDS", "AW_LEDGER", "GAP_STAGES", "KIT_SLOTS", "KIT_CACHE", "KIT_GIVE"):
        assert f"{tbl}:table" in g, tbl
    same = L.eval("rawequal")
    for e in (env, filed):
        assert dict(e.PART_VERSIONS) == {n: VERSION for n in FAMILY}, dict(e.PART_VERSIONS)
        assert list(e.PARTS.values()) == ["why", "ammo", "fixes", "kit"]
        shared = e.GEAR_PART_LOCALS
        assert len(list(shared.keys())) == 14
        assert same(shared.U, e.reqscript("ai-util")) and same(shared.M, e.reqscript("ai-military"))
    # a part run alone refuses
    try:
        L.execute("local src = ...; local e = setmetatable({qerror = error}, {__index = _G}); "
                  "assert(load(src, 'p', 't', e))()", text(PARTS[0]))
        raise AssertionError("ran alone")
    except Exception as e:  # noqa: BLE001
        assert "is a part of ai-military-gear; run ai-military-gear" in str(e), e


@test("load: a part missing beside the hub is said by name; as ai-military's companion (the prelude) every "
      "part's name is reqscript('ai-military-gear')'s and ai-military's; a swap in the hub's env reaches the parts")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    try:
        L.execute("local src = ...; local e = setmetatable({dfhack = {}, reqscript = function() return {} end}, "
                  "{__index = _G}); assert(load(src, 'ai-military-gear', 't', e))()", text(HUB))
        raise AssertionError("loaded without its parts")
    except Exception as e:  # noqa: BLE001
        assert "ai-military-gear-why.lua is missing (it goes beside ai-military-gear.lua)" in str(e), e
    env = L.execute("local src = ...; local e = setmetatable({dfhack = {persistent = {"
                    "saveSiteData = function() end, getSiteData = function(k, d) return d end}}}, {__index = _G}); "
                    "assert(load(src, 'ai-military', 't', e))(); return e", module_src("ai-military.lua"))
    G = env.reqscript("ai-military-gear")
    same = L.eval("rawequal")
    assert dict(G.PART_VERSIONS) == {n: VERSION for n in FAMILY}, dict(G.PART_VERSIONS)
    for fn in ("gaps_why", "quiver_report", "assign_bolts", "fix_gear_gaps", "kit_report", "army_gear"):
        assert L.eval("type")(G[fn]) == "function", fn
        assert L.eval("type")(env[fn]) == "function", fn        # ai-military's forwarder
    assert env.weapon_is_ranged(L.table_from({"ranged_ammo": "BOLT"})) is True
    # army_gear (kit part) calls gaps_why (why part) and kit_report (kit) through the one environment
    G.gaps_why = L.eval("function() error('swapped') end")
    G.kit_report = L.eval("function() return {swapped = true} end")
    G.quiver_report = L.eval("function() return {} end")
    G.flask_report = L.eval("function() return {} end")
    G.bolts_free_count = L.eval("function() return 7 end")
    out = L.table()
    G.army_gear(out)
    assert "swapped" in out.weapon_gaps_why.error and out.kit.swapped is True and out.bolts_free == 7
    assert same(G.GEAR_PART_LOCALS.M, env)


@test("names: the bridge's module list still names ai-military-gear once; no other Lua file names a part")
def _():
    listed = re.search(r"^BRIDGE_MODULES = \{(.*?)^\}", BRIDGE, re.M | re.S).group(1)
    assert listed.count("'ai-military-gear'") == 1
    for p in LUA_DIR.rglob("*.lua"):
        if p.stem in FAMILY:
            continue
        src = p.read_text(encoding="utf-8")
        for n in PARTS:
            assert n not in src, (p.name, n)


if __name__ == "__main__":
    finish()
