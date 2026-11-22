"""(r8, code health 13c, s8) lua/ai-builder-cistern.lua (110 KB) split by theme
into three builder parts under 60 KB each: ai-builder-cistern (the plan: the
source, the tunnel, the shaft, plan_cistern, cistern_sealed),
ai-builder-cistern-status (the saved cistern, its status, levers, retiring,
closing its gaps) and ai-builder-cistern-step (cistern_step, one step a call),
ai-builder.lua's PARTS loading the two new ones right after 'cistern'.
Behaviour unchanged: the three files together are the old file's lines with
only the split's scaffolding added (headers, version marks, the few shared
top-level locals handed on through CISTERN_PART_LOCALS); the parts loaded one
after another define the same globals as the text in one piece; the real
builder loads them all.

    python tests/test_r8_s8.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from cistern_src import builder_parts, cistern_parts, cistern_src  # noqa: E402

LUA_DIR = ROOT / "lua"
FIRST = "ai-builder-cistern"
LATER = ["ai-builder-cistern-status", "ai-builder-cistern-step"]
FAMILY = [FIRST] + LATER
HUB = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB, re.M).group(1)


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the three files are each under 60 KB (the one was 110 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS loads cistern, cistern-status, cistern-step one after another, after the wells and "
      "before the surface as the one file was")
def _():
    parts = builder_parts()
    i = parts.index("cistern")
    assert parts[i:i + 3] == ["cistern", "cistern-status", "cistern-step"], parts
    assert parts.index("wells") < i < parts.index("surface"), parts
    assert cistern_parts() == FAMILY, cistern_parts()
    assert len(parts) == len(set(parts)), parts


@test("parts: each new file is a builder part (no module of its own), says so, carries its version mark")
def _():
    for n in FAMILY:
        src = text(n)
        assert "@ module" not in src, n
        assert "A part of ai-builder" in src[:600], n
        assert (f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'"
                "   -- (0.105.26) bumped with BRIDGE_VERSION") in src.split("\n"), n
        assert len(re.findall(r"^PART_VERSIONS", src, re.M)) == 1, n


L_ = r"CISTERN_PART_LOCALS\.\w+"
SCAFFOLD = [
    r"",
    r"--.*",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-builder-cistern-[\w-]+'\] = '[^']+'   -- .*",
    r"local ez = ez",
    rf"local \w+(, \w+)* = {L_}(, {L_})*",
    r"CISTERN_PART_LOCALS = \{\w+ = \w+(, \w+ = \w+)*\}",
    rf"{L_}(, {L_})* = \w+(, \w+)*",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(rf"^(local ez = ez|local \w+(, \w+)* = {L_}(, {L_})*)$")

# sha256 of lua/ai-builder-cistern.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "4f0745812a6573b491771226d3525824f5f75a41b171c0443316199850d7d7c6"
SPLIT_VERSION = "0.105.63"


def _body(src: str, later: bool, removed: list) -> str:
    """A file's text without the split's scaffolding (a later part's header and
    the locals it takes in; the "-- (r8)" block a file ends with), the removed
    lines put in `removed`."""
    lines = src.split("\n")
    if later:
        i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
        while i < len(lines) and (lines[i] == "" or TAKE_RE.match(lines[i])):
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r8)")), default=None)
    if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the three files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.63; what was taken out is headers, marks, comments and the shared locals handed on")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {VERSION})")
    removed = []
    parts = [_body(text(FIRST), False, removed)] + [_body(text(n), True, removed) for n in LATER]
    whole = "\n\n".join(p.rstrip("\n") for p in parts) + "\n"
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    # the scaffolding is small: two headers (a mark, ez and the locals taken in) and two hand-overs
    assert sum(1 for l in removed if l and not l.startswith("--")) == 11, removed


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(src: str) -> set[str]:
    out = set()
    for l in src.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*=", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a top-level local another file of the family declares without taking it in; "
      "none of the handed-on locals is ever assigned again (a copy would go stale)")
def _():
    texts = {n: text(n) for n in FAMILY}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert {"DIR8", "DIR4", "still_water", "save_cistern", "standable", "tunnel_to_goal"} <= family, family
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
    handed = {"DIR8", "still_water", "river_water", "save_cistern", "game_tick", "room_tiles",
              "building_info", "path_words"}
    for n, t in texts.items():
        for name in handed:
            again = [l for l in t.split("\n")
                     if re.match(r"^\s*(?!local\b)(?:[\w.]+\s*,\s*)*" + name + r"\s*(?:,\s*[\w.]+\s*)*=[^=]", l)]
            assert not again, (n, name, again)
            assert not re.search(r"\b" + name + r"\s*\[[^\]]*\]\s*=[^=]", t), (n, name)   # a table written into


ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env.reqscript = function(n) return {} end
    env.site_get = function() return {} end
    env.site_put = function(k, d) env.PUT = {k, d} end
    env.ez = function(z) return z end
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
        if k ~= '_G' and k ~= 'PUT' then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
return keys(split), keys(whole), split
"""


@test("load: the parts loaded one after another define the same globals as the text in one piece; "
      "the shared locals are the first file's own table and functions")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, env = L.execute(ENV, L.table_from([text(n) for n in FAMILY]), L.table_from(FAMILY))
    assert a == b
    g = set(a.split())
    for fn in ("citizens_in_deep_water", "water_body_safe", "cistern_prefs", "plan_cistern", "cistern_sealed",
               "cistern_data", "pull", "cistern_status", "cistern_retire", "cistern_relink", "cistern_shut",
               "cistern_gap_plan", "cistern_close_gaps", "cistern_step"):
        assert f"{fn}:function" in g, fn
    assert "CISTERN_KEY:string" in g and "CISTERN_HOLD:boolean" in g and "PART_VERSIONS:table" in g
    shared = env.CISTERN_PART_LOCALS
    assert set(shared.keys()) == {"DIR8", "still_water", "river_water", "save_cistern", "game_tick",
                                  "room_tiles", "building_info", "path_words"}, list(shared.keys())
    assert len(shared.DIR8) == 8
    for k in shared.keys():
        if k != "DIR8":
            assert L.eval("type")(shared[k]) == "function", k
    # still_water, handed on: still water only (as the one file's local did)
    t = L.table_from
    assert shared.still_water(t({"liquid": True, "depth": 7})) and not shared.still_water(t({"liquid": False}))
    # save_cistern, handed on: writes the cistern's own key
    d = L.table_from({"stage": "dig"})
    shared.save_cistern(d)
    assert env.PUT[1] == env.CISTERN_KEY == "ai-overseer/cistern" and L.eval("rawequal")(env.PUT[2], d)
    assert [env.PART_VERSIONS[n] for n in FAMILY] == [VERSION] * 3


@test("helper: the tests' cistern_src() is the three files in load order; each file compiles alone")
def _():
    src = cistern_src()
    assert src == "\n".join(text(n) for n in FAMILY)
    assert src.index("function plan_cistern(") < src.index("function cistern_status(") < src.index("function cistern_step(")
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    chk = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return e end")
    for n in FAMILY:
        assert chk(text(n), n) is None, n


@test("the builder: ai-builder.lua loads the three files (the fake fort of test_builder), every part marked, "
      "cistern_step and cistern_status the hub's own names")
def _():
    need_lua()
    import test_builder as TB
    B = TB.B
    parts = list(B.PARTS.values())
    assert parts == builder_parts(), parts
    for n in FAMILY:
        assert B.PART_VERSIONS[n] == B.PART_VERSIONS["ai-builder"], n
    for fn in ("plan_cistern", "cistern_status", "cistern_step", "cistern_close_gaps", "cistern_retire"):
        assert B[fn] is not None, fn
    assert set(B.CISTERN_PART_LOCALS.keys()) >= {"DIR8", "save_cistern", "path_words"}


if __name__ == "__main__":
    finish()
