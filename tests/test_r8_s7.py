"""(r8, code health 13c, s7) lua/ai-military.lua (111 KB) split by theme into a
hub and three parts under 60 KB each (ai-military-draft, -uniforms, -duty),
loaded into the hub's own environment as lua/ai-gates.lua loads its parts.
Behaviour unchanged: the hub and the parts, in load order and with only the
split's scaffolding taken out (headers, guards, version marks, the loader, the
hub's locals handed on), are the one file's lines; loaded they define the same
names as the text in one piece; the hub's locals reach the parts as the same
objects; the forwarders to the companion lua/ai-military-gear.lua (not part of
this split) still stand, and run, last.

    python tests/test_r8_s7.py
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
HUB_NAME = "ai-military"
PARTS = ["ai-military-draft", "ai-military-uniforms", "ai-military-duty"]
# the hub's file-scope locals each part takes in (MILITARY_PART_LOCALS)
TAKES = {
    "ai-military-draft": ["U", "report_citizens", "COMBAT_SKILLS", "wants_fight", "fight_focus"],
    "ai-military-uniforms": ["U"],
    "ai-military-duty": ["U", "report_citizens", "report_units", "gear", "save_shelter_marks", "order_tick",
                         "is_guard_order", "is_ai_order"],
}


def read(stem: str) -> str:
    return (LUA_DIR / f"{stem}.lua").read_text(encoding="utf-8")


HUB = read(HUB_NAME)
# where the hub's scaffolding (the hand-over, PARTS, the loader) starts and ends
SCAF_FROM = "-- (r8) The rest of the military lives in parts beside this file"
SCAF_TO = "-- (r8) the parts end here; what follows stood at the end of the one file"


@test("sizes: the hub and the three parts are each under 60 KB (the one file was 111 KB)")
def _():
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)
    assert (LUA_DIR / "ai-military-gear.lua").exists()          # the companion, as it was


@test("hub: PARTS lists the parts in the old file's order; the test helpers know the hub; "
      "the gear companion is still a companion, not a part")
def _():
    listed = re.search(r"^PARTS = \{([^}]*)\}", HUB, re.M).group(1)
    assert re.findall(r"'([\w-]+)'", listed) == ["draft", "uniforms", "duty"], listed
    assert "ai-military.lua" in SPLIT and split_parts("ai-military.lua") == PARTS
    assert COMPANIONS["ai-military.lua"] == ["ai-military-gear"]
    assert "--@module = true" in HUB
    # the loader is ai-gates' own, line for line but for the name
    def loader(src):
        return src[src.index("local function part_path(name)"):src.rindex("        assert(loadfile(path, 't', _ENV))()")]
    assert loader(HUB) == loader(read("ai-gates")).replace("ai-gates", "ai-military")
    assert "load(src, name, 't', _ENV)" in HUB and "PART_SOURCES[name]" in HUB


@test("parts: each is a part (no module line), refuses to run alone, carries one version mark, the hub's")
def _():
    version = re.search(r"^PART_VERSIONS = \{\['ai-military'\] = '([^']+)'\}", HUB, re.M).group(1)
    for n in PARTS:
        src = read(n)
        assert not re.search(r"^--@ ?module", src, re.M), n
        assert f"if not MILITARY_PART_LOCALS then qerror('{n} is a part of ai-military; run ai-military') end" in src, n
        assert src.count(f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{version}'") == 1, n
        assert len(re.findall(r"PART_VERSIONS\['", src)) == 1, n
        take = "local " + ", ".join(TAKES[n]) + " = " + ", ".join("MILITARY_PART_LOCALS." + x for x in TAKES[n])
        assert src.count(take) == 1, n
    handed = re.search(r"^MILITARY_PART_LOCALS = \{([^}]*)\}$", HUB, re.M).group(1)
    pairs = [p.strip() for p in handed.split(",")]
    want = []
    for n in PARTS:
        want += [x for x in TAKES[n] if x not in want]
    assert pairs == [f"{x} = {x}" for x in want], pairs


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not MILITARY_PART_LOCALS then qerror\('ai-military-\w+ is a part of ai-military; run ai-military'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['ai-military-\w+'\] = '[^']+'   -- .*",
    r"local [\w, ]+ = MILITARY_PART_LOCALS\.\w+(, MILITARY_PART_LOCALS\.\w+)*   -- \(r8\) the hub's locals",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")

# sha256 of lua/ai-military.lua at 0.105.63 (a2b59e8), the last commit with it in one file
OLD_SHA = "8e3f3b742aa3ef1d6c7c6e066635a30a4ad9386095d4cc2030c41edf0abe9461"
SPLIT_VERSION = "0.105.63"


def pieces() -> tuple[list[str], list[str], str]:
    """The old file's text in its pieces, in load order (the hub's head, each
    part's body, the hub's tail), the parts' scaffolding lines taken out, and
    the hub's scaffolding (one block)."""
    a, b = HUB.index(SCAF_FROM), HUB.index(SCAF_TO)
    b_end = HUB.index("\n", b) + 1
    out = [HUB[:a]]
    removed = []
    for n in PARTS:
        lines = read(n).split("\n")
        i = next(k for k, l in enumerate(lines) if l.startswith("local ") and "MILITARY_PART_LOCALS." in l) + 1
        while lines[i] == "":
            i += 1
        removed += lines[:i]
        out.append("\n".join(lines[i:]))
    out.append(HUB[b_end:])
    return out, removed, HUB[a:b_end]


def whole_text() -> str:
    return "\n\n".join(p.strip("\n") for p in pieces()[0]) + "\n"


@test("unchanged: the hub's head, the parts' bodies and the hub's tail are, byte for byte, the one file of "
      "0.105.63; what was taken out is headers, guards, marks, the locals taken in, and the hub's loader")
def _():
    out, removed, hub_scaffold = pieces()
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    # the hub's block: comments, the hand-over, PARTS, the mark, part_path and the loader loop; nothing else
    code = [l for l in hub_scaffold.split("\n") if l.strip() and not l.strip().startswith("--")]
    assert code[0].startswith("MILITARY_PART_LOCALS = {") and code[1].startswith("PARTS = {"), code[:2]
    assert code[2].startswith("PART_VERSIONS = {['ai-military'] = '"), code[2]
    assert code[3] == "local function part_path(name)" and code[-1] == "end", (code[3], code[-1])
    assert sum(1 for l in code if re.match(r"^\S", l) and not l.startswith(("end", "local function part_path")))  \
        == 4, code                                 # the three assignments and the `for` of the loader
    # the forwarders stand last, after the parts are loaded
    tail = out[-1].lstrip("\n")
    assert tail.startswith("-- --- the gear (lua/ai-military-gear.lua)")
    assert tail.rstrip("\n").endswith("    _ENV[name] = function(...) return gear()[name](...) end\nend")
    assert HUB.index("assert(loadfile(path, 't', _ENV))()") < HUB.index("_ENV[name] = function(...)")
    version = re.search(r"^PART_VERSIONS = \{\['ai-military'\] = '([^']+)'\}", HUB, re.M).group(1)
    if version != SPLIT_VERSION:
        skip(f"a one-off proof of the r8 split against {SPLIT_VERSION}'s file (now {version})")
    assert hashlib.sha256(whole_text().encode("utf-8")).hexdigest() == OLD_SHA


def _strip(line: str) -> str:
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def _top_locals(text: str) -> set[str]:
    out = set()
    for l in text.split("\n"):
        m = re.match(r"^local function (\w+)", l) or re.match(r"^local (\w+(?:\s*,\s*\w+)*)", l)
        if m:
            out |= set(re.split(r"\s*,\s*", m.group(1)))
    return out


@test("locals: no file uses a file-scope local another file of the family declares without taking it in; "
      "none of those handed on is assigned again anywhere")
def _():
    texts = {n: read(n) for n in [HUB_NAME] + PARTS}
    family = set().union(*(_top_locals(t) for t in texts.values()))
    assert {"U", "gear", "GEAR", "is_ai_order", "candidates", "held", "apply_template", "test_spot"} <= family
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            # probe_squads (ai-military-duty) has a local of its own named `held` (a flag), not
            # ai-military-draft's held(fort, code): declared in the function before it is read
            if n == "ai-military-duty" and name == "held":
                assert any(re.match(r"^\s+local held = false$", code[i - 1]) for i in hits), hits
                first = min(hits)
                assert re.match(r"^\s+local held = false$", code[first - 1]), code[first - 1]
                hits = []
            assert not hits, (n, name, hits[:5])
    handed = set().union(*map(set, TAKES.values()))
    for n, t in texts.items():
        for i, l in enumerate(t.split("\n"), 1):
            c = _strip(l)
            for name in handed:
                m = re.search(r"(?<![\w.:])" + re.escape(name) + r"\s*(?:,\s*[\w.]+\s*)*=(?!=)", c)
                if not m:
                    continue
                ok = (c.startswith(("local ", "MILITARY_PART_LOCALS = "))            # declared; handed on; taken in
                      or re.match(r"^\s+local " + re.escape(name) + r"\b", c)          # a function's own local
                      or re.search(r"[{,]\s*" + re.escape(name) + r"\s*=", c)          # a table's key
                      or (re.match(r"^\s+" + re.escape(name) + r" = ", c)               # (on a line of keys)
                          and c.rstrip().endswith((",", "})"))))
                assert ok, (n, i, l)


RIG = r"""
local hub_src, whole_src, part_srcs = ...
local function fresh()
    local env = setmetatable({}, {__index = _G})
    env.qerror = error
    return env
end
local split = fresh()
assert(load(hub_src, 'ai-military', 't', split))()
local whole = fresh()
assert(load(whole_src, 'ai-military-whole', 't', whole))()
local SCAFFOLD = {PARTS = true, PART_VERSIONS = true, MILITARY_PART_LOCALS = true, PART_SOURCES = true}
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if not SCAFFOLD[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
-- a part run alone refuses
local alone = {}
for name, src in pairs(part_srcs) do
    local ok, err = pcall(assert(load(src, name, 't', fresh())))
    alone[name] = (not ok) and tostring(err) or 'ran'
end
return keys(split), keys(whole), split, whole, alone
"""


def rig():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    out = L.execute(RIG, module_src("ai-military.lua"), with_util(whole_text(), "ai-military.lua"),
                    L.table_from({n: read(n) for n in PARTS}))
    return L, out


@test("load: the hub with its parts defines the same names as the text in one piece (but the split's own: "
      "PARTS, PART_VERSIONS, MILITARY_PART_LOCALS); every part marked; a part run alone refuses")
def _():
    L, (a, b, split, whole, alone) = rig()
    assert a == b, (set(a.split()) ^ set(b.split()))
    g = set(a.split())
    for fn in ["pick_soldiers", "report", "squad_power", "gate_levers",                 # the hub
               "nursing_mothers", "draftable", "fill", "trim", "release", "make_squad",  # draft
               "probe", "pick_template", "set_uniform", "adopt_uniform", "uniform_set",  # uniforms
               "set_routine", "kill_target_ok", "orders", "defend", "assign_barracks",   # duty
               "probe_squads", "shelter", "station",
               "stray_report", "assign_bolts", "gear_report"]:                           # the forwarders
        assert f"{fn}:function" in g, fn
    assert [split.PARTS[i] for i in range(1, 4)] == ["draft", "uniforms", "duty"]
    version = split.PART_VERSIONS["ai-military"]
    assert {k: v for k, v in split.PART_VERSIONS.items()} == {n: version for n in [HUB_NAME] + PARTS}
    assert whole.PARTS is None and whole.MILITARY_PART_LOCALS is None
    for n in PARTS:
        assert f"{n} is a part of ai-military; run ai-military" in alone[n], (n, alone[n])


@test("one module: a name swapped on the module reaches the parts; a part's function reaches the hub's and "
      "another part's; the hub's locals are handed on as the same objects; the gear companion sees the parts")
def _():
    L, (_, _, env, _, _) = rig()
    shared = env.MILITARY_PART_LOCALS
    want = set().union(*map(set, TAKES.values()))
    assert set(shared.keys()) == want, list(shared.keys())
    assert L.eval("rawequal")(shared.U, env.reqscript("ai-util"))
    # is_ai_order, handed to ai-military-duty, is the function the hub's ai_order() calls
    probe = L.eval("""function(env)
        local seen = {}
        local o = setmetatable({}, {__index = function(_, k) seen[#seen + 1] = k; return nil end})
        pcall(env.ai_order, o, 1); local a = table.concat(seen, ' '); seen = {}
        pcall(env.MILITARY_PART_LOCALS.is_ai_order, o, 1); return a, table.concat(seen, ' ') end""")
    a, b = probe(env)
    assert a == b and a, (a, b)
    # a swap (as the tests and DFHack's reload do) reaches a part: set_routine and adopt_uniform
    # (ai-military-duty, -uniforms) call the hub's fort_squad by its module name
    env.fort_squad = L.eval("function(id) SEEN = (SEEN or 0) + 1; return nil end")
    r = env.set_routine(7, "Off duty")
    assert r.rejected and r.error == "no such squad in this fort"
    r = env.adopt_uniform(7, True)
    assert r.ok is False and L.globals().SEEN == 2, L.globals().SEEN
    # ai-military-draft's make_squad reads ai-military-uniforms' uniform_set by name, defined after it
    assert "uniform_set(" in read("ai-military-draft") and "\nuniform_set = position_has_uniform" in \
        read("ai-military-uniforms")
    assert env.uniform_set is not None
    # the companion: loaded over this module, it finds the parts' names on it
    gear = env.reqscript("ai-military-gear")
    M = L.eval("function(g) return g.reqscript('ai-military') end")(gear)
    assert L.eval("rawequal")(M, env)
    assert M.station is not None and M.make_squad is not None and M.set_uniform is not None
    assert gear.PART_VERSIONS["ai-military-gear"] == env.PART_VERSIONS["ai-military"]


@test("from files: loaded from its file (as the game loads it, no PART_SOURCES) the hub finds its parts "
      "beside it and marks all three")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    n, a, b, c = L.execute(r"""
        local dir = ...
        local envs = {}
        local function req(name)
            if envs[name] then return envs[name] end
            local e = setmetatable({}, {__index = _G}); envs[name] = e
            e.reqscript = req; e.dfhack = {}
            assert(loadfile(dir .. name .. '.lua', 't', e))()
            return e
        end
        local M = req('ai-military')
        local n = 0
        for _ in pairs(M.PART_VERSIONS) do n = n + 1 end
        return n, type(M.station), type(M.make_squad), type(M.stray_report)
    """, str(LUA_DIR) + "/")
    assert (n, a, b, c) == (4, "function", "function", "function"), (n, a, b, c)


@test("readers: split_src reads the family; no test reads ai-military.lua alone for a line a part holds")
def _():
    fam = split_src("ai-military.lua")
    for line in ["function make_squad(dry_run, txt, opts)", "function station(squad_id, x, y, z, dry_run)",
                 "function set_uniform(squad_id, kind, dry_run, txt, ranged)", "function report(txt)"]:
        assert fam.count(line) == 1, line
    assert "function report(txt)" in HUB and "function make_squad(" not in HUB


if __name__ == "__main__":
    finish()
