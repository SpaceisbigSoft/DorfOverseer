"""(r8, code health s4) lua/ai-builder-wells.lua (133 KB) split by theme into
builder parts under 60 KB each: ai-builder-wells (the spots), -wells-shaft (the
cavern shaft's gate and lid), -wells-watch (what may come up a shaft, the
watcher, the lids) and -wells-place (a shaft taken up again, the winter
cistern, place_well, the dig renewed), loaded by ai-builder.lua's PARTS right
after 'wells'. Behaviour unchanged: the files together are the old file's
lines with only the split's scaffolding added (headers, version marks, the
shared locals handed on); loaded one after another they define the globals the
one file defined.

    python tests/test_r8_s4.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from builder_wells_util import wells_parts, wells_src  # noqa: E402

LUA_DIR = ROOT / "lua"
STEM = "ai-builder-wells"
LATER = ["ai-builder-wells-shaft", "ai-builder-wells-watch", "ai-builder-wells-place"]
FAMILY = [STEM] + LATER
HUB = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
HANDED = ["STAIR_DOWN_SHAPE", "shaft_bottom", "hatch_at", "job_of",
          "free_mechanism_count", "shaft_kept", "abs_now", "gate_mem"]


def text(n: str) -> str:
    return (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")


def hub_parts() -> list[str]:
    return re.findall(r"'([\w-]+)'", re.search(r"^PARTS = \{([^}]*)\}", HUB, re.M).group(1))


@test("sizes: the four files are each under 60 KB (the one was 133 KB)")
def _():
    for n in FAMILY:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)


@test("hub: PARTS loads the three new parts right after 'wells', between 'farms' and 'cistern'")
def _():
    parts = hub_parts()
    i = parts.index("wells")
    assert parts[i:i + 5] == ["wells", "wells-shaft", "wells-watch", "wells-place", "cistern"], parts
    assert "farms" in parts[:i], parts
    assert len(parts) == len(set(parts)), parts
    assert wells_parts() == FAMILY, wells_parts()
    # the bridge finds a split module's parts from this line (split_part_names: '([%w_-]+)')
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", p) for p in parts), parts


@test("parts: each file is a builder part (no module of its own), says so, carries the hub's version mark")
def _():
    version = re.search(r"^PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB, re.M).group(1)
    for n in FAMILY:
        src = text(n)
        assert "--@ module = true" not in src and "--@module" not in src, n
        assert src.startswith(f"-- {n}: "), n
        assert "A part of ai-builder" in src[:600], n
        assert f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{version}'" in src, n
        assert len(re.findall(r"^PART_VERSIONS", src, re.M)) == 1, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-builder-wells[\w-]*'\] = '[^']+'   -- .*",
    r"local ez = ez",
    r"local \w+(, \w+)* =",
    r"    WELLS_PART_LOCALS\.\w+(, WELLS_PART_LOCALS\.\w+)*",
    r"WELLS_PART_LOCALS = \{(\w+ = \w+, )+\w+ = \w+,",
    r" +(\w+ = \w+, )+\w+ = \w+\}",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^(local ez = ez|local \w+(, \w+)* =|    WELLS_PART_LOCALS\.[\w., ]+)$")

# sha256 of lua/ai-builder-wells.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "168e467b6ec5836c300c44afde5ded894e325dcc0bc206f9f6284bfc735525ce"
SPLIT_VERSION = "0.105.63"
# the one file's first two lines (its header, reworded in the first part to name the others)
OLD_HEAD = ["-- ai-builder-wells: wells: the spot under the fort, on the shore, over a cavern or at the",
            "-- end of a gallery; the cavern shaft's gate and lid; place_well."]
NEW_HEAD_LINES = 5


def _body(n: str, removed: list) -> str:
    """A file's text without the split's scaffolding: a later part's header and
    the locals it takes in, the "-- (r8)" hand-over block a file ends with; the
    first file's reworded header put back as it was. Removed lines go in `removed`."""
    lines = text(n).split("\n")
    if n == STEM:
        removed += lines[:NEW_HEAD_LINES]
        lines = OLD_HEAD + lines[NEW_HEAD_LINES:]
    else:
        i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
        while i < len(lines) and (lines[i] == "" or TAKE_RE.match(lines[i])):
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r8)")), default=None)
    if t is not None and n != STEM and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the four files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.63; what was taken out is headers, marks, comments and the shared locals handed on")
def _():
    version = re.search(r"^PART_VERSIONS = \{\['ai-builder'\] = '([^']+)'\}", HUB, re.M).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {version})")
    removed: list = []
    whole = "\n\n".join(_body(n, removed).rstrip("\n") for n in FAMILY) + "\n"
    assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    # the scaffolding holds no code but the mark, `local ez = ez` and the hand-over
    code = [l for l in removed if l and not l.startswith("--")]
    assert len(code) == 4 + 6 + 2, code                 # shaft, watch, place


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


@test("locals: no file uses a file-scope local another file of the family declares without taking it in; "
      "what is handed on is never assigned again")
def _():
    texts = {n: text(n) for n in FAMILY}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert len(family) == 26, sorted(family)            # the one file's 26 file-scope locals
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
    # the hand-over: shaft gives, watch takes, exactly these, in the same order
    shaft, watch = texts["ai-builder-wells-shaft"], texts["ai-builder-wells-watch"]
    given = re.search(r"^WELLS_PART_LOCALS = \{(.*?)\}", shaft, re.M | re.S).group(1)
    assert re.findall(r"(\w+) = (\w+)", given) == [(h, h) for h in HANDED], given
    taken = re.findall(r"WELLS_PART_LOCALS\.(\w+)", watch)
    assert taken == HANDED, taken
    assert "WELLS_PART_LOCALS" not in texts[STEM] and "WELLS_PART_LOCALS" not in texts["ai-builder-wells-place"]
    assert shaft.rstrip("\n").endswith("gate_mem = gate_mem}")       # given once everything is defined
    # each is declared once in the shaft part and written nowhere else in the family
    whole = "\n".join(_strip(l) for l in wells_src().split("\n"))
    for h in HANDED + ["ez"]:
        writes = re.findall(r"^(.*(?<![\w.:])" + h + r"\s*=(?!=).*)$", whole, re.M)
        writes = [w for w in writes if "WELLS_PART_LOCALS" not in w and not w.startswith("local ")
                  and not re.match(r"^ +(\w+ = \w+, )+\w+ = \w+\}$", w)]
        assert not writes, (h, writes)
    for n in LATER:                                     # ez: the hub's global function, as in the one file
        assert len(re.findall(r"^local ez = ez$", texts[n], re.M)) == 1, n


# the globals lua/ai-builder-wells.lua defined in one file (0.105.63), read from it before the split
OLD_GLOBALS = """
CAVERN_NO_SPOT_DAYS CAVERN_SEARCH_SECONDS CAVERN_TOTAL_SECONDS CAVERN_WELL_MIN_DEPTH FILLED_WELL_HALF
FILLED_WELL_HALF_MAX FILLED_WELL_SECONDS FILLED_WELL_ZONE OPEN_SHAPE PART_VERSIONS SHAFT_CLEAR SHAFT_CLIMB
SHAFT_CLOSE SHAFT_DRY_MARGIN SHAFT_FAR SHAFT_LEVELS SHAFT_LINK_FAILS_MAX SHAFT_MARGIN SHAFT_MIN_SHUT SHAFT_NEAR
SHAFT_WATCH SHAFT_WATCH_TICKS STAIR_SHAPES WATCH_RELOAD WELL_DIG_UP WELL_FLOOR_SHAPES WELL_GALLERY_MAX
WELL_GALLERY_SECONDS WELL_GALLERY_WINDOW WELL_MAX_DROP WELL_RENEW_JOBS WELL_SCAN_MARGIN WELL_SEARCH_SECONDS
WELL_SHORE_FAR_MAX WELL_SHORE_NEAR WELL_SHORE_RADIUS WELL_ZONES
"""

ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
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
return keys(split), keys(whole), split
"""


@test("load: the parts loaded one after another define the same globals as the text in one piece and as "
      "the one file did; the handed-on locals are the shaft part's own functions")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    a, b, env = L.execute(ENV, L.table_from([text(n) for n in FAMILY]), L.table_from(FAMILY))
    assert a == b
    got = {k.split(":")[0] for k in a.split()}
    funcs = {k.split(":")[0] for k in a.split() if k.endswith(":function") and k != "OPEN_SHAPE:function"}
    assert got - funcs - {"WELLS_PART_LOCALS"} == set(OLD_GLOBALS.split()), \
        sorted((got - funcs - {"WELLS_PART_LOCALS"}) ^ set(OLD_GLOBALS.split()))
    # every global function of the one file, counted (45, and OPEN_SHAPE) and the ones other modules call by name
    assert len(funcs) == 45, len(funcs)
    for fn in ("water_below", "find_well_spot", "find_shore_well_spot", "find_cavern_well_spot",
               "find_gallery_well_spot", "designate", "shaft_gate_state", "well_shaft_step", "hostile_wild",
               "shaft_judge", "shaft_threats", "shaft_watch_start", "well_lids", "seal_well_stairs",
               "revive_cavern_well", "undo_well_cells", "well_safety_call", "find_filled_well_spot", "place_well",
               "well_spots_unreached", "well_dig_check", "renew_well_dig"):
        assert fn in funcs, fn
    shared = env.WELLS_PART_LOCALS
    assert sorted(shared.keys()) == sorted(HANDED), list(shared.keys())
    for h in HANDED:
        assert L.eval("type")(shared[h]) == ("table" if h == "STAIR_DOWN_SHAPE" else "function"), h
    assert shared.STAIR_DOWN_SHAPE.STAIR_DOWN is True and shared.STAIR_DOWN_SHAPE.STAIR_UPDOWN is True
    for n in FAMILY:
        assert env.PART_VERSIONS[n], n


@test("load: the real hub (ai-builder.lua with its loader) loads the four files and gives their names")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    B = L.execute(r"""
        local path = ...
        local env = setmetatable({}, {__index = _G})
        env._G = env
        env.reqscript = function(n) return setmetatable({}, {__index = function() return function() end end}) end
        env.dfhack = {}
        assert(loadfile(path, 't', env))()
        return env
    """, str(LUA_DIR / "ai-builder.lua"))
    for n in FAMILY:
        assert B.PART_VERSIONS[n] is not None, n
    for fn in ("find_well_spot", "well_shaft_step", "shaft_watch_start", "well_lids", "place_well", "renew_well_dig"):
        assert L.eval("type")(B[fn]) == "function", fn
    assert B.WELLS_PART_LOCALS.shaft_bottom is not None


if __name__ == "__main__":
    finish()
