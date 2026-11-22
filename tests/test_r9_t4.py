"""(r9, code health t4) lua/ai-builder-landmarks.lua (84 KB) split by theme into
builder parts under 60 KB each: ai-builder-landmarks (the saved landmarks, grids
and turns, the candidate sites), then ai-builder-landmarks-place (the map checks
and the start on a site) and ai-builder-landmarks-stages (the surface stages,
the openings, landmark_step, the report), which ai-builder.lua's PARTS loads
right after it. Behaviour unchanged: the files together are the old file's lines
with only the split's scaffolding added (headers, version marks, the shared
locals handed on); the parts loaded one after another define the same globals
as the text in one piece.

    python tests/test_r9_t4.py
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
STEM = "ai-builder-landmarks"
LATER = [STEM + "-" + t for t in ("place", "stages")]
FAMILY = [STEM] + LATER
HUB = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
TEXT = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in FAMILY}
SHARED = {"save_landmarks", "find_landmark", "grid_xy", "reason", "reserved_boxes", "extension_cells", "now_date"}


def hub_parts() -> list[str]:
    return re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{(.*?)\}", HUB, re.M | re.S).group(1))


@test("sizes: the three files are each under 60 KB (the one was 84 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS loads the two new parts right after 'landmarks', in this order, each once; "
      "every file is there beside the hub")
def _():
    parts = hub_parts()
    i = parts.index("landmarks")
    assert parts[i - 1] == "halls" and parts[i + 3] == "court", parts
    assert parts[i:i + 3] == [n[len("ai-builder-"):] for n in FAMILY], parts
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
        assert "A part of ai-builder" in src[:800], n
        assert src.count(f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{version}'") == 1, n
        assert len(re.findall(r"^PART_VERSIONS", src, re.M)) == 1, n
    bridge = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "src:match('\\nPARTS = (%b{})')" in bridge
    listed = re.search(r"\nPARTS = (\{.*?\})", HUB, re.S).group(1)
    for n in LATER:
        assert f"'{n[len('ai-builder-'):]}'" in listed, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-builder-landmarks-\w+'\] = '[^']+'   -- .*",
    r"local (\w+)(, \w+)* = \1(, \w+)*",
    r"local \w+(, \w+)? = LANDMARKS_PART_LOCALS\.\w+(, LANDMARKS_PART_LOCALS\.\w+)?",
    r"LANDMARKS_PART_LOCALS = \{save_landmarks = save_landmarks, find_landmark = find_landmark, grid_xy = grid_xy,",
    r" +reason = reason, reserved_boxes = reserved_boxes, extension_cells = extension_cells\}",
    r"LANDMARKS_PART_LOCALS\.now_date = now_date",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^(local info, (has, )?add = info, (has, )?add|"
                     r"local \w+(, \w+)? = LANDMARKS_PART_LOCALS\.\w+(, LANDMARKS_PART_LOCALS\.\w+)?)$")

# sha256 and size of lua/ai-builder-landmarks.lua at 0.105.64 (8183548), the last commit with it in one file
OLD_SHA = "db3c06bd416960ba91c6bf77b0ecba17abc850f4f9c7bd367126a3eec96a84c7"
OLD_SIZE = 83759
SPLIT_VERSION = "0.105.64"


def _body(text: str, later: bool, removed: list) -> str:
    """A file's text without the split's scaffolding: a later part's header (to
    its version mark, the locals it takes in and ONE blank line after them) and
    the "-- (r9)" block a file ends with. The removed lines go in `removed`."""
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
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r9)")), default=None)
    if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.64; what was taken out is headers, marks, comments and the shared locals handed on")
def _():
    version = re.search(r"PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {version})")
    removed = []
    parts = [_body(TEXT[STEM], False, removed)] + [_body(TEXT[n], True, removed) for n in LATER]
    whole = ("\n\n".join(p.rstrip("\n") for p in parts) + "\n").encode("utf-8")
    assert len(whole) == OLD_SIZE, len(whole)
    assert hashlib.sha256(whole).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    code = [l for l in removed if l and not l.startswith("--")]
    # two marks; seven lines taking locals in (2 the hub's, 5 handed on); three handing on
    assert len(code) == 2 + 7 + 3, code


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
      "the seven handed on are functions declared once and never assigned again")
def _():
    family = set().union(*(_top_locals(t) for t in TEXT.values()))
    assert SHARED <= family
    for n, t in TEXT.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
    whole = "\n".join(_strip(l) for t in TEXT.values() for l in t.split("\n"))
    for name in SHARED:
        assert len(re.findall(rf"^local function {name}\(", whole, re.M)) == 1, name
        rest = re.sub(r"(?m)^local [\w, ]+ = LANDMARKS_PART_LOCALS\..*$", "", whole)
        rest = re.sub(rf"\b{name} = {name}\b", "", rest)
        rest = re.sub(rf"LANDMARKS_PART_LOCALS\.{name}\b", "", rest)
        assert not re.search(rf"(?<![\w.:]){name}\s*=[^=]", rest), name
    # the hub's info, has, add and ez, taken in by each file that uses them, as the one file took them
    for n, t in TEXT.items():
        code = "\n".join(_strip(l) for l in t.split("\n"))
        took = re.search(r"^local ((?:\w+, )*\w+) = \1$", t, re.M)
        took = set(took.group(1).split(", ")) if took else set()
        for name in ("info", "has", "add", "ez"):
            if re.search(rf"(?<![\w.:]){name}\(", code):
                assert name in took, (n, name)


ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({qerror = error, info = function() end, ez = function(z) return z end,
                              has = function() end, add = function() end},
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
      "the shared locals are functions")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, env = L.execute(ENV, L.table_from([TEXT[n] for n in FAMILY]), L.table_from(FAMILY))
    assert a == b
    g = set(a.split())
    for fn in ("blueprints", "landmarks_data", "landmarks_open_surface", "landmark_sites", "offered_site",
               "validate_landmark", "start_landmark", "build_landmark", "landmark_dig_cells",
               "landmark_surface_cells", "open_plan", "landmark_step", "landmarks_report"):
        assert f"{fn}:function" in g, fn
    assert set(env.LANDMARKS_PART_LOCALS.keys()) == SHARED
    assert all(L.eval("type")(v) == "function" for v in env.LANDMARKS_PART_LOCALS.values())
    assert sorted(env.PART_VERSIONS.keys()) == sorted(FAMILY)
    # find_landmark, handed on: the landmark of that id in a record, as the one file's local did
    d = L.eval("{list = {{landmark_id = 3, name = 'a'}, {landmark_id = 7, name = 'b'}}}")
    assert env.LANDMARKS_PART_LOCALS.find_landmark(d, 7).name == "b"
    assert env.LANDMARKS_PART_LOCALS.find_landmark(d, 9) is None


@test("each file compiles alone; where each theme's names live")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    chk = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return f ~= nil, e end")
    for n in FAMILY:
        ok, err = chk(TEXT[n], n)
        assert ok, (n, err)
    where = {"": ["blueprints", "stone_at", "landmarks_data", "landmarks_open_surface", "grid_cells",
                  "envelope", "landmark_plans", "landmark_sites", "offered_site"],
             "-place": ["paths_kept", "open_drop_reasons", "validate_landmark", "landmark_dig_cells",
                        "landmark_surface_cells", "start_landmark", "build_landmark"],
             "-stages": ["remove_construction", "units_on", "open_plan", "landmark_step", "landmarks_report"]}
    for suffix, fns in where.items():
        for fn in fns:
            defs = [n for n in FAMILY if re.search(rf"^function {fn}\(", TEXT[n], re.M)]
            assert defs and set(defs) == {STEM + suffix}, (fn, defs)


if __name__ == "__main__":
    finish()
