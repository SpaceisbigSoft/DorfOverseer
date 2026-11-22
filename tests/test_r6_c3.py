"""(r6, code health c3) lua/ai-bridge-report.lua and lua/ai-bridge-actions.lua
split by theme into files under ~60 KB each (ai-bridge-report-supplies, -fort,
-world; ai-bridge-actions-fort, -works, -civic), the hub loading them right
after the file they came from. Behaviour unchanged: the files together are the
old file's lines with only the split's scaffolding added (headers, version
marks, the few shared locals handed on); the parts loaded one after another
define the same globals as the text in one piece; the bridge's own
report_citizens/report_units are defined once and still go to ai-util's walks.

    python tests/test_r6_c3.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua, have_lua  # noqa: E402
from lua_modules_util import bridge_later_parts, bridge_part_src  # noqa: E402

LUA_DIR = ROOT / "lua"
FAMILIES = {
    "ai-bridge-report": ["ai-bridge-report-supplies", "ai-bridge-report-fort", "ai-bridge-report-world"],
    "ai-bridge-actions": ["ai-bridge-actions-fort", "ai-bridge-actions-works", "ai-bridge-actions-civic"],
}
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")


def hub_parts() -> list[str]:
    return re.findall(r"'([\w-]+)'", re.search(r"^BRIDGE_PARTS = \{(.*?)\}", HUB, re.M).group(1))


@test("sizes: the eight files are each under 60 KB (the two were 194 and 204 KB)")
def _():
    for stem, later in FAMILIES.items():
        for n in [stem] + later:
            size = (LUA_DIR / f"{n}.lua").stat().st_size
            assert size < 60 * 1024, (n, size)


@test("hub: BRIDGE_PARTS loads each file's later parts right after it, in the old order around them")
def _():
    parts = hub_parts()
    assert parts == ["ai-bridge-report", "ai-bridge-report-supplies", "ai-bridge-report-fort",
                     "ai-bridge-report-world", "ai-bridge-orders", "ai-bridge-actions", "ai-bridge-actions-fort",
                     "ai-bridge-actions-works", "ai-bridge-actions-civic", "ai-bridge-probes",
                     "ai-bridge-design"], parts
    for stem, later in FAMILIES.items():
        assert bridge_later_parts(stem) == later, stem


@test("parts: each new file is a bridge part (no module), refuses to run alone, carries its version mark")
def _():
    version = re.search(r"^BRIDGE_VERSION = '([^']+)'", HUB, re.M).group(1)
    for later in FAMILIES.values():
        for n in later:
            src = (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8")
            assert "--@ module = true" not in src, n
            assert f"if not BRIDGE_VERSION then qerror('{n} is a part of ai-bridge; run ai-bridge') end" in src, n
            assert f"PART_VERSIONS['{n}'] = '{version}'" in src, n


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not BRIDGE_VERSION then qerror\('ai-bridge-[\w-]+ is a part of ai-bridge; run ai-bridge'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-bridge-[\w-]+'\] = '[^']+'   -- .*",
    r"local utils = require\('utils'\)",
    r"local [\w, ]+ = (REPORT|ACTIONS)_PART_LOCALS\.\w+(, (REPORT|ACTIONS)_PART_LOCALS\.\w+)*",
    r"(REPORT|ACTIONS)_PART_LOCALS = \{[\w =,]+\}",
    r"(REPORT|ACTIONS)_PART_LOCALS\.\w+(, (REPORT|ACTIONS)_PART_LOCALS\.\w+)* = [\w, ]+",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")
TAKE_RE = re.compile(r"^(local utils = require\('utils'\)|local [\w, ]+ = (REPORT|ACTIONS)_PART_LOCALS\.[\w., ]+)$")
REPORT_NOTE = re.compile(r"-- \(r6\) This and report_units.*?Kept\.\n", re.S)

# sha256 of lua/ai-bridge-report.lua and lua/ai-bridge-actions.lua at 0.105.61
# (de94504), the last commit with each in one file
OLD_SHA = {
    "ai-bridge-report": "462c6a16fb20ec2824533016b8332b492ae762d168752e3033a26e091bce7d19",
    "ai-bridge-actions": "f0574c449d6e15d528eb1004157dbfa2a8922c851275e96e1a76349b8c1a70e9",
}
SPLIT_VERSION = "0.105.62"


def _body(text: str, later: bool, removed: list) -> str:
    """A file's text without the split's scaffolding (a later part's header and
    the locals it takes in; the "-- (r6)" block a file ends with), the removed
    lines put in `removed`."""
    lines = text.split("\n")
    if later:
        i = next(k for k, l in enumerate(lines) if l.startswith("PART_VERSIONS = ")) + 1
        while i < len(lines) and (lines[i] == "" or TAKE_RE.match(lines[i])):
            i += 1
        removed += lines[:i]
        lines = lines[i:]
    t = max((k for k, l in enumerate(lines) if l.startswith("-- (r6)")), default=None)
    if t is not None and all(SCAFFOLD_RE.match(l) for l in lines[t:]):
        removed += lines[t:]
        lines = lines[:t]
    return "\n".join(lines)


@test("unchanged: the files with the split's scaffolding taken out are, byte for byte, the one file "
      "of 0.105.61; what was taken out is headers, marks, comments and the shared locals handed on")
def _():
    version = re.search(r"^BRIDGE_VERSION = '([^']+)'", HUB, re.M).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r6 split against {SPLIT_VERSION}'s files (now {version})")
    for stem, later in FAMILIES.items():
        removed = []
        parts = [_body((LUA_DIR / f"{stem}.lua").read_text(encoding="utf-8"), False, removed)]
        parts += [_body((LUA_DIR / f"{n}.lua").read_text(encoding="utf-8"), True, removed) for n in later]
        whole = "\n\n".join(p.rstrip("\n") for p in parts) + "\n"
        notes = REPORT_NOTE.findall(whole)
        whole = REPORT_NOTE.sub("", whole)
        removed += [l for n in notes for l in n.split("\n") if l]
        assert hashlib.sha256(whole.encode("utf-8")).hexdigest() == OLD_SHA[stem], stem
        bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
        assert not bad, (stem, bad)
        assert len(notes) == (1 if stem == "ai-bridge-report" else 0), stem


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(text: str) -> set[str]:
    out = set()
    for l in text.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)\s*=", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a top-level local another file of its family declares without taking it in")
def _():
    for stem, later in FAMILIES.items():
        texts = {n: (LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in [stem] + later}
        family = set().union(*(_top_locals(t) for t in texts.values()))
        for n, t in texts.items():
            mine = _top_locals(t)
            code = [_strip(l) for l in t.split("\n")]
            for name in family - mine:
                pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
                hits = [i for i, l in enumerate(code, 1) if pat.search(l)
                        and not re.match(r"^\s+" + re.escape(name) + r" = true,", l)]   # a table key
                # ai-bridge-actions' LEDGER_FIELDS names kitchen_ban as a key on a line of keys
                hits = [i for i in hits if not (n == "ai-bridge-actions" and name == "kitchen_ban"
                                                and "= true," in code[i - 1])]
                assert not hits, (n, name, hits[:5])


ENV = r"""
local srcs, names = ...
local function fresh()
    local env = setmetatable({BRIDGE_VERSION = 'test', OUT_DIR = 'out', qerror = error}, {__index = _G})
    env.require = function(n) return {n = n} end
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
        if k ~= '_G' and k ~= 'require' then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
return keys(split), keys(whole), split
"""


@test("load: the parts loaded one after another define the same globals as the text in one piece; "
      "the shared locals are the same functions")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    for stem, later in FAMILIES.items():
        names = [stem] + later
        srcs = [(LUA_DIR / f"{n}.lua").read_text(encoding="utf-8") for n in names]
        a, b, env = L.execute(ENV, L.table_from(srcs), L.table_from(names))
        assert a == b, stem
        g = set(a.split())
        for fn in (["get_dwarves", "get_supplies", "get_dead", "get_moods", "get_health", "get_justice",
                    "get_hazards", "get_deep", "get_order_desk", "push_event", "start_watching",
                    "report_citizens", "report_units", "citizen_anchor"]
                   if stem == "ai-bridge-report" else
                   ["parse_plan", "parse_floor", "act_import_orders", "act_seed_reserve", "slaughter_pick_mood",
                    "act_display_artifact", "kitchen_hold", "send_mission_rules"]):
            assert f"{fn}:function" in g, (stem, fn)
        shared = env.REPORT_PART_LOCALS if stem == "ai-bridge-report" else env.ACTIONS_PART_LOCALS
        want = ({"inc", "usable", "TICKS_PER_DAY", "layer_at", "citizen_positions", "nearest"}
                if stem == "ai-bridge-report" else {"string_list"})
        assert set(shared.keys()) == want, (stem, list(shared.keys()))
        if stem == "ai-bridge-report":
            # inc, handed on: counts into a table, as the one file's local did
            t = L.table()
            shared.inc(t, "x")
            shared.inc(t, "x", 2)
            assert t["x"] == 3, t["x"]


@test("helpers: report_citizens/report_units defined once in the bridge, still ai-util's walks inside a "
      "report and DFHack's own outside one (or with no ai-util)")
def _():
    texts = {p.name: p.read_text(encoding="utf-8") for p in LUA_DIR.glob("ai-bridge*.lua")}
    for fn in ("report_citizens", "report_units"):
        defs = [n for n, t in texts.items() for _ in re.finditer(rf"^function {fn}\(", t, re.M)]
        assert defs == ["ai-bridge-report.lua"], (fn, defs)
    for n, t in texts.items():
        for fn in ("now_tick", "name_of", "enum_name", "report_citizens", "report_units"):
            assert not re.search(rf"^\s*local function {fn}\(", t, re.M), (n, fn)
    if not have_lua():
        return
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    src = (LUA_DIR / "ai-bridge-report.lua").read_text(encoding="utf-8")
    i = src.index("-- dfhack.units.getCitizens(...), once a report")
    j = src.index("\nend\n", src.index("function report_units()")) + 5
    out = L.execute(r"""
        local chunk = ...
        local env = setmetatable({}, {__index = _G})
        env.dfhack = {units = {getCitizens = function(a, b) return {'dfhack', tostring(a), tostring(b)} end}}
        env.df = {global = {world = {units = {active = 'vector'}}}}
        assert(load(chunk, 'c', 't', env))()
        local r = {}
        r[1] = env.report_citizens(true)[1]; r[2] = env.report_units()
        env.REPORT_CTX = {}                       -- a report, but no ai-util (a stub bridge)
        r[3] = env.report_citizens(false, true)[3]; r[4] = env.report_units()
        env.REPORT_CTX = {util = {citizens = function(...) return {'util', select('#', ...)} end,
                                  units_active = function() return 'walked once' end}}
        r[5] = env.report_citizens(true, false)[1]; r[6] = env.report_citizens(true, false)[2]
        r[7] = env.report_units()
        return r
    """, src[i:j])
    assert [out[k] for k in range(1, 8)] == ["dfhack", "vector", "true", "vector", "util", 2, "walked once"], \
        [out[k] for k in range(1, 8)]


if __name__ == "__main__":
    finish()
