"""(r8, code health s6) lua/ai-builder-surface.lua (126 KB) split by theme into
builder parts under 60 KB each: ai-builder-keep, -deepdepot, -wagonroad, -dump,
listed in the hub's PARTS right after 'surface'. Behaviour unchanged: the five
files together are the old file's lines with only the split's scaffolding added
(headers, guards, version marks, the deep depot's local helpers its road
uses too, handed on through DEPOT_PART_LOCALS); the parts loaded one after another define the same
globals as the text in one piece.

    python tests/test_r8_s6.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402

LUA_DIR = ROOT / "lua"
STEM = "ai-builder-surface"
LATER = ["ai-builder-keep", "ai-builder-deepdepot", "ai-builder-wagonroad", "ai-builder-dump"]
NAMES = [STEM] + LATER
HUB = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
TEXTS = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in NAMES}
# the local helpers ai-builder-deepdepot hands on to ai-builder-wagonroad (the only
# top-level locals of the old file used across a cut, besides `info, ez`)
HANDED = set()
HANDED_DEPOT = {"save_deep_depot", "deep_now", "wagon_ground", "building_blocks", "wagon_look", "deep_dir",
                "deep_depot_building", "any_depot", "depot_built", "deep_dig_left"}


def hub_parts() -> list[str]:
    return re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{(.*?)\}", HUB, re.M | re.S).group(1))


@test("sizes: the five files are each under 60 KB (the one was 126 KB)")
def _():
    for n in NAMES:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS lists keep, deepdepot, wagonroad, dump right after surface, in that order, before rooms")
def _():
    parts = hub_parts()
    i = parts.index("surface")
    assert parts[i:i + 6] == ["surface", "keep", "deepdepot", "wagonroad", "dump", "rooms"], parts
    assert len(parts) == len(set(parts)), parts
    for n in LATER:
        assert (LUA_DIR / f"{n}.lua").is_file(), n


@test("parts: each new file is a builder part (no module), refuses to run alone, carries its version mark")
def _():
    version = re.search(r"^PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB, re.M).group(1)
    for n in LATER:
        src = TEXTS[n]
        assert "@ module" not in src and "@module" not in src, n
        assert "A part of ai-builder" in src[:600], n
        assert f"if not PARTS then qerror('{n} is a part of ai-builder; run ai-builder') end" in src, n
        assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{version}'" in src, n
    assert f"PART_VERSIONS['{STEM}'] = '{version}'" in TEXTS[STEM]
    # the hub sets PARTS before its loop loads a part, so the guard passes there
    assert HUB.index("\nPARTS = {") < HUB.index("for _, part in ipairs(PARTS) do")


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not PARTS then qerror\('ai-builder-[\w-]+ is a part of ai-builder; run ai-builder'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-builder-[\w-]+'\] = '[^']+'   -- .*",
    r"local info, ez = info, ez",
    r"local [\w, ]+ = DEPOT_PART_LOCALS\.\w+(, DEPOT_PART_LOCALS\.\w+)*",
    r"DEPOT_PART_LOCALS = \{[\w =,]+",
    r" +[\w =,]+\}?",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^(local info, ez = info, ez|local [\w, ]+ = DEPOT_PART_LOCALS\.[\w., ]+)$")
HEAD_NOTE = re.compile(r"-- \(r8\) The keep, the underground depot.*?-dump\.\n", re.S)

# sha256 of lua/ai-builder-surface.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "1d4a51e02303b6d168b9fe924096ffd4e8566f0214eb3ce9137098056eda7afa"
SPLIT_VERSION = "0.105.63"


def _body(text: str, later: bool, removed: list) -> str:
    """A file's text without the split's scaffolding (a later part's header and
    the locals it takes in; the "-- (r8)" block a file ends with), the removed
    lines put in `removed`."""
    lines = text.split("\n")
    if later:
        i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
        while i < len(lines) and (lines[i] == "" or TAKE_RE.match(lines[i])):
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r8)") and k > 10), default=None)
    if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.63; what was taken out is headers, guards, marks, comments and the shared locals handed on")
def _():
    version = re.search(r"^PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB, re.M).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {version})")
    removed = []
    parts = [_body(TEXTS[STEM], False, removed)] + [_body(TEXTS[n], True, removed) for n in LATER]
    whole = "\n\n".join(p.rstrip("\n") for p in parts) + "\n"
    notes = HEAD_NOTE.findall(whole)
    whole = HEAD_NOTE.sub("", whole)
    removed += [l for n in notes for l in n.split("\n") if l]
    assert len(notes) == 1, notes
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    # every part's body starts at the old file's section line it was cut at
    for n, first in zip(LATER, ("-- --- the keep: building above ground",
                                "-- --- the underground trade depot (the Deep mine)",
                                "-- --- (0.105.30) the built road, checked for the wagons",
                                "-- --- the garbage dump (0.105.27 disposal)")):
        assert _body(TEXTS[n], True, []).startswith(first), n


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(text: str) -> set[str]:
    out = set()
    for l in text.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*(?:=|$)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a top-level local another file of the family declares without taking it in; "
      "what is handed on is functions only, never reassigned")
def _():
    family = set().union(*(_top_locals(t) for t in TEXTS.values()))
    for n, t in TEXTS.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            key = re.compile(r"[{,]\s*" + re.escape(name) + r" = ")   # a table's key of the same name
            hits = [i for i, l in enumerate(code, 1) if pat.search(key.sub(",", l))]
            assert not hits, (n, name, hits[:5])
    # each handed name: one `local function` in the file that hands it, no assignment to it anywhere
    for name in HANDED | HANDED_DEPOT:
        owner = STEM if name in HANDED else "ai-builder-deepdepot"
        assert len(re.findall(rf"^local function {name}\(", TEXTS[owner], re.M)) == 1, name
        for n, t in TEXTS.items():
            for l in t.split("\n"):
                c = _strip(l)
                if re.match(r"^local [\w, ]+ = DEPOT_PART_LOCALS\.", c):
                    continue
                if n == owner and (c.startswith("DEPOT_PART_LOCALS = {") or re.match(r"^ {21}\w+ = \w+[,}]", c)):
                    continue   # the hand-over's own `name = name` pairs
                assert not re.search(rf"(?<![\w.:]){name}\s*=[^=]", c), (n, name, l)
    for n in (STEM, "ai-builder-keep", "ai-builder-deepdepot", "ai-builder-dump"):
        took = set(re.findall(r"DEPOT_PART_LOCALS\.(\w+)", "\n".join(
            l for l in TEXTS[n].split("\n") if l.startswith("local "))))
        assert took == set(), (n, took)
    assert "DEPOT_PART_LOCALS" not in TEXTS[STEM] + TEXTS["ai-builder-keep"] + TEXTS["ai-builder-dump"]
    took = set(re.findall(r"DEPOT_PART_LOCALS\.(\w+)", "\n".join(
        l for l in TEXTS["ai-builder-wagonroad"].split("\n") if l.startswith("local "))))
    assert took == HANDED_DEPOT, took


ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({PARTS = {}, qerror = error, info = function() end, ez = function() end},
                             {__index = _G})
    env._G = env
    return env
end
-- as the hub: each part a chunk of its own in the one env, in order
local split = fresh()
for i = 1, #names do assert(load(srcs[i], names[i], 't', split))() end
-- the text in one piece
local whole = fresh()
local all = {}
for i = 1, #names do all[#all + 1] = srcs[i] end
assert(load(table.concat(all, '\n'), 'whole', 't', whole))()
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if k ~= '_G' then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
-- a part alone, outside the builder: refused
local alone = {}
for i = 2, #names do
    local env = setmetatable({qerror = error}, {__index = _G})
    local ok, err = pcall(assert(load(srcs[i], names[i], 't', env)))
    alone[i - 1] = (not ok) and tostring(err) or 'ran'
end
return keys(split), keys(whole), split, alone
"""


@test("load: the parts loaded one after another define the same globals as the text in one piece; "
      "the shared locals are functions; a part run alone is refused")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, env, alone = L.execute(ENV, L.table_from([TEXTS[n] for n in NAMES]), L.table_from(NAMES))
    assert a == b
    g = set(a.split())
    for fn in ("find_surface_rect", "is_tree", "find_keep_court", "keep_status", "place_keep",
               "deep_wagon_check", "place_dump_zone"):
        assert f"{fn}:function" in g, fn
    assert "DEPOT_PART_LOCALS:table" in g
    shared = env.DEPOT_PART_LOCALS
    assert set(shared.keys()) == HANDED | HANDED_DEPOT, list(shared.keys())
    for k in shared.keys():
        assert "function" in str(shared[k]), k
    for i, n in enumerate(LATER, 1):
        assert f"{n} is a part of ai-builder; run ai-builder" in alone[i], (n, alone[i])
    for n in NAMES:
        assert env.PART_VERSIONS[n] is not None, n


@test("the builder: the real hub loads all five and the names the bridge and the brain reach are there")
def _():
    need_lua()
    src = (ROOT / "tests" / "test_hygiene_builder.py").read_text(encoding="utf-8")
    assert "B.PARTS" in src   # the hygiene test checks every ai-builder-*.lua is in PARTS, through the loaded hub
    by_file = {
        STEM: ["find_surface_rect", "is_tree"],
        "ai-builder-keep": ["keep_data", "find_keep_court", "keep_status", "place_keep"],
        "ai-builder-deepdepot": [],
        "ai-builder-wagonroad": ["deep_wagon_check"],
        "ai-builder-dump": ["place_dump_zone"],
    }
    for n, fns in by_file.items():
        for fn in fns:
            assert re.search(rf"^function {fn}\(", TEXTS[n], re.M), (n, fn)
            others = [m for m in NAMES if m != n and re.search(rf"^function {fn}\(", TEXTS[m], re.M)]
            assert not others, (fn, others)


if __name__ == "__main__":
    finish()
