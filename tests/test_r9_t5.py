"""(r9, code health 13c, t5) lua/gui/ai-overseer.lua (80 KB), the in-game
panel, split by theme into a hub and two parts under 60 KB each, beside it in
lua/gui/: gui/ai-overseer-rules (the Rules and Army tabs) and
gui/ai-overseer-culture (the Needs you, Culture and Camera tabs). The hub
keeps its head (helpers, the sliders' page, the AI page) and its tail (the
window, the screen, the module return and the command's show) and loads the
parts in between into its own environment, as lua/ai-gates.lua loads its parts.
Behaviour unchanged: the hub's head, the parts' bodies and the hub's tail are,
byte for byte, the one file of 0.105.64 (8183548); loaded, they define the
same names as the text in one piece; the hub's locals reach the parts as the
same objects, and CULTURE_KEY comes back to the window.

    python tests/test_r9_t5.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip, need_lua  # noqa: E402
from lua_modules_util import SPLIT, split_parts, split_src  # noqa: E402

LUA_DIR = ROOT / "lua"
HUB_NAME = "gui/ai-overseer"
PARTS = ["gui/ai-overseer-rules", "gui/ai-overseer-culture"]
# the hub's file-scope locals each part takes in (OVERSEER_PART_LOCALS)
TAKES = {"gui/ai-overseer-rules": ["widgets", "S"], "gui/ai-overseer-culture": ["dialogs", "widgets", "S"]}
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
VERSION = re.search(r"^BRIDGE_VERSION = '([^']+)'", BRIDGE, re.M).group(1)


def read(name: str) -> str:
    return (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8")


HUB = read(HUB_NAME)
SCAF_FROM = "---------------------------------------------------------------------------\n-- (r9) The rest of the panel's tabs lives in parts beside this file"
SCAF_TO = "-- (r9) the parts end here; what follows stood at the end of the one file\n\n"
HAND_BACK = "OVERSEER_PART_LOCALS.CULTURE_KEY = CULTURE_KEY   -- (r9) handed back: the window (in the hub) reads it\n"

# lua/gui/ai-overseer.lua at 0.105.64 (8183548), the last commit with it in one file
OLD_SHA = "0bf1ca0c2ea95e9728334a3c4ca1d6156ce85b8b3913da3bfca4335276d2ca13"
OLD_SIZE = 80361
SPLIT_VERSION = "0.105.64"


@test("sizes: the hub and the two parts are each under 60 KB (the one file was 80 KB); all in lua/gui/")
def _():
    for n in [HUB_NAME] + PARTS:
        size = (LUA_DIR / f"{n}.lua").stat().st_size
        assert size < 60 * 1024, (n, size)
    assert sorted(p.name for p in (LUA_DIR / "gui").glob("*.lua")) == \
        ["ai-overseer-culture.lua", "ai-overseer-rules.lua", "ai-overseer.lua"]


@test("hub: still the module and the command (--@ module = true, the module return, the show, last); "
      "PARTS in the old file's order; the test helpers know it; the loader is ai-gates' adapted to gui/")
def _():
    assert HUB.startswith("-- gui/ai-overseer: the AI Overseer's control panel.\n")
    assert re.search(r"^--@ module = true$", HUB, re.M)
    listed = re.search(r"^PARTS = \{([^}]*)\}", HUB, re.M).group(1)
    assert re.findall(r"'([\w-]+)'", listed) == ["rules", "culture"], listed
    assert "gui/ai-overseer.lua" in SPLIT and split_parts("gui/ai-overseer.lua") == PARTS
    assert f"PART_VERSIONS = {{['gui/ai-overseer'] = '{VERSION}'}}   -- (0.105.26) bumped with BRIDGE_VERSION" in HUB
    assert "debug.getinfo(1, 'S').source:match('^@(.*[/\\\\])')" in HUB
    assert "local path = part_path('ai-overseer-' .. part, name)" in HUB
    assert "return dfhack.findScript and dfhack.findScript(name) or nil" in HUB    # by its script name, gui/...
    assert "assert(load(src, name, 't', _ENV))()" in HUB and "assert(loadfile(path, 't', _ENV))()" in HUB
    assert HUB.rstrip("\n").endswith("view = view and view:raise() or OverseerScreen{}:show()")
    assert HUB.index("assert(loadfile(path, 't', _ENV))()") < HUB.index("OverseerWindow = defclass(")
    assert HUB.index("assert(loadfile(path, 't', _ENV))()") < HUB.index("if dfhack_flags.module then")


@test("parts: each is a part (no module line), refuses to run alone, carries one version mark, the bridge's")
def _():
    for n in PARTS:
        src = read(n)
        assert not re.search(r"^--@ ?module", src, re.M), n
        assert f"if not OVERSEER_PART_LOCALS then qerror('{n} is a part of gui/ai-overseer; run gui/ai-overseer') end" in src, n
        assert src.count(f"PART_VERSIONS = PART_VERSIONS or {{}}; PART_VERSIONS['{n}'] = '{VERSION}'") == 1, n
        assert len(re.findall(r"PART_VERSIONS\['", src)) == 1, n
        take = "local " + ", ".join(TAKES[n]) + " = " + ", ".join("OVERSEER_PART_LOCALS." + x for x in TAKES[n])
        assert src.count(take) == 1, n
    handed = re.search(r"^OVERSEER_PART_LOCALS = \{([^}]*)\}$", HUB, re.M).group(1)
    assert [p.strip() for p in handed.split(",")] == ["dialogs = dialogs", "widgets = widgets", "S = S"]
    assert read("gui/ai-overseer-culture").endswith(HAND_BACK)
    assert "\nlocal CULTURE_KEY = OVERSEER_PART_LOCALS.CULTURE_KEY   -- (r9) the culture part's, for the window\n" in HUB


SCAFFOLD = [
    r"",
    r"--.*",
    r"if not OVERSEER_PART_LOCALS then qerror\('gui/ai-overseer-\w+ is a part of gui/ai-overseer; run gui/ai-overseer'\) end",
    r"PART_VERSIONS = PART_VERSIONS or \{\}; PART_VERSIONS\['gui/ai-overseer-\w+'\] = '[^']+'   -- .*",
    r"local [\w, ]+ = OVERSEER_PART_LOCALS\.\w+(, OVERSEER_PART_LOCALS\.\w+)*   -- \(r9\) the hub's locals",
]
SCAFFOLD_RE = re.compile("^(?:" + "|".join(SCAFFOLD) + ")$")


def pieces() -> tuple[list[str], list[str], str]:
    """The old file's text in its pieces, in load order (the hub's head, each
    part's body, the hub's tail), the parts' scaffolding taken out, and the
    hub's scaffolding (one block)."""
    a, b = HUB.index(SCAF_FROM), HUB.index(SCAF_TO) + len(SCAF_TO)
    out, removed = [HUB[:a]], []
    for n in PARTS:
        src = read(n)
        if src.endswith(HAND_BACK):
            src = src[:-len(HAND_BACK)]
        lines = src.split("\n")
        i = next(k for k, l in enumerate(lines) if l.startswith("local ") and "OVERSEER_PART_LOCALS." in l) + 2
        assert lines[i - 1] == "", n          # one blank line after the take-in, then the old lines
        removed += lines[:i]
        out.append("\n".join(lines[i:]))
    out.append(HUB[b:])
    return out, removed, HUB[a:b]


def whole_text() -> str:
    return "".join(pieces()[0])        # cut at blank lines: joined as they are, nothing evened out


@test("unchanged: the hub's head, the parts' bodies and the hub's tail are, byte for byte, the one file of "
      "0.105.64; what was taken out is headers, guards, marks, the locals taken in and handed back, the loader")
def _():
    out, removed, hub_scaffold = pieces()
    bad = [l for l in removed if not SCAFFOLD_RE.match(l)]
    assert not bad, bad
    code = [l for l in hub_scaffold.split("\n") if l.strip() and not l.strip().startswith("--")]
    assert code[0].startswith("OVERSEER_PART_LOCALS = {") and code[1].startswith("PARTS = {"), code[:2]
    assert code[2].startswith("PART_VERSIONS = {['gui/ai-overseer'] = '"), code[2]
    assert code[3] == "local function part_path(file, name)", code[3]
    assert code[-1].startswith("local CULTURE_KEY = OVERSEER_PART_LOCALS.CULTURE_KEY"), code[-1]
    top = [l for l in code if re.match(r"^\S", l) and not l.startswith(("end", "local function part_path"))]
    assert len(top) == 5, top        # the hand-over, PARTS, the mark, the loader's `for`, CULTURE_KEY taken back
    assert out[1].startswith("---------------------------------------------------------------------------\n"
                             "-- The Rules tab: what the planner may build and do on its own.")
    assert out[2].startswith("---------------------------------------------------------------------------\n"
                             "-- The Needs you tab:")
    assert out[3].startswith("---------------------------------------------------------------------------\n"
                             "-- The window\n")
    if VERSION != SPLIT_VERSION:
        skip(f"a one-off proof of the r9 split against {SPLIT_VERSION}'s file (now {VERSION})")
    whole = whole_text().encode("utf-8")
    assert len(whole) == OLD_SIZE, len(whole)
    assert hashlib.sha256(whole).hexdigest() == OLD_SHA


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
    assert {"S", "widgets", "dialogs", "gui", "CULTURE_KEY", "camera_module", "deep_copy", "fmt_tokens"} <= family
    for n, t in texts.items():
        mine = _top_locals(t)
        code = [_strip(l) for l in t.split("\n")]
        for name in family - mine:
            pat = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
            hits = [i for i, l in enumerate(code, 1) if pat.search(l)]
            assert not hits, (n, name, hits[:5])
    handed = {"S", "widgets", "dialogs", "CULTURE_KEY"}
    for n, t in texts.items():
        for i, l in enumerate(t.split("\n"), 1):
            c = _strip(l)
            for name in handed:
                if not re.search(r"(?<![\w.:])" + re.escape(name) + r"\s*(?:,\s*[\w.]+\s*)*=(?!=)", c):
                    continue
                ok = (c.startswith(("local ", "OVERSEER_PART_LOCALS"))
                      or re.match(r"^\s+local " + re.escape(name) + r"\b", c)
                      or re.search(r"[{,]\s*" + re.escape(name) + r"\s*=", c))
                assert ok, (n, i, l)


RIG = r"""
local hub_src, whole_src, part_srcs = ...
local function auto() return setmetatable({}, {__index = function(t, k) local v = {}; rawset(t, k, v); return v end}) end
local S = setmetatable({TRAIT_MIN = -100, TRAIT_MAX = 100, TRAIT_STEP = 10}, {__index = function() return {} end})
local mods = {}
local function fresh(parts)
    local env = setmetatable({}, {__index = _G})
    env.qerror = error
    env.dfhack_flags = {module = true}
    env.PART_SOURCES = parts
    env.DEFAULT_NIL = nil
    env.defclass = function(c, parent) c = c or {}; c.ATTRS = function() end; return c end
    env.require = function(n) mods[n] = mods[n] or auto(); return mods[n] end
    env.reqscript = function(n) assert(n == 'ai-overseer-settings', n); return S end
    env.dfhack = auto()
    return env
end
local split = fresh(part_srcs)
assert(load(hub_src, 'gui/ai-overseer', 't', split))()
local whole = fresh(nil)
assert(load(whole_src, 'gui/ai-overseer-whole', 't', whole))()
local SCAFFOLD = {PARTS = true, PART_VERSIONS = true, OVERSEER_PART_LOCALS = true, PART_SOURCES = true}
local function keys(e)
    local o = {}
    for k, v in pairs(e) do
        if not SCAFFOLD[k] then o[#o + 1] = k .. ':' .. type(v) end
    end
    table.sort(o)
    return table.concat(o, ' ')
end
-- the culture part's key reaches the window's upvalue: the hub's selected_now reads it
local same = split.OVERSEER_PART_LOCALS.S == S and split.OVERSEER_PART_LOCALS.widgets == mods['gui.widgets']
    and split.OVERSEER_PART_LOCALS.dialogs == mods['gui.dialogs']
local alone = {}
for name, src in pairs(part_srcs) do
    local ok, err = pcall(assert(load(src, name, 't', fresh(nil))))
    alone[name] = (not ok) and tostring(err) or 'ran'
end
return keys(split), keys(whole), split, whole, alone, same
"""


def rig():
    need_lua()
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    out = L.execute(RIG, HUB, whole_text(), L.table_from({n: read(n) for n in PARTS}))
    return L, out


@test("load: the hub with its parts defines the same names as the text in one piece (but the split's own: "
      "PARTS, PART_VERSIONS, OVERSEER_PART_LOCALS); every part marked; the locals the same objects; "
      "CULTURE_KEY back in the hub; a part run alone refuses")
def _():
    L, (a, b, split, whole, alone, same) = rig()
    assert a == b, (set(a.split()) ^ set(b.split()))
    g = set(a.split())
    for cls in ["TraitPage", "AIPage", "RulesPage", "MilitaryPage", "NeedsPage", "CameraPage", "CulturePage",
                "OverseerWindow", "OverseerScreen"]:
        assert f"{cls}:table" in g, cls
    assert "merge_changes:function" in g
    assert [split.PARTS[i] for i in range(1, 3)] == ["rules", "culture"]
    assert dict(split.PART_VERSIONS.items()) == {n: VERSION for n in [HUB_NAME] + PARTS}
    assert split.OVERSEER_PART_LOCALS.CULTURE_KEY == "ai-overseer/culture"
    assert whole.PARTS is None and whole.OVERSEER_PART_LOCALS is None
    assert same
    for fn in ["init", "refresh"]:
        assert split.RulesPage[fn] is not None and split.MilitaryPage[fn] is not None, fn
        assert split.NeedsPage[fn] is not None and split.CameraPage[fn] is not None, fn
    assert split.CulturePage.confirm_wipe is not None and split.CulturePage.learned_lines is not None
    for n in PARTS:
        assert f"{n} is a part of gui/ai-overseer; run gui/ai-overseer" in alone[n], (n, alone[n])


@test("the window built (tests/gui_behaviour.py) has every page, the parts' among them; "
      "the window's culture line reads the save through CULTURE_KEY")
def _():
    import gui_behaviour as GB
    win = GB.window()
    for name in ("AIPage", "RulesPage", "MilitaryPage", "NeedsPage", "CulturePage", "CameraPage"):
        GB.page(win, name)                                  # raises KeyError when missing
    assert GB.find(GB.page(win, "RulesPage"), "fort_goal") is not None
    L, G, TP = GB._boot()
    sel = win.selected
    TP.H.persist["ai-overseer/culture"] = TP.t({"effects": {sel: "the test's effect"}})
    win.effects_read = None
    assert win.selected_now(win) == "Now: the test's effect", win.selected_now(win)


@test("the bridge finds the parts: a `PARTS = {` line in the hub (module_has_parts), the parts named "
      "<module>-<part> beside it (split_part_names, bridge_part_path); gui/ai-overseer is a bridge module; "
      "the delivery's touch of lua\\gui\\*.lua covers them; the family read whole by split_src")
def _():
    assert ("\n" + HUB).count("\nPARTS = {") == 1
    assert re.search(r"'gui/ai-overseer'", BRIDGE)
    assert "for _, p in ipairs(parts or {}) do table.insert(out, mod .. '-' .. p) end" in BRIDGE
    for n in PARTS:
        assert (LUA_DIR / f"{n}.lua").parent == LUA_DIR / "gui"
    whole = split_src("gui/ai-overseer.lua")
    for marker in ("function RulesPage:init()", "function MilitaryPage:refresh()", "function CulturePage:learned_lines()",
                   "function OverseerWindow:init()"):
        assert marker in whole, marker
    guide = (ROOT / "docs" / "setup-guide.md").read_text(encoding="utf-8")
    assert r"lua\gui\*.lua" in guide


finish()
