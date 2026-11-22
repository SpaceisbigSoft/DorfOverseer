"""(r5, group p5) Behaviour tests in place of source-text asserts.

Tests that read a lua/ or brain/ file and looked for a line of its text
(code_has, `"..." in SRC`, a regex over the source, a handler cut out of
the hub's text and run alone) broke on every refactor that kept the
behaviour: one blocked a fix (test_b7 required the literal
"and floor_mode() == 'hallway'"). The tests listed in CONVERTED now run the
code instead: the window built on a stub gui (tests/gui_behaviour.py), the
bridge hub loaded with stand-in modules (tests/bridge_behaviour.py), the
builder on test_builder's fake fort. What is a true contract (a docs line,
DFHack's module marker, a wiring list's member) stays, marked `# contract`.

    python tests/test_r5_p5.py
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))
from harness import code_has, finish, have_lua, skip, test  # noqa: E402

# (file, the test's title as it starts): each runs the code, no source text unmarked
CONVERTED = [
    ('test_artifacts.py', '(fix5) the display list is buildings.other.DISPLAY_CASE '),
    ('test_artifacts.py', 'bridge: place_display and display_artifact in ACTIONS an'),
    ('test_b7_floor_wiring.py', '10. the guards: a floor part that is no function (a numb'),
    ('test_b7_floor_wiring.py', '10. every floor part raising at once: the level is place'),
    ('test_b7_floor_wiring.py', '10. floor_release and floor_book_piles run after the sav'),
    ('test_b9_floor_rule.py', "window: the 'New levels:' cycle on the Rules tab (row 4,"),
    ('test_b9_floor_rule.py', "the names the other groups read (the contract's names): "),
    ('test_captives.py', 'bridge: the captives and necro sections (safe), make_pit'),
    ('test_construct_seams.py', "construct switch: the Rules tab's toggle, set and refres"),
    ('test_d0_settings.py', "window: the AI & tokens tab's Design selector under the "),
    ('test_d0_settings.py', 'window: Landmarks on the Rules tab beside the memorials,'),
    ('test_d0_settings.py', 'window: the Culture page shows the design lines when the'),
    ('test_disposal_actions.py', 'bridge: the six actions in ACTIONS, DRY_OK and CACHE_INV'),
    ('test_disposal_settings.py', 'disposal keys: the Rules tab has the cycle and both swit'),
    ('test_hunt_planner.py', 'settings and window: hunt off | small | ai, default ai; '),
    ('test_item10.py', 'bridge: three sections (safe), three actions on ACTIONS '),
    ('test_item3_killers.py', 'bridge: the killers section (safe), killer_cell (ids che'),
    ('test_k48_gate_halt.py', 'the way-out guard: the first try leaves the bridge to a '),
    ('test_k48_report_cache.py', 'A3 5: redig_projects is a bridge action (dry runs allowe'),
    ('test_killzones.py', 'bridge: the killzones section (safe, cached a day), both'),
    ('test_killzones.py', "Rules: killzones on by default (settings, the Army tab's"),
    ('test_learning.py', "the hospital burrow's Rules switch (0.104.168): on by de"),
    ('test_lure.py', 'bridge: the three actions, DRY_OK, the lures section (pu'),
    ('test_lure.py', 'brain: digest default, labels, config, Rules switch (set'),
    ('test_missions_settings.py', "window: the Army tab's Missions cycle and World screen s"),
    ('test_missions_settings.py', "window (J17): the Raids cycle on the Army tab's free row"),
    ('test_missions_settings.py', "window: the Army tab's left-column rows don't collide an"),
    ('test_peace_bans.py', 'settings: the peace choice (ai, accept, refuse; default '),
    ('test_planner.py', '0.105.24 presets: the Merchant city turns shut_to_visito'),
    ('test_provisions.py', 'bridge: the four actions in ACTIONS and DRY_OK, the prov'),
    ('test_provisions.py', 'settings: the hunting and cavern_farms switches (on by d'),
    ('test_r1_g6.py', "3 lua: start_project: a mood's workshops level takes no "),
    ('test_r2_h3.py', '1 lua: finish_project give_up with drop takes the named '),
    ('test_r2_h3.py', '2 lua: a small need (paper, well, drink) starts past the'),
    ('test_r2_h4.py', "2 lua: start_project: the lone `crossbows` Bowyer's take"),
    ('test_r2_h7.py', '3 lua: finish_project leave_planned: the level is done, '),
    ('test_r33_lua_misc.py', 'L8 gui: the tab bar reloads the settings before a page i'),
    ('test_r33_lua_misc.py', 'L8 gui: the Rules page ends at row 27 and the Army tab h'),
    ('test_r35_core.py', 'founding (Lua): an aquifer all round the dwarves: refuse'),
    ('test_r35_core.py', 'marker-only dig tiles: wired as a bridge action whose dr'),
    ('test_r35_merge.py', 'open_caverns: (v35) the switch reads AI decides / Always'),
    ('test_r35_water.py', 'bridge: cistern_step passes retire (with why) and relink'),
    ('test_r36_gates.py', 'D2: free_gate_jobs: a piece with no record at an entranc'),
    ('test_r40_cleanup.py', 'bridge: the four actions in ACTIONS and DRY_OK, the clea'),
    ('test_r40_cleanup.py', 'window: the World cleanup row on the Rules tab, in a fre'),
    ('test_r41_hauling.py', 'bridge: the hauling section (safe), the two actions on A'),
    ('test_r41_hauling.py', 'fix 11 (lua): the dwarves the AI added remembered; shrin'),
    ('test_r41_insane.py', 'bridge: the insane section (safe, in the pulse), the ins'),
    ('test_r46_recovery.py', 'bridge: the migration section (safe), call_migrants (dry'),
    ('test_r47_surface_dangers.py', 'wiring: actions, DRY_OK, the section in SECTIONS and the'),
    ('test_r47_tantrums.py', 'bridge: the tantrums section (safe, in the pulse), the t'),
    ('test_r47_way_out.py', 'wiring: the way_out section (in the pulse too) and its d'),
    ('test_stuck.py', 'bridge: the stuck section (safe), stuck_reset (kind and '),
    ('test_syndromes.py', 'bridge: the syndromes and miasma sections (safe), the th'),
    ('test_syndromes.py', 'settings: the syndrome_care switch (on by default), save'),
    ('test_threats.py', 'bridge: the new actions are in the table and refuse bad '),
    ('test_traffic.py', 'bridge: paint_traffic in ACTIONS and DRY_OK, the traffic'),
    ('test_traffic.py', 'settings: traffic on by default, kept off when set off, '),
    ('test_water.py', 'the Rules (0.105.4 review): "Cavern well into an unfound'),
    ('test_world.py', 'the Rules: tribute (small, pay, refuse) and Make contact'),
]

# --- the detector: a source-text assert in a test function --------------------------------

_TEXT = re.compile(r"read_text|split_src|module_src|lua_text|\.read\(\)")


def _text_names(tree, src):
    """Module-level names bound to a file's text (X = (LUA_DIR / ...).read_text(...))."""
    out = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and _TEXT.search(ast.get_source_segment(src, node.value) or ""):
            for t in node.targets:
                out |= {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
    return out


def source_asserts(fn, src, names) -> list[int]:
    """The lines of fn that test source text: code_has(...), `"..." in <text>`, a regex,
    count or index over <text>; a line marked `# contract` is a contract and kept."""
    local = set(names)
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            v = n.value
            if _TEXT.search(ast.get_source_segment(src, v) or "") or (
                    isinstance(v, ast.Subscript) and any(isinstance(x, ast.Name) and x.id in local
                                                         for x in ast.walk(v.value))):
                for t in n.targets:
                    local |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
    lines = src.splitlines()

    def on_text(node):
        return any(isinstance(x, ast.Name) and x.id in local for x in ast.walk(node))
    out = set()
    for n in ast.walk(fn):
        bad = False
        if isinstance(n, ast.Call):
            name = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if name == "code_has":
                bad = True
            elif name in ("search", "findall", "finditer", "match", "count", "index"):
                bad = any(on_text(a) for a in n.args) or (isinstance(n.func, ast.Attribute) and on_text(n.func.value)
                                                         and not isinstance(n.func.value, ast.Call))
        elif isinstance(n, ast.Compare) and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops):
            bad = any(on_text(c) for c in n.comparators)
        if bad and "# contract" not in lines[n.lineno - 1]:
            out.add(n.lineno)
    return sorted(out)


def _find(file, title):
    src = (TESTS / file).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for d in fn.decorator_list:
                if (isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)
                        and str(d.args[0].value).startswith(title)):
                    return fn, src, tree
    return None, src, tree


@test("the detector sees each kind of source-text assert, and lets a `# contract` line and a run pass")
def _():
    sample = (
        "SRC = (ROOT / 'lua' / 'x.lua').read_text(encoding='utf-8')\n"
        "@test('a')\n"
        "def a():\n"
        "    assert code_has(SRC, 'local x = 1')\n"
        "    assert 'foo(' in SRC\n"
        "    body = SRC[SRC.index('function f('):]\n"
        "    assert 'bar' not in body\n"
        "    assert re.search(r'baz', SRC)\n"
        "    assert SRC.count('qux') == 2\n"
        "    assert '--@ module = true' in SRC   # contract\n"
        "    assert run(SRC) == 3\n")
    tree = ast.parse(sample)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef)][0]
    assert source_asserts(fn, sample, _text_names(tree, sample)) == [4, 5, 6, 7, 8, 9], \
        source_asserts(fn, sample, _text_names(tree, sample))


@test("the converted tests run the code: none tests a line of lua/ or brain/ text (but a `# contract` one)")
def _():
    missing, dirty = [], []
    for file, title in CONVERTED:
        fn, src, tree = _find(file, title)
        if fn is None:
            missing.append((file, title))
            continue
        got = source_asserts(fn, src, _text_names(tree, src))
        if got:
            dirty.append((file, title[:40], got))
    assert not missing, ("not found", missing)
    assert not dirty, dirty
    assert len(CONVERTED) >= 30, len(CONVERTED)


# --- the refactor the text assert blocked: the floors' switch written another way ----------

REFACTOR_FROM = """    local floors_on = type(floor_site) == 'function' and type(floor_mode) == 'function'
        and FLOOR_KINDS and FLOOR_KINDS[kind] and params.floor ~= false and params.join ~= false
        and floor_mode() == 'hallway'"""
REFACTOR_TO = """    local function floors_wanted()
        if type(floor_site) ~= 'function' or type(floor_mode) ~= 'function' then return false end
        if not (FLOOR_KINDS and FLOOR_KINDS[kind]) then return false end
        if params.floor == false or params.join == false then return false end
        local mode = floor_mode()
        return mode == 'hallway'
    end
    local floors_on = floors_wanted()"""


@test("the floors' switch refactored (a local function, the mode in a local): the old text assert fails on it, "
      "the behaviour the new tests check holds")
def _():
    if not have_lua():
        skip("needs the lupa package (pip install lupa)")
    from lupa.lua53 import LuaRuntime
    import test_builder as TB
    import test_b7_floor_wiring as B7
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert REFACTOR_FROM in src, "the switch moved: update REFACTOR_FROM"
    new = src.replace(REFACTOR_FROM, REFACTOR_TO)
    assert code_has(src, "and floor_mode() == 'hallway'") and not code_has(new, "and floor_mode() == 'hallway'")
    tmp = Path(tempfile.mkdtemp(prefix="r5p5-lua-"))
    try:
        shutil.copytree(ROOT / "lua", tmp / "lua")
        (tmp / "lua" / "ai-builder-projects.lua").write_text(new, encoding="utf-8")
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.globals().LUA_DIR = str(tmp / "lua")
        B, W = lua.execute(TB.HARNESS, (tmp / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                           (tmp / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
        F = lua.execute(B7.STANDINS, B, W)
        bed = lua.table_from({"kind": "bedrooms", "rooms": 4, "room_size": 3})
        when = lua.table_from({"year": 255, "tick": 100})

        def fresh(mode="hallway", answer="site"):
            W.reset()
            for k in list(W.persist.keys()):
                W.persist[k] = None
            for name in B7.FLOOR_NAMES:
                B[name] = None
            F.reset()
            F.install()
            F.mode, F.answer = mode, answer
        fresh()
        r = B.start_project(bed, when, False)
        assert r.ok and r.floor is not None and r.floor.id == 3 and F.calls.site == 1 and F.calls.mode == 1, dict(r)
        assert F.calls.commit == 1
        fresh(mode="classic")
        r = B.start_project(bed, when, False)
        assert r.ok and r.floor is None and F.calls.site == 0, dict(r)
        fresh()
        B.floor_site = 42                                  # not a function: never called
        r = B.start_project(bed, when, False)
        assert r.ok and r.floor is None and F.calls.mode == 0, dict(r)
        fresh(answer="refuse")
        r = B.start_project(bed, when, False)
        assert r.ok and r.not_on_floor == "no room" and F.calls.fallback == 1, dict(r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- what the two helpers give, checked on the whole hub and the whole window ---------------

@test("bridge: every report section survives a fort where every module it asks for is missing (safe: one throw "
      "never loses the report)")
def _():
    if not have_lua():
        skip("needs the lupa package (pip install lupa)")
    import bridge_behaviour as BB
    env = BB.hub()
    run = BB.lua().eval("function(f) local ok, r = pcall(f, {}); return {ok, tostring(r)} end")
    names = list(env.SECTIONS.keys())
    assert len(names) > 80, len(names)
    bad = []
    for n in names:
        r = run(env.SECTIONS[n])
        if not r[1]:
            bad.append((n, r[2][:120]))
    assert not bad, bad


@test("window: every page builds; on the Rules, Army and AI pages no two controls overlap and every row is shown")
def _():
    if not have_lua():
        skip("needs the lupa package (pip install lupa)")
    import gui_behaviour as GB
    win = GB.window()
    assert len(GB.pages(win)) == 10
    for name in ("RulesPage", "MilitaryPage", "AIPage"):
        pg = GB.page(win, name)
        assert GB.overlaps(pg) == [], (name, GB.overlaps(pg))
        rows = [w.row for w in GB.widgets(pg) if w.row is not None]
        assert rows and max(rows) <= GB.visible_rows(win) - 1, (name, max(rows))
        for w in GB.widgets(pg):
            # (the AI page's effective-value column, l = 112 w = 12, is framed past the 120 inside: its
            # text is short; left as it is, not this group's)
            if w.l is not None and w.w is not None and name != "AIPage":
                assert w.l + w.w <= GB.inner_width(win), (name, w.view_id, w.l, w.w)
        GB.refresh(pg)                                     # every setOption names a view that is there


if __name__ == "__main__":
    finish()
