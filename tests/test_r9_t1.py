"""(r9, code health t1) lua/ai-society-burrows.lua (90 KB) split by theme into a
hub and three parts under 60 KB each, the way lua/ai-gates.lua and
lua/ai-society.lua are: ai-society-burrows.lua (the recreation burrow, and the
loader) loads ai-society-burrows-hospital, -calm and -weather into its own
environment, in the old file's order. Behaviour unchanged: the hub and the
parts with the split's scaffolding taken out are the old file byte for byte;
loaded as the hub loads them they define the names the one file defined; the
file-scope locals a later file uses are handed on (BURROWS_PART_LOCALS) as the
same objects. The module is still ai-society's companion (its forwarders):
the tests' companion loading (tests/lua_modules_util.py prelude) feeds its
parts too.

    python tests/test_r9_t1.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import COMPANIONS, SPLIT, module_src, prelude, split_parts, split_src, with_util  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB_NAME = "ai-society-burrows"
PARTS = ["ai-society-burrows-hospital", "ai-society-burrows-calm", "ai-society-burrows-weather"]
# the file-scope locals of the hub and the earlier parts each part takes back
TAKES = {"ai-society-burrows-hospital": ["U", "report_citizens", "S", "rec_state", "zone_tiles"],
         "ai-society-burrows-calm": ["U", "report_citizens", "S", "rec_state", "zone_tiles", "HOSP_SCAN_MAX",
                                     "hb_state", "hb_now", "walk_group", "stand_pos", "can_walk", "in_zones",
                                     "pile_holds", "burrow_unit_ids", "in_tantrum", "hb_citizen", "shelter_id",
                                     "wk_take_out"],
         "ai-society-burrows-weather": ["U", "report_citizens", "S", "rec_state", "rec_dry", "hb_state", "hb_now",
                                        "calm_state"]}
HUB_GIVES = ["U", "report_citizens", "S", "rec_state", "rec_dry", "zone_tiles"]
# what a part adds to the hand-over for the parts after it
GIVES = {"ai-society-burrows-hospital": ["HOSP_SCAN_MAX", "hb_state", "hb_now", "walk_group", "stand_pos",
                                         "can_walk", "in_zones", "pile_holds", "burrow_unit_ids", "in_tantrum",
                                         "hb_citizen", "shelter_id", "wk_take_out"],
         "ai-society-burrows-calm": ["calm_state"],
         "ai-society-burrows-weather": []}
HUB = (LUA_DIR / "ai-society-burrows.lua").read_text(encoding="utf-8")
TEXTS = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in PARTS}

# sha256 of lua/ai-society-burrows.lua at 0.105.64 (8183548), the last commit with it in one file
OLD_SHA = "afb39069e5ebae6ea2ea08090bd9ec25d57bd54ac80e0e73881e5fd2aaedfb56"
OLD_SIZE = 90400
SPLIT_VERSION = "0.105.64"

HAND_OVER = ("BURROWS_PART_LOCALS = {U = U, report_citizens = report_citizens, S = S, rec_state = rec_state, "
             "rec_dry = rec_dry, zone_tiles = zone_tiles}")
TAIL_START = "-- (r9) this file's locals the later parts use, handed on (each takes them"
PART_TAIL = "-- (r9) this part's locals the parts after it use, handed on\n"
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
    local name = 'ai-society-burrows-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-society-burrows: ' .. name .. '.lua is missing (it goes beside ai-society-burrows.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
"""
SCAFFOLD_RE = re.compile("^(?:" + "|".join([
    r"",
    r"--.*",
    re.escape(HAND_OVER),
    r"PARTS = \{'hospital', 'calm', 'weather'\}",
    r"PART_VERSIONS = \{\['ai-society-burrows'\] = '[^']+'\}   -- .*",
    r"if not BURROWS_PART_LOCALS then qerror\('ai-society-burrows-\w+ is a part of ai-society-burrows; "
    r"run ai-society-burrows'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-society-burrows-\w+'\] = '[^']+'   -- .*",
    r"local [\w, ]+ = BURROWS_PART_LOCALS\.\w+(, BURROWS_PART_LOCALS\.\w+)*   -- \(r9\) the hub's and earlier "
    r"parts' locals",
    r"BURROWS_PART_LOCALS\.(?P<given>\w+) = (?P=given)",
]) + ")$")


# (the one line of the old file changed: its own mark, now started afresh at each load as ai-gates' is)
OLD_MARK = "PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-burrows'] = '%s'   -- (0.105.26) bumped with BRIDGE_VERSION\n"
NEW_MARK_RE = re.compile(r"^-- \(r9\) the hub's and its parts' version marks; started afresh at each load, so a part\n"
                         r"-- that failed to load shows as unmarked \(as ai-gates does\)\n"
                         r"PART_VERSIONS = \{\['ai-society-burrows'\] = '([^']+)'\}   -- \(0\.105\.26\) bumped with BRIDGE_VERSION\n", re.M)


def hub_mark() -> str:
    return NEW_MARK_RE.search(HUB).group(1)


def hub_body(removed: list) -> str:
    """The hub's own lines: all before the split's tail (the hand-over, the
    part list, the loader), which goes to `removed`."""
    i = HUB.index("\n" + TAIL_START + "\n")
    tail = HUB[i + 1:]
    assert tail.endswith(LOADER), "the hub ends with the loader"
    removed += tail[:-len(LOADER)].split("\n")
    body = HUB[:i]
    m = NEW_MARK_RE.search(body)
    assert m and len(NEW_MARK_RE.findall(body)) == 1
    removed += m.group(0).split("\n")
    return body[:m.start()] + OLD_MARK % m.group(1) + body[m.end():]


def part_body(name: str, removed: list) -> str:
    """A part's lines after its header (comments, the guard, the version mark,
    the locals it takes back, one empty line) and before its own hand-over at
    its end; both go to `removed`."""
    text = TEXTS[name]
    if GIVES[name]:
        j = text.index(PART_TAIL)
        removed += text[j:].split("\n")
        text = text[:j]
    lines = text.split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("local ") and "BURROWS_PART_LOCALS." in l)
    assert lines[i + 1] == "", name
    removed += lines[:i + 2]
    return "\n".join(lines[i + 2:])


@test("sizes: the four files are each under 60 KB (the one was 90 KB), and together the old file "
      "and a few KB of scaffolding")
def _():
    total = 0
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)
        total += size
    if hub_mark() == SPLIT_VERSION:
        assert OLD_SIZE < total < OLD_SIZE + 8 * 1024, total


@test("hub: PARTS lists hospital, calm, weather in the old file's order; the tests' helpers read the same; "
      "still a module of its own and ai-society's companion")
def _():
    listed = re.search(r"^PARTS = \{(.*?)\}$", HUB, re.M).group(1)
    assert re.findall(r"'([\w-]+)'", listed) == ["hospital", "calm", "weather"], listed
    assert split_parts("ai-society-burrows.lua") == PARTS
    assert "ai-society-burrows.lua" in SPLIT
    assert COMPANIONS["ai-society.lua"] == ["ai-society-burrows"]
    assert "\n--@module = true\n" in HUB and "local S = reqscript('ai-society')" in HUB
    found = sorted(p.stem for p in LUA_DIR.glob("ai-society-burrows-*.lua"))
    assert found == sorted(PARTS), found
    # the parts load last (nothing follows the loader: the old file ended with release_ai_burrows,
    # now the last part's last function)
    assert HUB.endswith(LOADER)
    assert TEXTS[PARTS[-1]].rstrip().endswith("return out\nend")
    assert split_src("ai-society-burrows.lua") == HUB + "".join("\n" + TEXTS[n] for n in PARTS)
    # the companion loading feeds the parts: ai-society's prelude carries them, and the hub's own
    pre = prelude("ai-society.lua")
    assert all(f'["{n}"] = ' in pre for n in PARTS + ["ai-society-animals", "ai-society-burrows"])
    assert all(f'["{n}"] = ' in prelude("ai-society-burrows.lua") for n in PARTS)


@test("parts: each is a part (no module), refuses to run alone, carries its version mark, takes back the "
      "locals it uses and hands on those the parts after it use")
def _():
    version = hub_mark()
    for n in PARTS:
        src = TEXTS[n]
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
        assert (f"if not BURROWS_PART_LOCALS then qerror('{n} is a part of ai-society-burrows; "
                f"run ai-society-burrows') end") in src, n
        marks = re.findall(r"^PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['([\w-]+)'\] = '([^']+)'",
                           src, re.M)
        assert marks == [(n, version)], (n, marks)
        take = "local " + ", ".join(TAKES[n]) + " = " + ", ".join("BURROWS_PART_LOCALS." + x for x in TAKES[n])
        assert src.count(take + "   -- (r9) the hub's and earlier parts' locals\n") == 1, n
        head = src[:src.index("PART_VERSIONS = ")].split("\n")
        assert all(l == "" or l.startswith("--") or l.startswith("if not BURROWS_PART_LOCALS") for l in head), n
        if GIVES[n]:
            assert src.endswith(PART_TAIL + "".join(f"BURROWS_PART_LOCALS.{x} = {x}\n" for x in GIVES[n])), n
        else:
            assert PART_TAIL not in src and "BURROWS_PART_LOCALS." + "x =" not in src
    # every name taken was handed on by the hub or an earlier part
    given = set(HUB_GIVES)
    for n in PARTS:
        assert set(TAKES[n]) <= given, (n, set(TAKES[n]) - given)
        given |= set(GIVES[n])
    assert HUB.count(HAND_OVER + "\n") == 1
    assert HUB.index(HAND_OVER) < HUB.index("\nPARTS = ") < HUB.index(LOADER)


@test("unchanged: the hub and the parts with the split's scaffolding taken out are, byte for byte, the one "
      "file of 0.105.64; what was taken out is headers, the guard, marks, the loader and the locals handed on")
def _():
    if hub_mark() != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {hub_mark()})")
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


@test("locals: no file uses a file-scope local another file of the family declares without taking it in "
      "(nor takes in one it does not use); those handed on are never assigned again")
def _():
    texts = {HUB_NAME: HUB, **TEXTS}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert {"U", "S", "rec_state", "hb_state", "calm_state", "wk_state", "HB_SRC"} <= family
    # (dist: a local of calm's; hospital's 'dist' are table keys and locals inside its functions)
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine - {"dist"}:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
        if n != HUB_NAME:
            assert set(TAKES[n]) <= mine, n
            for name in TAKES[n]:
                pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
                assert sum(1 for l in code if pat.search(l)) > 1, (n, name)
    handed = set(HUB_GIVES).union(*GIVES.values())
    for name in handed:
        writes = [l for t in texts.values() for l in map(_strip, t.split("\n"))
                  if re.search(r"(?<![\w.:])" + name + r"\s*(,\s*\w+\s*)*=(?!=)", l)
                  and not l.lstrip().startswith("local ") and "BURROWS_PART_LOCALS" not in l]
        assert not writes, (name, writes)


ENV = r"""
local split_src, whole_src = ...
local function fresh()
    local env = setmetatable({qerror = error}, {__index = _G})
    env.dfhack = {onStateChange = {}}
    env.df = {}
    env.SOC = {}
    env.reqscript = function(n) if n == 'ai-society' then return env.SOC end error('reqscript ' .. n) end
    return env
end
local split = fresh()
assert(load(split_src, 'ai-society-burrows', 't', split))()
local whole = fresh()
assert(load(whole_src, 'ai-society-burrows', 't', whole))()
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
    a, b, split, one = L.execute(ENV, module_src("ai-society-burrows.lua"),
                                 with_util(whole, "ai-society-burrows.lua"))
    return L, a, b, split, one


@test("load: the hub loading its parts defines the names the text in one piece defines (and only the "
      "split's own besides); every part marked; the parts' names are the module's")
def _():
    need_lua()
    L, a, b, split, one = _load()
    own = {"BURROWS_PART_LOCALS:table", "PARTS:table"}
    ga, gb = set(a.split()), set(b.split())
    assert ga - own == gb, (sorted(ga - own - gb), sorted(gb - ga))
    assert own <= ga, own - ga
    assert len(gb) > 50, len(gb)
    for fn in ("fill_recreation", "badly_wants_friends", "recreation_status", "recreation_tick", "in_mood",   # hub
               "hospital_zones", "well_gives_water", "is_patient", "in_quarantine", "hospital_burrow_status",
               "hospital_burrow_tick",                                                                  # hospital
               "calm_burrow_status", "calm_burrow_tick",                                                # calm
               "weather_keep_in", "weather_keep_in_status", "release_ai_burrows"):                      # weather
        assert f"{fn}:function" in ga, fn
    marks = dict(split.PART_VERSIONS.items())
    assert set(marks) == {HUB_NAME, *PARTS}, marks
    assert len(set(marks.values())) == 1, marks
    assert list(split.PARTS.values()) == ["hospital", "calm", "weather"]
    # the map-unload hook of the hospital's source cache is set up as before
    assert "ai-society-burrows-hb" in dict(split.dfhack.onStateChange.items())


@test("load: the locals handed on are the hub's and parts' own objects (one state table reader, one "
      "ai-util); a part's function reaches the earlier files' through them")
def _():
    need_lua()
    L, a, b, split, one = _load()
    shared = split.BURROWS_PART_LOCALS
    assert set(shared.keys()) == set(HUB_GIVES).union(*GIVES.values()), sorted(shared.keys())
    assert L.eval("rawequal")(shared.U, split.reqscript("ai-util"))
    assert L.eval("rawequal")(shared.S, split.SOC)
    # release_ai_burrows (weather) reads the four states through the handed-on readers (hub's rec_state,
    # hospital's hb_state, calm's calm_state, its own wk_state): with ai-util's site data swapped, every
    # burrow reads empty and nothing is let out, without an error
    split.U = None
    shared.U.site_get = L.eval("function(k) return nil end")
    shared.U.site_put = L.eval("function() end")
    r = split.release_ai_burrows(True)
    assert not any(str(k).endswith("_error") for k in r.keys()), dict(r.items())
    # a swap of a module name reaches the parts: release_ai_burrows calls the ticks by the module's name
    shared.U.site_get = L.eval("function(k) return {members = {[7] = 1}} end")
    split.recreation_tick = L.eval("function(...) return {released = {1, 2}} end")
    split.hospital_burrow_tick = L.eval("function(...) return {released = 3} end")
    split.calm_burrow_tick = L.eval("function(...) return {released = {}} end")
    split.weather_keep_in = L.eval("function(...) return {released = {9}} end")
    r = dict(split.release_ai_burrows(True).items())
    assert r == {"recreation": 2, "hospital": 3, "weather": 1}, r


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
        assert ok is False and str(err) == f"{n} is a part of ai-society-burrows; run ai-society-burrows", (n, err)


@test("companion: ai-society loaded from its text reaches the parts' functions through its forwarders")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(r"""
        local src = ...
        local env = setmetatable({}, {__index = _G})
        env.df = {global = {plotinfo = {group_id = 1}}}
        env.dfhack = {onStateChange = {}}
        env.require = function() return {} end
        assert(load(src, 'ai-society', 't', env))()
        return env
    """, module_src("ai-society.lua"))
    B = env.reqscript("ai-society-burrows")
    assert set(dict(B.PART_VERSIONS.items())) >= {HUB_NAME, *PARTS}
    for fn in ("is_patient", "calm_burrow_tick", "release_ai_burrows"):
        assert L.eval("type")(B[fn]) == "function", fn
    B.is_patient = L.eval("function(u) return 'swapped' end")
    assert env.is_patient(L.table_from({})) == "swapped"     # the forwarder looks the name up on call


if __name__ == "__main__":
    finish()
