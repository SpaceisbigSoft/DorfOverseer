"""(D0, G3) The Design track's two settings: `design` (Scripts / Guided /
Architect) and `landmark_pace` (season / year / never) in
lua/ai-overseer-settings.lua (defaults, sanitize, for_ai, old saves, presets,
set_rules), the window's Design selector and Landmarks switch, the Culture
page's design lines and the bridge's set_culture keeping them; in a real Lua
engine (lupa, Lua 5.3).

    python tests/test_d0_settings.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish, code_has  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_preset as TP      # the bridge and the settings with a stub DFHack  # noqa: E402

GUI = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
SETTINGS = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")

test = make_test(before=TP.reset)


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)]


@test("design and landmark_pace: the choices, their names and words")
def _():
    S = TP.H.settings()
    assert lua_list(S.DESIGN_MODES) == ["scripts", "guided", "architect"]
    assert lua_list(S.LANDMARK_PACES) == ["season", "year", "never"]
    for m in lua_list(S.DESIGN_MODES):
        assert S.DESIGN_NAMES[m] and S.DESIGN_WORDS[m], m
        assert len(S.DESIGN_NAMES[m]) + 2 + len(S.DESIGN_WORDS[m]) <= 110, m     # one line at l = 2
    for m in lua_list(S.LANDMARK_PACES):
        assert S.LANDMARK_PACE_NAMES[m], m
    assert S.DESIGN_TOKENS == "Guided ~4k tokens an era; Architect ~5-15k a landmark; none without --ai"
    assert S.DESIGN_DEFAULT == "scripts" and S.DESIGN_NEW == "guided"


@test("defaults: a new fort starts at Guided (the decision), one landmark a season; for_ai carries both")
def _():
    S = TP.H.settings()
    d = S.defaults()
    assert d.design == "guided" and d.landmark_pace == "season"
    a = S.for_ai(d)
    assert a.design == "guided" and a.landmark_pace == "season"
    # a fort with nothing saved reads the defaults, and nothing is written
    s = S.load_settings()
    assert s.design == "guided" and s.landmark_pace == "season"
    assert TP.H.persist["ai-overseer/settings"] is None


@test("sanitize: each value kept; an unknown value becomes the default (scripts, season)")
def _():
    S = TP.H.settings()
    for m in ("scripts", "guided", "architect"):
        assert S.sanitize(TP.t({"design": m})).design == m
        assert S.for_ai(S.sanitize(TP.t({"design": m}))).design == m
    for p in ("season", "year", "never"):
        assert S.sanitize(TP.t({"landmark_pace": p})).landmark_pace == p
        assert S.for_ai(TP.t({"landmark_pace": p})).landmark_pace == p
    for bad in ("Guided", "auto", 1, True, ""):
        s = S.sanitize(TP.t({"design": bad, "landmark_pace": bad}))
        assert s.design == "scripts" and s.landmark_pace == "season", bad
    assert S.sanitize(None).design == "scripts"


@test("an old save without them reads Scripts and one a season, and keeps its other settings")
def _():
    S = TP.H.settings()
    old = {"version": 2, "traits": {"piety": {"value": 50, "extreme": False}}, "mode": "copilot",
           "memorial_pace": "year", "construct": False}
    TP.H.persist["ai-overseer/settings"] = TP.t(old)
    s = S.load_settings()
    assert s.design == "scripts" and s.landmark_pace == "season"
    assert s.mode == "copilot" and s.memorial_pace == "year" and s.construct is False
    assert s.traits.piety.value == 50
    a = S.for_ai(s)
    assert a.design == "scripts" and a.landmark_pace == "season"
    # saved and loaded again: the same
    S.save_settings(s)
    assert S.load_settings().design == "scripts"


@test("round trip: a chosen setting is saved with the fort and read back")
def _():
    S = TP.H.settings()
    s = S.defaults()
    s.design, s.landmark_pace = "architect", "year"
    S.save_settings(s)
    saved = TP.H.persist["ai-overseer/settings"]
    assert saved.design == "architect" and saved.landmark_pace == "year"
    back = S.load_settings()
    assert back.design == "architect" and back.landmark_pace == "year"
    assert S.for_ai(back).design == "architect"


@test("presets don't set them: applying one keeps the fort's design and pace")
def _():
    S = TP.H.settings()
    for name in TP.PRESETS:
        s = S.defaults()
        s.design, s.landmark_pace = "architect", "never"
        m = S.load_preset(name, s)
        assert m.design == "architect" and m.landmark_pace == "never", name
    keys = lua_list(S.PRESET_RULE_KEYS)
    assert "design" not in keys and "landmark_pace" not in keys
    # the keeper's apply_preset on a new fort: the new fort's Guided is saved
    r = TP.act({"type": "apply_preset", "name": "Deep mine"})
    assert r.ok and TP.saved().design == "guided" and r.settings.design == "guided", dict(r)
    # ... and on an old fort (settings saved without design): Scripts stays
    TP.reset()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "mode": "autopilot"})
    r = TP.act({"type": "apply_preset", "name": "Monastery"})
    assert r.ok and TP.saved().design == "scripts", dict(r)


@test("set_rules takes the two choices from outside the window, refusing a bad one")
def _():
    r = TP.act({"type": "set_rules", "rules": {"design": "architect", "landmark_pace": "year"}})
    assert r.ok, dict(r)
    assert TP.saved().design == "architect" and TP.saved().landmark_pace == "year"
    r = TP.act({"type": "set_rules", "rules": {"design": "fantastic"}})
    assert not r.ok and "design" in r.error, dict(r)
    assert TP.saved().design == "architect"


@test("the settings section hands both to the brain (state['settings'])")
def _():
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "design": "guided", "landmark_pace": "never"})
    S = TP.H.settings()
    a = S.for_ai(S.load_settings())
    assert a.design == "guided" and a.landmark_pace == "never"


# --- the window ------------------------------------------------------------------------

def page(name: str) -> str:
    a = GUI.index(f"function {name}:init()")
    return GUI[a:GUI.index("\nend\n", a)]


@test("window: the AI & tokens tab's Design selector under the sliders, with its words and token note")
def _():
    src = page("AIPage")
    assert code_has(src, "view_id = 'design'") and code_has(src, "p:set_field('design', v)")
    assert "widgets.CycleHotkeyLabel{\n        view_id = 'design'" in src
    assert code_has(src, "S.DESIGN_MODES") and code_has(src, "S.DESIGN_WORDS") and code_has(src, "S.DESIGN_TOKENS")
    assert code_has(GUI, "self.subviews.design:setOption(s.design or S.DESIGN_DEFAULT, false)")
    m = re.search(r"view_id = 'design',.*?label = '([^']*)',\s*label_width = (\d+)", src, re.S)
    assert m and len(m.group(1)) <= int(m.group(2)), m and m.groups()
    # the sliders take rows 2-5; every row-0-column control in its own row, all within the 28 shown
    rows = [int(x) for x in re.findall(r"frame = \{t = (\d+), l = [02][,}]", src)]
    design_row = int(re.search(r"view_id = 'design',\s*frame = \{t = (\d+)", src).group(1))
    assert design_row == 7, design_row
    assert len(rows) == len(set(rows)), sorted(rows)
    assert max(rows) <= 27 and min(r for r in rows if r) > 5, sorted(rows)


@test("window: Landmarks on the Rules tab beside the memorials, in a free part of that row")
def _():
    src = page("RulesPage")
    assert code_has(src, "view_id = 'landmark_pace'") and code_has(src, "p:set_field('landmark_pace', v)")
    assert code_has(GUI, "self.subviews.landmark_pace:setOption(s.landmark_pace or 'season', false)")
    mem = re.search(r"view_id = 'memorial_pace',\s*frame = \{t = (\d+), l = (\d+), w = (\d+)\}", src)
    lm = re.search(r"view_id = 'landmark_pace',\s*frame = \{t = (\d+), l = (\d+), w = (\d+)\}", src)
    assert mem and lm
    assert mem.group(1) == lm.group(1)                                   # the same row
    assert int(mem.group(2)) + int(mem.group(3)) < int(lm.group(2))      # to its right
    assert int(lm.group(2)) + int(lm.group(3)) <= 118
    m = re.search(r"view_id = 'landmark_pace',.*?label = '([^']*)',\s*label_width = (\d+)", src, re.S)
    longest = max(len(x) for x in ("one a season", "one a year", "never"))
    assert len(m.group(1)) <= int(m.group(2)) and int(m.group(2)) + longest + 4 <= int(lm.group(3))


@test("window: the Culture page shows the design lines when the culture has them, and the new halls' words")
def _():
    src = page("CulturePage")      # init; the lines are in refresh
    assert src
    r = GUI[GUI.index("function CulturePage:refresh()"):]
    assert code_has(r, "type(c.design) == 'table'") and "THE DESIGN LANGUAGE" in r
    for h in ("octagonal", "round", "cruciform", "nave"):
        assert re.search(rf"\b{h} = '", GUI[:GUI.index("CameraPage = defclass")]), h


@test("bridge: set_culture keeps the design lines (6 at most, cleaned) and takes the new halls")
def _():
    lines = [f"Line {i}: halls cruciform, motif <flame>" for i in range(9)]
    r = TP.act({"type": "set_culture", "culture": {"profile": {"hall": "cruciform", "smooth": 1, "statues": 1},
                                                   "design": lines}})
    assert r.ok, dict(r)
    c = TP.H.persist["ai-overseer/culture"]
    got = lua_list(c.design)
    assert len(got) == 6 and got[0] == "Line 0: halls cruciform, motif flame", got
    assert c.profile.hall == "cruciform"
    for h in ("octagonal", "round", "nave", "plain"):
        assert TP.act({"type": "set_culture", "culture": {"profile": {"hall": h}}}).ok, h
    assert not TP.act({"type": "set_culture", "culture": {"profile": {"hall": "spiral"}}}).ok
    # no design: none kept (the page shows nothing new)
    assert TP.act({"type": "set_culture", "culture": {"profile": {}}}).ok
    assert TP.H.persist["ai-overseer/culture"].design is None


@test("the settings, the window and the bridge actions compile under Lua 5.3")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-overseer-settings.lua", "gui/ai-overseer.lua", "ai-bridge-actions.lua"):
        ok = chk((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


@test("docs/controls.md names the two settings")
def _():
    doc = (ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
    for k in ("`design`", "`landmark_pace`", "Guided", "Architect", "Landmarks (Architect)"):
        assert k in doc, k


if __name__ == "__main__":
    finish()
