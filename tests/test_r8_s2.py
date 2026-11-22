"""(r8, code health s2) lua/ai-builder-projects.lua (164 KB) split by theme into
builder parts under 60 KB each: ai-builder-projects (the saved projects, the
workshop levels, start_project), then ai-builder-projects-progress, -finish,
-founding, -wayin, -polish, which ai-builder.lua's PARTS loads right after it.
Behaviour unchanged: the files together are the old file's lines with only the
split's scaffolding added (headers, version marks, the shared locals handed
on); the parts loaded one after another define the same globals as the text in
one piece.

    python tests/test_r8_s2.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import builder_part_src  # noqa: E402

LUA_DIR = ROOT / "lua"
STEM = "ai-builder-projects"
LATER = [STEM + "-" + t for t in ("progress", "finish", "founding", "wayin", "polish")]
FAMILY = [STEM] + LATER
HUB = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
TEXT = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in FAMILY}


def hub_parts() -> list[str]:
    return re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{(.*?)\}", HUB, re.M | re.S).group(1))


@test("sizes: the six files are each under 60 KB (the one was 164 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS loads the five new parts right after 'projects', in this order, each once; "
      "every file is there beside the hub")
def _():
    parts = hub_parts()
    i = parts.index("projects")
    assert parts[i - 1] == "sites", parts
    assert parts[i:i + 6] == [n[len("ai-builder-"):] for n in FAMILY], parts
    assert len(parts) == len(set(parts)), parts
    for p in parts:
        assert (LUA_DIR / f"ai-builder-{p}.lua").is_file(), p
    assert builder_part_src(STEM) == "\n".join(TEXT[n] for n in FAMILY)


@test("parts: each new file is a builder part (no module), says so, carries its version mark; "
      "the bridge finds them from the hub's PARTS line")
def _():
    version = re.search(r"PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB).group(1)
    for n in FAMILY:
        src = TEXT[n]
        assert "@ module" not in src and "@module" not in src, n
        assert "A part of ai-builder" in src[:600], n
        assert src.count(f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{version}'") == 1, n
        assert len(re.findall(r"^PART_VERSIONS", src, re.M)) == 1, n
    # ai-bridge's `version`: reqscript('ai-builder').PARTS, or the hub's text matched like this
    bridge = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "src:match('\\nPARTS = (%b{})')" in bridge
    listed = re.search(r"\nPARTS = (\{.*?\})", HUB, re.S).group(1)
    for n in LATER:
        assert f"'{n[len('ai-builder-'):]}'" in listed, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-builder-projects-\w+'\] = '[^']+'   -- .*",
    r"local ez = ez",
    r"local info, ez = info, ez",
    r"local \w+ = PROJECTS_PART_LOCALS\.\w+",
    r"PROJECTS_PART_LOCALS = \{find = find\}",
    r"PROJECTS_PART_LOCALS\.founded_site = founded_site",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^(local ez = ez|local info, ez = info, ez|local \w+ = PROJECTS_PART_LOCALS\.\w+)$")

# sha256 of lua/ai-builder-projects.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "be215ea8b4887465636a9b2199e8e1f2d6eda8fc5b94862543d14a1c6a253e92"
SPLIT_VERSION = "0.105.63"


def _body(text: str, later: bool, removed: list) -> str:
    """A file's text without the split's scaffolding: a later part's header (to
    its version mark, the locals it takes in and ONE blank line after them) and
    the "-- (r8)" block a file ends with. The removed lines go in `removed`."""
    lines = text.split("\n")
    if later:
        i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
        assert lines[i] == ""
        i += 1
        while TAKE_RE.match(lines[i]):
            i += 1
        assert lines[i] == ""
        i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r8)")), default=None)
    if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.63; what was taken out is headers, marks, comments and the shared locals handed on")
def _():
    version = re.search(r"PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {version})")
    removed = []
    parts = [_body(TEXT[STEM], False, removed)] + [_body(TEXT[n], True, removed) for n in LATER]
    whole = "\n\n".join(p.rstrip("\n") for p in parts) + "\n"
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    code = [l for l in removed if l and not l.startswith("--")]
    assert len(code) == 5 + 7 + 2, code      # five marks; seven locals taken in; two handed on


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(text: str) -> set[str]:
    out = set()
    for l in text.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*(=|$)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a top-level local another file of the family declares without taking it in; "
      "the two handed on (find, founded_site) are functions never assigned again")
def _():
    family = set().union(*(_top_locals(t) for t in TEXT.values()))
    assert {"find", "founded_site", "tick_of", "wkey", "refuse", "room_cells", "decode_projects"} <= family
    for n, t in TEXT.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
    whole = "\n".join(_strip(l) for t in TEXT.values() for l in t.split("\n"))
    for name in ("find", "founded_site"):
        assert len(re.findall(rf"^local function {name}\(", whole, re.M)) == 1, name
        assert not re.search(rf"(?<![\w.:]){name}\s*=[^=]", whole.replace(f"local {name} = PROJECTS_PART_LOCALS", "")
                             .replace(f"{{{name} = {name}}}", "")), name
    assert "local find = PROJECTS_PART_LOCALS.find" in TEXT[STEM + "-founding"]
    assert "local founded_site = PROJECTS_PART_LOCALS.founded_site" in TEXT[STEM + "-wayin"]
    # the hub's info and ez, taken in by each file that uses them, as the one file took them
    for n, t in TEXT.items():
        code = "\n".join(_strip(l) for l in t.split("\n"))
        for name in ("info", "ez"):
            if re.search(rf"(?<![\w.:]){name}\(", code):
                assert re.search(rf"^local (info, )?{name}( = |, ez = )", t, re.M), (n, name)


ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({qerror = error, info = function() end, ez = function(z) return z end},
                             {__index = _G})
    env.require = function(n) return {n = n} end
    env._G = env
    return env
end
-- as the hub: each part a chunk of its own in the one env, in order
local split = fresh()
for i = 1, #names do assert(load(srcs[i], names[i], 't', split))() end
-- the text in one piece
local whole = fresh()
assert(load(table.concat(srcs, '\n'), 'whole', 't', whole))()
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if k ~= '_G' and k ~= 'require' then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
return keys(split), keys(whole), split
"""


@test("load: the parts loaded one after another define the same globals as the text in one piece; "
      "the shared locals are functions; start_project is the wrapper, start_project_level the first")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, env = L.execute(ENV, L.table_from([TEXT[n] for n in FAMILY]), L.table_from(FAMILY))
    assert a == b
    g = set(a.split())
    for fn in ("load_projects", "save_projects", "join_workshop_level", "start_project", "start_project_level",
               "cells_of", "dig_progress", "furnish_progress", "slot_cap", "projects_report", "registry_report",
               "dedicate_temple", "prioritize_project", "furnish_project", "finish_project", "engrave_project",
               "found_fort", "has_staircase", "cancel_project", "unreached_stairs_dropped",
               "dig_way_in", "way_in_plan_and_dig", "way_in_second_spots", "polish_pick", "polish_next"):
        assert f"{fn}:function" in g, fn
    assert env.start_project != env.start_project_level
    assert set(env.PROJECTS_PART_LOCALS.keys()) == {"find", "founded_site"}
    assert all(L.eval("type")(v) == "function" for v in env.PROJECTS_PART_LOCALS.values())
    assert sorted(env.PART_VERSIONS.keys()) == sorted(FAMILY)
    # find, handed on: the project of that id in a record, as the one file's local did
    data = L.eval("{list = {{id = 3, kind = 'a'}, {id = 7, kind = 'b'}}}")
    assert env.PROJECTS_PART_LOCALS.find(data, 7).kind == "b"
    assert env.PROJECTS_PART_LOCALS.find(data, 9) is None


@test("each file compiles alone; where each theme's names live")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    chk = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return f ~= nil, e end")
    for n in FAMILY:
        ok, err = chk(TEXT[n], n)
        assert ok, (n, err)
    where = {"": ["load_projects", "save_projects", "join_workshop_level", "start_project"],
             "-progress": ["cells_of", "dig_progress", "furnish_progress", "slot_cap", "projects_report",
                           "registry_report"],
             "-finish": ["dedicate_temple", "retarget_hall", "prioritize_project", "unmark_project_dig",
                         "furnish_project", "finish_project", "engrave_project"],
             "-founding": ["found_fort", "has_staircase", "cancel_project", "unreached_stairs_dropped"],
             "-wayin": ["way_in_fort", "way_in_second_spots", "dig_way_in", "way_in_plan_and_dig"],
             "-polish": ["polish_pick", "polish_next"]}
    for suffix, fns in where.items():
        for fn in fns:
            defs = [n for n in FAMILY if re.search(rf"^function {fn}\(", TEXT[n], re.M)]
            assert defs and set(defs) == {STEM + suffix}, (fn, defs)


if __name__ == "__main__":
    finish()
