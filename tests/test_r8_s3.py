"""(r8, code health s3) lua/ai-society.lua (140 KB) split by theme into a hub
and three parts under 60 KB each, the way lua/ai-gates.lua is: ai-society.lua
(the shelter, and the loader) loads ai-society-animals, -needs and -posts into
its own environment, in the old file's order. Behaviour unchanged: the hub and
the parts with the split's scaffolding taken out are the old file byte for
byte; loaded as the hub loads them they define the names the one file defined;
the few file-scope locals the parts share (ai-util, the report's walks,
utils) are handed on as the same objects. lua/ai-society-burrows.lua stays the
separate module it was (a companion, no part).

    python tests/test_r8_s3.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import COMPANIONS, SPLIT, module_src, split_parts, split_src, with_util  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB_NAME = "ai-society"
PARTS = ["ai-society-animals", "ai-society-needs", "ai-society-posts"]
# the file-scope locals of the hub each part takes back
TAKES = {"ai-society-animals": ["report_citizens", "report_units", "utils"],
         "ai-society-needs": ["U", "report_citizens"],
         "ai-society-posts": ["U", "report_citizens", "report_units"]}
HUB = (LUA_DIR / "ai-society.lua").read_text(encoding="utf-8")
TEXTS = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in PARTS}

# sha256 of lua/ai-society.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "190a4c4b3b9c09a9e7124993ef4fc1fd89498350dfd2bfc94fd65b7b00220c85"
OLD_SIZE = 139915
SPLIT_VERSION = "0.105.63"

HAND_OVER = ("SOCIETY_PART_LOCALS = {U = U, report_citizens = report_citizens, "
             "report_units = report_units, utils = utils}")
TAIL_START = "-- (r8) this file's locals the later parts use, handed on (each takes them"
LOADER = r"""local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-society-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-society: ' .. name .. '.lua is missing (it goes beside ai-society.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
"""
SCAFFOLD_RE = re.compile("^(?:" + "|".join([
    r"",
    r"--.*",
    re.escape(HAND_OVER),
    r"PARTS = \{'animals', 'needs', 'posts'\}",
    r"PART_VERSIONS = \{\['ai-society'\] = '[^']+'\}   -- .*",
    r"if not SOCIETY_PART_LOCALS then qerror\('ai-society-\w+ is a part of ai-society; run ai-society'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-society-\w+'\] = '[^']+'   -- .*",
    r"local [\w, ]+ = SOCIETY_PART_LOCALS\.\w+(, SOCIETY_PART_LOCALS\.\w+)*   -- \(r8\) the hub's locals",
]) + ")$")


def hub_mark() -> str:
    return re.search(r"^PART_VERSIONS = \{\['ai-society'\] = '([^']+)'\}", HUB, re.M).group(1)


def hub_body(removed: list) -> str:
    """The hub's own lines: all before the split's tail (the hand-over, the
    part list, the loader), which goes to `removed`."""
    i = HUB.index("\n" + TAIL_START + "\n")
    tail = HUB[i + 1:]
    assert tail.endswith(LOADER), "the hub ends with the loader"
    removed += tail[:-len(LOADER)].split("\n")
    return HUB[:i]


def part_body(name: str, removed: list) -> str:
    """A part's lines after its header (comments, the guard, the version mark,
    the locals it takes back, one empty line), which goes to `removed`."""
    lines = TEXTS[name].split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("local ") and "SOCIETY_PART_LOCALS." in l)
    assert lines[i + 1] == "", name
    removed += lines[:i + 2]
    return "\n".join(lines[i + 2:])


@test("sizes: the four files are each under 60 KB (the one was 140 KB), and together the old file "
      "and a few KB of scaffolding")
def _():
    total = 0
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)
        total += size
    if hub_mark() == SPLIT_VERSION:
        assert OLD_SIZE < total < OLD_SIZE + 6 * 1024, total


@test("hub: PARTS lists animals, needs, posts in the old file's order; the tests' helpers read the same; "
      "ai-society-burrows is no part (a companion module, as before)")
def _():
    listed = re.search(r"^PARTS = \{(.*?)\}$", HUB, re.M).group(1)
    assert re.findall(r"'([\w-]+)'", listed) == ["animals", "needs", "posts"], listed
    assert split_parts("ai-society.lua") == PARTS
    assert "ai-society.lua" in SPLIT
    assert COMPANIONS["ai-society.lua"] == ["ai-society-burrows"]
    assert "ai-society-burrows" not in PARTS
    burrows = (LUA_DIR / "ai-society-burrows.lua").read_text(encoding="utf-8")
    assert "\n--@module = true\n" in burrows and "local S = reqscript('ai-society')" in burrows
    assert "SOCIETY_PART_LOCALS" not in burrows
    # every ai-society-*.lua beside the hub is a part or the companion
    found = sorted(p.stem for p in LUA_DIR.glob("ai-society-*.lua") if not p.stem.startswith("ai-society-burrows-"))   # (r9) its own parts
    assert found == sorted(PARTS + ["ai-society-burrows"]), found
    # the hub is still the module; it loads the parts last (nothing follows the loader)
    assert "\n--@module = true\n" in HUB and HUB.endswith(LOADER)
    # split_src: the hub and its parts, in load order
    assert split_src("ai-society.lua") == HUB + "".join("\n" + TEXTS[n] for n in PARTS)


@test("parts: each is a part (no module), refuses to run alone, carries its version mark and takes back "
      "the hub's locals it uses; the hub carries its own mark")
def _():
    version = hub_mark()
    for n in PARTS:
        src = TEXTS[n]
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert f"if not SOCIETY_PART_LOCALS then qerror('{n} is a part of ai-society; run ai-society') end" in src, n
        marks = re.findall(r"^PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['([\w-]+)'\] = '([^']+)'", src, re.M)
        assert marks == [(n, version)], (n, marks)
        take = "local " + ", ".join(TAKES[n]) + " = " + ", ".join("SOCIETY_PART_LOCALS." + x for x in TAKES[n])
        assert src.count(take + "   -- (r8) the hub's locals\n") == 1, n
        # the guard and the mark stand before any code
        head = src[:src.index("PART_VERSIONS = ")].split("\n")
        assert all(l == "" or l.startswith("--") or l.startswith("if not SOCIETY_PART_LOCALS") for l in head), n
    assert HUB.count(HAND_OVER + "\n") == 1
    assert HUB.index(HAND_OVER) < HUB.index("\nPARTS = ") < HUB.index("\nPART_VERSIONS = {") < HUB.index(LOADER)


@test("unchanged: the hub and the parts with the split's scaffolding taken out are, byte for byte, the one "
      "file of 0.105.63; what was taken out is headers, the guard, marks, the loader and the locals handed on")
def _():
    if hub_mark() != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {hub_mark()})")
    removed: list = []
    whole = hub_body(removed) + "\n" + "".join(part_body(n, removed) for n in PARTS)
    assert len(whole.encode("utf-8")) == OLD_SIZE, len(whole.encode("utf-8"))
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad


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


@test("locals: no file uses a file-scope local another file of the family declares without taking it in; "
      "the four handed on are never assigned again")
def _():
    texts = {HUB_NAME: HUB, **TEXTS}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert {"U", "report_citizens", "report_units", "utils", "civ_alert", "pens", "BURROWS", "WORN_MODE"} <= family
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
        if n != HUB_NAME:
            assert set(TAKES[n]) <= mine, n
            # and takes in none it does not use
            for name in TAKES[n]:
                pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
                assert sum(1 for l in code if pat.search(l)) > 1, (n, name)
    for name in ("U", "report_citizens", "report_units", "utils"):
        writes = [l for t in texts.values() for l in map(_strip, t.split("\n"))
                  if re.search(r"(?<![\w.:])" + name + r"\s*(,\s*\w+\s*)*=(?!=)", l) and not l.startswith("local ")
                  and "SOCIETY_PART_LOCALS = {" not in l]
        assert not writes, (name, writes)


ENV = r"""
local split_src, whole_src = ...
local function fresh()
    local env = setmetatable({qerror = error}, {__index = _G})
    env.require = function(n) return {required = n} end
    env.dfhack = {}
    env.df = {}
    return env
end
local split = fresh()
assert(load(split_src, 'ai-society', 't', split))()
local whole = fresh()
assert(load(whole_src, 'ai-society', 't', whole))()
local function keys(e)
    local o = {}
    for k, v in pairs(e) do o[#o + 1] = k .. ':' .. type(v) end
    table.sort(o)
    return table.concat(o, ' ')
end
return keys(split), keys(whole), split, whole
"""


def _load():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    removed: list = []
    whole = hub_body(removed) + "\n" + "".join(part_body(n, removed) for n in PARTS)
    a, b, split, one = L.execute(ENV, module_src("ai-society.lua"), with_util(whole, "ai-society.lua"))
    return L, a, b, split, one


@test("load: the hub loading its parts defines the names the text in one piece defines (and only the "
      "split's own besides); every part marked; the parts' names are the module's")
def _():
    need_lua()
    L, a, b, split, one = _load()
    own = {"SOCIETY_PART_LOCALS:table", "PARTS:table", "PART_VERSIONS:table", "PART_SOURCES:table"}
    ga, gb = set(a.split()), set(b.split())
    # (the prelude hands PART_SOURCES to both; the one piece has no loader to read it)
    assert ga - own == gb - {"PART_SOURCES:table"}, (sorted(ga - own - gb), sorted(gb - ga))
    assert own <= ga, own - ga
    assert len(gb) > 100, len(gb)
    for fn in ("setup_shelter", "fill_shelter", "refresh_shelter", "find_burrow", "new_burrow",        # the hub
               "pasture", "nest_boxes", "train_war", "guard_gate", "gate_dogs", "pasture_report",      # animals
               "set_popcap", "expel_one", "give_trinkets", "stress_census", "accept_cups",             # needs
               "staff_location", "keep_mousers", "lower_ai_alarm", "stand_down",                       # posts
               "fill_recreation", "release_ai_burrows", "in_mood"):                # the burrows' forwarders
        assert f"{fn}:function" in ga, fn
    marks = dict(split.PART_VERSIONS.items())
    assert set(marks) == {HUB_NAME, *PARTS}, marks
    assert len(set(marks.values())) == 1, marks
    assert list(split.PARTS.values()) == ["animals", "needs", "posts"]


@test("load: the locals handed on are the hub's own (ai-util's module, utils, the report's walks: one "
      "object for every part); a swap of a module name reaches the parts")
def _():
    need_lua()
    L, a, b, split, one = _load()
    shared = split.SOCIETY_PART_LOCALS
    assert set(shared.keys()) == {"U", "report_citizens", "report_units", "utils"}, list(shared.keys())
    assert shared.utils.required == "utils"
    assert L.eval("rawequal")(shared.U, split.reqscript("ai-util")) and shared.U.report_citizens is not None
    # the report's walks go to ai-util's, looked up each call: a swap there is seen by a part
    # (posts' stand_down -> lower_ai_alarm, needs' expel_one are not run here: no game)
    shared.U.report_units = L.eval("function() return 'walked' end")
    assert shared.report_units() == "walked"
    # a part's function calls the hub's by the module's name: swapped, the swap is what runs
    # (stand_down, in posts, calls lower_ai_alarm and the forwarder release_ai_burrows)
    split.lower_ai_alarm = L.eval("function(o) return {swapped = o.why} end")
    split.release_ai_burrows = L.eval("function(dry) return {dry = dry} end")
    r = split.stand_down(L.table_from({"halted": True, "dry_run": True}))
    assert r.alarm.swapped == "the AI is halted" and r.burrows.dry is True
    # and the module's own name answers with the one environment the parts ran in
    assert L.eval("rawequal")(split.reqscript("ai-society"), split)


@test("load: a part run alone refuses (it is no script of its own)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    for n in PARTS:
        ok, err = L.execute(r"""
            local src, name = ...
            local env = setmetatable({qerror = function(m) error(m, 0) end}, {__index = _G})
            return pcall(assert(load(src, name, 't', env)))
        """, TEXTS[n], n)
        assert ok is False and str(err) == f"{n} is a part of ai-society; run ai-society", (n, err)


if __name__ == "__main__":
    finish()
