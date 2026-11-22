"""(r9, code health t10) Two files of 60-86 KB split by theme, behaviour unchanged.

* lua/ai-gates-watch.lua (65 KB), already a part of the ai-gates hub: cut in
  two, ai-gates-watch (the watcher's helpers: who is outside, closing and
  opening an entrance's pieces, the lever links, the danger at a gate) and
  ai-gates-watch-look (a lockdown that outlives its cause, the brain away,
  the watcher's look, check, arm, open_all, the restored lockdown, planned
  gate buildings, doors), listed in ai-gates.lua's PARTS right after 'watch'.
  The three locals of the first the second uses are handed on as module names
  (_ENV.x = x), the gates parts' own pattern.
* lua/ai-missions.lua (66 KB), a standalone module: a hub in the ai-gates
  style (PARTS, part_path, PART_SOURCES for the tests, load into _ENV) with
  the readers, the armies, squads, reports, spoils and sites, and two parts:
  ai-missions-targets (the World screen, the landmasses, relations, targets)
  and ai-missions-report (status_of, report, away_units, probe_screen). The
  file-scope locals a later part uses go in MISSIONS_PART_LOCALS (functions
  never assigned again).

The proofs: each family with the split's scaffolding taken out is, byte for
byte, the one file of 0.105.64 (8183548), kept as sha256 + size.

    python tests/test_r9_t10.py
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

WATCH = ["ai-gates-watch", "ai-gates-watch-look"]
MHUB = "ai-missions"
MPARTS = ["ai-missions-targets", "ai-missions-report"]
MFAMILY = [MHUB] + MPARTS

# lua/ai-gates-watch.lua and lua/ai-missions.lua at 0.105.64 (8183548), the last commit with each in one file
WATCH_SHA = "b9b1f461c42dd22a1c9e716dc4bfdff3c2c268ad8b32d4d17167b9c50eca53ce"
WATCH_SIZE = 64999
MISSIONS_SHA = "a6115f4de064bf79cbd4ecf5fbee020ac804b97cc05e897c9b237390da39fb5d"
MISSIONS_SIZE = 65566
# the two header lines ai-gates-watch had before the cut (now three lines saying what went where)
WATCH_OLD_HEAD = ["-- ai-gates-watch: the watcher: who is outside, closing and opening an entrance's pieces,",
                  "-- the lever links, check(), arm(), open_all(); planned gate buildings; doors."]


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


@test("sizes: the five files are each under 60 KB (the two were 65 and 66 KB)")
def _():
    for n in WATCH + MFAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("ai-gates: watch-look is listed right after watch; the hub stays the gates' own otherwise")
def _():
    gates = text("ai-gates")
    assert re.search(r"^PARTS = \{'scan', 'watch', 'watch-look', 'fortify', 'works', 'wings', 'save', 'stuck'\}$",
                     gates, re.M)
    parts = split_parts("ai-gates.lua")
    assert parts[parts.index("ai-gates-watch") + 1] == "ai-gates-watch-look"


@test("ai-missions: a hub with PARTS in the old file's order; the tests' helpers read the family")
def _():
    hub = text(MHUB)
    assert re.search(r"^PARTS = \{'targets', 'report'\}$", hub, re.M)
    assert "ai-missions.lua" in SPLIT and split_parts("ai-missions.lua") == MPARTS
    assert split_src("ai-missions.lua") == "\n".join(text(n) for n in MFAMILY)
    assert re.search(r"^--@ module = true$", hub, re.M)
    gates = text("ai-gates")
    frm = "local function part_path(name)"
    # the loader is ai-gates' own, name for name, and stands last
    assert hub[hub.index(frm):] == gates[gates.index(frm):].replace("ai-gates", "ai-missions")
    assert hub.count(frm) == 1


@test("parts: each carries its version mark (one); the missions' parts refuse to run alone and are no modules")
def _():
    for n in WATCH + MPARTS:
        src = text(n)
        assert (f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'   -- (0.105.26) bumped "
                "with BRIDGE_VERSION") in src, n
        assert src.count(f"'{VERSION}'") == 1, n
        assert not re.search(r"^--@\s*module\s*=\s*true", src, re.M), n
    for n in MPARTS:
        assert f"if not MISSIONS_PART_LOCALS then qerror('{n} is a part of ai-missions; run ai-missions') end" in text(n)
    hub = text(MHUB)
    assert f"PART_VERSIONS = {{['{MHUB}'] = '{VERSION}'}}   -- (0.105.26) bumped with BRIDGE_VERSION" in hub
    assert hub.count(f"'{VERSION}'") == 1


# --- the byte-for-byte proofs -------------------------------------------------

WATCH_TAKE = re.compile(r"^local [\w, ]+ = [\w, ]+   -- \((13e|r9)\) the hub's and earlier parts' locals$")
WATCH_SCAFFOLD = re.compile(r"^(?:|--.*|PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-gates-watch-look'\] = '[^']+'   -- .*"
                            r"|local U, gate_name, lever_pull_pending, pull, set_entrance = U, gate_name, lever_pull_pending, "
                            r"pull, set_entrance   -- \(r9\) .*"
                            r"|_ENV\.lever_pull_pending, _ENV\.pull, _ENV\.set_entrance = lever_pull_pending, pull, set_entrance)$")


def _watch_whole(removed: list) -> str:
    first = text("ai-gates-watch").split("\n")
    k = first.index("--")                            # the new header, down to the old one's "--"
    removed += first[:k]
    first = WATCH_OLD_HEAD + first[k:]
    t = next(i for i, l in enumerate(first) if l.startswith("-- (r9)"))
    removed += first[t:]
    second = text("ai-gates-watch-look").split("\n")
    i = next(i for i, l in enumerate(second) if WATCH_TAKE.match(l)) + 1
    while second[i] == "":
        i += 1
    removed += second[:i]
    return "\n".join(first[:t]).rstrip("\n") + "\n\n" + "\n".join(second[i:])


M_TAKE = re.compile(r"^local [\w, ]+ = MISSIONS_PART_LOCALS\.[\w., ]+$")
M_SCAFFOLD = re.compile(r"^(?:|--.*"
                        r"|if not MISSIONS_PART_LOCALS then qerror\('ai-missions-\w+ is a part of ai-missions; run ai-missions'\) end"
                        r"|PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-missions-\w+'\] = '[^']+'   -- .*"
                        r"|PART_VERSIONS = \{\['ai-missions'\] = '[^']+'\}   -- .*"
                        r"|PARTS = \{'targets', 'report'\}"
                        r"|local [\w, ]+ = MISSIONS_PART_LOCALS\.\w+(, MISSIONS_PART_LOCALS\.\w+)*"
                        r"|MISSIONS_PART_LOCALS = \{[\w =,]+\}"
                        r"|MISSIONS_PART_LOCALS\.\w+(, MISSIONS_PART_LOCALS\.\w+)* = [\w, ]+)$")


def _m_body(n: str, removed: list) -> str:
    lines = text(n).split("\n")
    if n != MHUB:
        i = next(k for k, l in enumerate(lines) if M_TAKE.match(l)) + 1
        while i < len(lines) and lines[i] == "":
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = next((k for k, l in enumerate(lines) if l.startswith("-- (r9)")), None)
    if t is not None:
        tail = lines[t:]
        if n == MHUB:
            tail = tail[:tail.index("local function part_path(name)")]   # the loader: checked as ai-gates' own
        removed += tail
        lines = lines[:t]
    return "\n".join(lines)


def _m_whole(removed: list) -> str:
    bodies = [_m_body(n, removed) for n in MFAMILY]
    return "\n\n".join([b.rstrip("\n") for b in bodies[:-1]] + [bodies[-1]])


@test("unchanged: what was taken out is headers, marks, comments, the part list and the shared locals handed on")
def _():
    for whole_fn, scaffold, marks in ((_watch_whole, WATCH_SCAFFOLD, ("\n-- (r9)", "ai-gates-watch-look")),
                                      (_m_whole, M_SCAFFOLD, ("\n-- (r9)", "MISSIONS_PART_LOCALS", "PART_VERSIONS"))):
        removed = []
        whole = whole_fn(removed)
        bad = [l for l in removed if not scaffold.match(l)]
        assert not bad, bad
        for m in marks:
            assert m not in whole, m
    assert not re.search(r"^PARTS = ", _m_whole([]), re.M)


@test("proof 1: ai-gates-watch + ai-gates-watch-look without the split's scaffolding are, byte for byte, "
      "ai-gates-watch.lua of 0.105.64")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
    whole = _watch_whole([]).encode("utf-8")
    assert len(whole) == WATCH_SIZE, len(whole)
    assert hashlib.sha256(whole).hexdigest() == WATCH_SHA


@test("proof 2: ai-missions + its two parts without the split's scaffolding are, byte for byte, "
      "ai-missions.lua of 0.105.64")
def _():
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
    whole = _m_whole([]).encode("utf-8")
    assert len(whole) == MISSIONS_SIZE, len(whole)
    assert hashlib.sha256(whole).hexdigest() == MISSIONS_SHA


# --- the locals and the same names --------------------------------------------------

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


@test("locals: no file uses a file-scope local another file of its family declares without taking it in; "
      "the ones handed on are never assigned again")
def _():
    for family, handed in ((WATCH, ["lever_pull_pending", "pull", "set_entrance"]),
                           (MFAMILY, ["new_reader", "short", "enum_name", "name_of", "each", "int", "fort_ids",
                                      "fort_squads", "controllers", "army_members", "waiting_people", "reports",
                                      "spoils", "hostile", "sites", "world_screen", "screen", "walk", "link_type"])):
        texts = {n: text(n) for n in family}
        every = set().union(*(_top_locals(t) for t in texts.values()))
        for n, t in texts.items():
            mine = _top_locals(t)
            code = [_strip(l) for l in t.split("\n")]
            for name in sorted(every - mine):
                pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)\s*(?!=[^=])")
                hits = [i for i, l in enumerate(code, 1) if pat.search(l) and not re.search(
                    r"[{,]\s*" + re.escape(name) + r"\s*=", l)]
                assert not hits, (n, name, hits[:5])
        for n, t in texts.items():
            for i, l in enumerate(t.split("\n"), 1):
                c = _strip(l)
                for name in handed:
                    if re.search(r"(?<![\w.:])" + re.escape(name) + r"\s*=[^=]", c) \
                            and not re.match(r"^local ", c) and "MISSIONS_PART_LOCALS" not in c \
                            and "_ENV." not in c and not re.search(r"[{,]\s*" + re.escape(name) + r"\s*=", c) \
                            and not re.match(r"^\s+" + re.escape(name) + r" = .*,$", c):
                        raise AssertionError((n, i, l))


NAMES = r"""
local mode, srcs, names, lua_dir = ...
local env = setmetatable({qerror = error, dfhack = {}, df = {}}, {__index = _G})
if mode == 'hub' then
    env.PART_SOURCES = {}
    for i = 2, #srcs do env.PART_SOURCES[names[i]] = srcs[i] end
    assert(load(srcs[1], names[1], 't', env))()
elseif mode == 'file' then
    assert(loadfile(lua_dir .. '/ai-missions.lua', 't', env))()
elseif mode == 'gates' then
    env.U, env.key, env.unkey, env.gate_name = {}, function() end, function() end, function() end
    for i = 1, #srcs do assert(load(srcs[i], names[i], 't', env))() end
else
    for i = 1, #srcs do assert(load(srcs[i], names[i], 't', env))() end
end
local o = {}
for k, v in pairs(env) do o[k] = type(v) end
return o
"""


@test("names: the families loaded as their hubs load them define the same names as the one files did "
      "(plus the split's own)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    run = lua.execute("return function(...) " + NAMES + " end")

    def names(mode, ns, srcs):
        return dict(run(mode, lua.table(*srcs), lua.table(*ns), str(LUA_DIR)).items())

    old = names("seq", ["whole"], [_m_whole([])])
    for got in (names("hub", MFAMILY, [text(n) for n in MFAMILY]), names("file", [], [])):
        got.pop("PART_SOURCES", None)
        assert set(got) - set(old) == {"MISSIONS_PART_LOCALS", "PARTS", "PART_VERSIONS"}, set(got) - set(old)
        assert set(old) - set(got) == set(), set(old) - set(got)
        assert all(got[k] == old[k] for k in old), [k for k in old if got[k] != old[k]]
    old = names("gates", ["whole"], [_watch_whole([])])
    new = names("gates", WATCH, [text(n) for n in WATCH])
    assert set(new) - set(old) == {"PART_VERSIONS"} - set(old), set(new) - set(old)
    assert set(old) - set(new) == set() and all(new[k] == old[k] for k in old)


if __name__ == "__main__":
    finish()
