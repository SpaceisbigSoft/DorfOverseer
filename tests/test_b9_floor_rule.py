"""(layout B, B9) The Rules switch `floor_layout`: how new levels are placed,
'hallway' (the default, also for a save without the key: every running fort)
or 'classic'. lua/ai-overseer-settings.lua (the choices, defaults, sanitize,
for_ai, set_rules; not a preset rule), the Rules tab's "New levels:" cycle in
lua/gui/ai-overseer.lua, and planner_core.player_rules; in a real Lua engine
(lupa, Lua 5.3).

    python tests/test_b9_floor_rule.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish, code_has  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_preset as TP      # the bridge and the settings with a stub DFHack  # noqa: E402
from planner_core import player_rules  # noqa: E402

GUI = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
SETTINGS = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
KEY = "ai-overseer/settings"

test = make_test(before=TP.reset)


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)]


@test("the choices and their names: hallway, classic")
def _():
    S = TP.H.settings()
    assert lua_list(S.FLOOR_LAYOUT_CHOICES) == ["hallway", "classic"]
    assert S.FLOOR_LAYOUT_NAMES.hallway == "along a main hall on each floor"
    assert S.FLOOR_LAYOUT_NAMES.classic == "each on its own (classic)"
    assert len(list(S.FLOOR_LAYOUT_NAMES.keys())) == 2


@test("defaults: hallway; a fort with nothing saved reads hallway and nothing is written")
def _():
    S = TP.H.settings()
    assert S.defaults().floor_layout == "hallway"
    assert S.load_settings().floor_layout == "hallway"
    assert TP.H.persist[KEY] is None


@test("sanitize: no key -> hallway (the running forts); classic and hallway kept; junk -> hallway")
def _():
    S = TP.H.settings()
    assert S.sanitize(TP.t({})).floor_layout == "hallway"
    assert S.sanitize(None).floor_layout == "hallway"
    assert S.sanitize(TP.t({"floor_layout": "classic"})).floor_layout == "classic"
    assert S.sanitize(TP.t({"floor_layout": "hallway"})).floor_layout == "hallway"
    for bad in ("x", True, False, 3, "Classic", "", ["classic"], {"classic": True}):
        assert S.sanitize(TP.t({"floor_layout": bad})).floor_layout == "hallway", bad


@test("a running fort's save without the key reads hallway and keeps its other settings; a choice is saved and read back")
def _():
    S = TP.H.settings()
    TP.H.persist[KEY] = TP.t({"version": 2, "mode": "copilot", "memorial_pace": "year", "construct": False,
                              "world_cleanup": "full"})
    s = S.load_settings()
    assert s.floor_layout == "hallway"
    assert s.mode == "copilot" and s.memorial_pace == "year" and s.construct is False and s.world_cleanup == "full"
    s.floor_layout = "classic"
    S.save_settings(s)
    assert TP.saved().floor_layout == "classic"
    assert S.load_settings().floor_layout == "classic"
    assert S.for_ai(S.load_settings()).floor_layout == "classic"


@test("for_ai carries it; RULE_CHOICES.floor_layout is the choices list")
def _():
    S = TP.H.settings()
    assert S.for_ai(S.defaults()).floor_layout == "hallway"
    for v in ("hallway", "classic"):
        assert S.for_ai(S.sanitize(TP.t({"floor_layout": v}))).floor_layout == v
    assert TP.LUA.eval('rawequal')(S.RULE_CHOICES.floor_layout, S.FLOOR_LAYOUT_CHOICES)
    assert lua_list(S.RULE_CHOICES.floor_layout) == ["hallway", "classic"]


@test("not a preset rule: in neither PRESET_RULE_KEYS nor a built-in preset; every preset leaves classic as it was")
def _():
    S = TP.H.settings()
    assert "floor_layout" not in lua_list(S.PRESET_RULE_KEYS)
    names = list(S.BUILTIN_PRESET_RULES.keys())
    assert sorted(names) == sorted(TP.PRESETS), names
    for name in names:
        assert S.BUILTIN_PRESET_RULES[name].floor_layout is None, name
    for name in TP.PRESETS:
        for v in ("classic", "hallway"):
            s = S.defaults()
            s.floor_layout = v
            assert S.load_preset(name, s).floor_layout == v, (name, v)
        # the keeper's --preset (the bridge's apply_preset) on a classic fort: still classic
        TP.reset()
        TP.H.persist[KEY] = TP.t({"version": 2, "mode": "autopilot", "floor_layout": "classic"})
        r = TP.act({"type": "apply_preset", "name": name})
        assert r.ok and TP.saved().floor_layout == "classic", (name, dict(r))
        assert r.rules.floor_layout is None, name
    # a preset the player saved carries no floor_layout either
    s = S.defaults()
    s.floor_layout = "classic"
    assert S.save_preset("Mine", s)
    back = S.defaults()
    assert S.load_preset("Mine", back).floor_layout == "hallway"


@test("set_rules sets it to classic and back, and refuses a value outside the choices")
def _():
    r = TP.act({"type": "set_rules", "rules": {"floor_layout": "classic"}})
    assert r.ok, dict(r)
    assert TP.saved().floor_layout == "classic"
    r = TP.act({"type": "set_rules", "rules": {"floor_layout": "hallway"}})
    assert r.ok, dict(r)
    assert TP.saved().floor_layout == "hallway"
    TP.act({"type": "set_rules", "rules": {"floor_layout": "classic"}})
    for bad in ("ring", "Classic", True, 3, ""):
        r = TP.act({"type": "set_rules", "rules": {"floor_layout": bad}})
        assert not r.ok and "floor_layout" in r.error, (bad, dict(r))
        assert TP.saved().floor_layout == "classic", bad
    # another switch set from outside: the choice stays
    r = TP.act({"type": "set_rules", "rules": {"construct": False}})
    assert r.ok and TP.saved().floor_layout == "classic" and TP.saved().construct is False


@test("the brain: player_rules reads hallway unless the settings say classic")
def _():
    assert player_rules({"settings": {}})["floor_layout"] == "hallway"
    assert player_rules({})["floor_layout"] == "hallway"
    assert player_rules({"settings": None})["floor_layout"] == "hallway"
    assert player_rules({"settings": {"floor_layout": "classic"}})["floor_layout"] == "classic"
    assert player_rules({"settings": {"floor_layout": "hallway"}})["floor_layout"] == "hallway"
    for bad in ("x", True, 3, None, "Classic", ["classic"]):
        assert player_rules({"settings": {"floor_layout": bad}})["floor_layout"] == "hallway", bad
    # what the settings section hands the brain is what player_rules reads
    S = TP.H.settings()
    for v in ("hallway", "classic"):
        a = S.for_ai(S.sanitize(TP.t({"floor_layout": v})))
        assert player_rules({"settings": {"floor_layout": a.floor_layout}})["floor_layout"] == v


def _rules_src() -> str:
    return GUI[GUI.index("function RulesPage:init()"):GUI.index("MilitaryPage = defclass")]


def _rules_boxes():
    """(row, l, w or None, what) of every framed control on the Rules page, at the window's numbers
    (9 optional levels: t = 14; the hospital 2nd, the jail 8th; the loops' i = 1..n)."""
    src = _rules_src()
    out = []
    for m in re.finditer(r"frame = \{t = ([^,]+), l = (\d+)(?:, w = (\d+))?\}", src):
        expr, l, wd = m.group(1).strip(), int(m.group(2)), m.group(3) and int(m.group(3))
        before = src[:m.start()]
        v = re.findall(r"view_id = ([^,\n]+),\s*$", before)
        what = v[0] if v else "label@%d" % (before.count("\n") + 1)
        n = 9 if "level_" in what else 3
        for i in (range(1, n + 1) if " + i" in expr else (0,)):
            out.append((eval(expr, {"jrow": 8, "hrow": 2, "t": 14, "i": i}), l, wd, what))
    return out


@test("window: the 'New levels:' cycle on the Rules tab (row 4, the right-hand column), overlapping nothing; its "
      "widest choice fits; refreshed")
def _():
    src = _rules_src()
    assert "widgets.CycleHotkeyLabel{\n        view_id = 'floor_layout'," in src
    assert code_has(src, "label = 'New levels:',")
    assert code_has(src, "for _, m in ipairs(S.FLOOR_LAYOUT_CHOICES) do "
                         "table.insert(out, {label = S.FLOOR_LAYOUT_NAMES[m], value = m}) end")
    assert code_has(src, "initial_option = S.FLOOR_LAYOUT_NAMES[p.settings.floor_layout] and "
                         "p.settings.floor_layout or 'hallway',")
    assert code_has(src, "on_change = function(v) p:set_field('floor_layout', v) end,")
    assert GUI.count("view_id = 'floor_layout'") == 1
    assert code_has(GUI, "self.subviews.floor_layout:setOption(S.FLOOR_LAYOUT_NAMES[s.floor_layout] and "
                         "s.floor_layout or 'hallway', false)")
    refresh = GUI[GUI.index("function RulesPage:refresh()"):]
    refresh = refresh[:refresh.index("\nend\n")]
    assert "self.subviews.floor_layout:setOption(" in refresh
    boxes = _rules_boxes()
    assert len(boxes) >= 45, len(boxes)                    # the parser sees the page
    mine = [b for b in boxes if b[3] == "'floor_layout'"]
    assert len(mine) == 1, boxes
    r, l, wd, _ = mine[0]
    assert (r, l, wd) == (4, 56, 62), mine
    assert l + wd <= 118 and 0 < r <= 27
    heading = re.search(r"frame = \{t = 4, l = 0\}, text = \{\{text = '([^']*)'", src).group(1)
    for r2, l2, w2, v in boxes:
        if v == "'floor_layout'" or r2 != r:
            continue
        w2 = w2 if w2 is not None else len(heading)        # the one unsized label in the row: the levels' heading
        assert "label@" not in v or (l2 == 0 and heading), (v, r2, l2)
        assert l2 + w2 <= l or l + wd <= l2, (v, r2, l2, w2, mine)
    # the hospital burrow's switch sits at row 4 + (the hospital's place among the levels): never row 4
    assert code_has(src, "frame = {t = 4 + hrow, l = 56, w = 62}")
    m = re.search(r"view_id = 'floor_layout',.*?label = '([^']*)',\s*label_width = (\d+)", src, re.S)
    S = TP.H.settings()
    widest = max(len(S.FLOOR_LAYOUT_NAMES[k]) for k in lua_list(S.FLOOR_LAYOUT_CHOICES))
    assert len(m.group(1)) < int(m.group(2)) and int(m.group(2)) + widest <= wd, (m.groups(), widest, wd)


@test("Lua: the window and the settings still compile (Lua 5.3)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    f = lua.eval("function(s) local fn, e = load(s, 'c', 't', {}); return e end")
    assert f(GUI) is None, f(GUI)
    assert f(SETTINGS) is None, f(SETTINGS)


@test("the source lines the other groups read (the contract's names)")
def _():
    assert "FLOOR_LAYOUT_CHOICES = {'hallway', 'classic'}" in SETTINGS
    assert code_has(SETTINGS, "floor_layout = FLOOR_LAYOUT_CHOICES,")
    assert code_has(SETTINGS, "floor_layout = 'hallway',")
    assert code_has(SETTINGS, "out.floor_layout = one_of(s.floor_layout, FLOOR_LAYOUT_CHOICES, d.floor_layout)")
    assert code_has(SETTINGS, "floor_layout = s.floor_layout,")
    core = (ROOT / "brain" / "planner_core.py").read_text(encoding="utf-8")
    assert code_has(core, '"floor_layout": "classic" if st.get("floor_layout") == "classic" else "hallway", '
                          '# (0.105.47) a training-only squad')
    assert list(player_rules({"settings": {}}))[-1] == "training_squad"


if __name__ == "__main__":
    finish()
