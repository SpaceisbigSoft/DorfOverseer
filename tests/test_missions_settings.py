"""(0.105.39, G4) The Rules switches for Phase 13b's missions: `missions`
(off / rescue / explore / all, default rescue) and `send_missions` (default
off) in lua/ai-overseer-settings.lua (defaults, sanitize, for_ai, old saves,
set_rules), the Army tab's rows in the window, and the docs; in a real Lua
engine (lupa, Lua 5.3).

    python tests/test_missions_settings.py
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

test = make_test(before=TP.reset)


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)]


@test("missions: the four choices, their names, the goals each allows, in RULE_CHOICES")
def _():
    S = TP.H.settings()
    assert lua_list(S.MISSION_CHOICES) == ["off", "rescue", "explore", "all"]
    assert lua_list(S.RULE_CHOICES.missions) == ["off", "rescue", "explore", "all"]
    for m in lua_list(S.MISSION_CHOICES):
        assert S.MISSION_NAMES[m], m
    assert lua_list(S.MISSION_GOALS.off) == []
    assert lua_list(S.MISSION_GOALS.rescue) == ["rescue", "recover_artifact"]
    assert lua_list(S.MISSION_GOALS.explore) == ["rescue", "recover_artifact", "explore"]
    allg = lua_list(S.MISSION_GOALS.all)
    assert set(allg) == {"rescue", "recover_artifact", "explore", "raid", "pillage", "tribute", "conquer"}
    # the offensive goals only at 'all'
    for m in ("off", "rescue", "explore"):
        assert not {"raid", "pillage", "tribute", "conquer"} & set(lua_list(S.MISSION_GOALS[m])), m
    assert len(S.MISSION_HELP) <= 110


@test("defaults: rescue, and send_missions off; for_ai hands both to the brain")
def _():
    S = TP.H.settings()
    d = S.defaults()
    assert d.missions == "rescue" and d.send_missions is False
    a = S.for_ai(d)
    assert a.missions == "rescue" and a.send_missions is False
    s = S.load_settings()                 # nothing saved: the defaults
    assert s.missions == "rescue" and s.send_missions is False


@test("sanitize: each choice kept; an unknown value reads rescue; send_missions only true when true")
def _():
    S = TP.H.settings()
    for m in ("off", "rescue", "explore", "all"):
        assert S.sanitize(TP.t({"missions": m})).missions == m
        assert S.for_ai(TP.t({"missions": m})).missions == m
    for bad in ("All", "raid", 1, True, False, ""):
        assert S.sanitize(TP.t({"missions": bad})).missions == "rescue", bad
    assert S.sanitize(TP.t({"send_missions": True})).send_missions is True
    assert S.sanitize(TP.t({"send_missions": "yes"})).send_missions is False
    assert S.for_ai(TP.t({"send_missions": True})).send_missions is True


@test("an old save without them reads the defaults and keeps its other settings")
def _():
    S = TP.H.settings()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "mode": "copilot", "send_messenger": True,
                                                 "construct": False})
    s = S.load_settings()
    assert s.missions == "rescue" and s.send_missions is False
    assert s.mode == "copilot" and s.send_messenger is True and s.construct is False


@test("round trip: chosen values saved with the fort and read back")
def _():
    S = TP.H.settings()
    s = S.defaults()
    s.missions, s.send_missions = "all", True
    S.save_settings(s)
    saved = TP.H.persist["ai-overseer/settings"]
    assert saved.missions == "all" and saved.send_missions is True
    back = S.load_settings()
    assert back.missions == "all" and back.send_missions is True


@test("set_rules takes the choice and the switch; an unknown choice is refused and the old value kept")
def _():
    r = TP.act({"type": "set_rules", "rules": {"missions": "explore", "send_missions": True}})
    assert r.ok, dict(r)
    assert TP.saved().missions == "explore" and TP.saved().send_missions is True
    assert r.changed.missions.old == "rescue" and r.changed.missions.new == "explore"
    for bad in ("conquest", True, 3):
        r = TP.act({"type": "set_rules", "rules": {"missions": bad}})
        assert not r.ok and "missions" in r.error, (bad, dict(r))
        assert TP.saved().missions == "explore", bad
    r = TP.act({"type": "set_rules", "rules": {"send_missions": "on"}})
    assert not r.ok and TP.saved().send_missions is True
    # the refusal names the choices set_rules takes
    assert "missions" in TP.act({"type": "set_rules", "rules": {"nope": True}}).error
    # a dry run saves nothing
    r = TP.act({"type": "set_rules", "rules": {"missions": "off"}, "dry_run": True})
    assert r.ok and TP.saved().missions == "explore"
    r = TP.act({"type": "set_rules", "rules": {"missions": "off"}})
    assert r.ok and TP.saved().missions == "off"


@test("presets don't set them")
def _():
    S = TP.H.settings()
    keys = lua_list(S.PRESET_RULE_KEYS)
    assert "missions" not in keys and "send_missions" not in keys
    for name in TP.PRESETS:
        s = S.defaults()
        s.missions = "all"
        assert S.load_preset(name, s).missions == "all", name


# --- the window ---------------------------------------------------------------------------

def army() -> str:
    a = GUI.index("function MilitaryPage:init()")
    return GUI[a:GUI.index("\nend\n", a)]


def army_refresh() -> str:
    a = GUI.index("function MilitaryPage:refresh()")
    return GUI[a:GUI.index("\nend\n", a)]


@test("window: the Army tab's Missions cycle and World screen switch, refreshed, with their help")
def _():
    src = army()
    assert "widgets.CycleHotkeyLabel{\n        view_id = 'missions'" in src
    assert code_has(src, "p:set_field('missions', v)") and code_has(src, "S.MISSION_CHOICES")
    assert code_has(src, "S.MISSION_NAMES[m]") and code_has(src, "S.MISSION_HELP")
    assert "widgets.ToggleHotkeyLabel{\n        view_id = 'send_missions'" in src
    assert code_has(src, "p:set_field('send_missions', v)")
    assert code_has(src, "initial_option = p.settings.send_missions == true")
    ref = army_refresh()
    assert code_has(ref, "self.subviews.missions:setOption(") and code_has(ref, "self.subviews.send_missions:setOption(")
    # labels fit their widths; the longest choice fits beside the label
    S = TP.H.settings()
    longest = max(len(S.MISSION_NAMES[m]) for m in lua_list(S.MISSION_CHOICES))
    m = re.search(r"view_id = 'missions',\s*frame = \{t = [^,]+, l = (\d+), w = (\d+)\},\s*label = '([^']*)',"
                  r"\s*label_width = (\d+)", src)
    assert m, "missions frame"
    l, w, label, lw = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
    assert len(label) <= lw and lw + longest + 4 <= w and l + w <= 118
    m = re.search(r"view_id = 'send_missions',\s*frame = \{t = [^,]+, l = (\d+), w = (\d+)\},\s*label = '([^']*)',"
                  r"\s*label_width = (\d+)", src)
    assert m and len(m.group(3)) <= int(m.group(4)) and int(m.group(1)) + int(m.group(2)) <= 118


@test("window: the Army tab's left-column rows don't collide and stay inside the 28 shown")
def _():
    src = army()
    cut = src.index("\n    t = t + 20\n")
    rows = []                                   # t = -3: the header at row 0
    for m in re.finditer(r"frame = \{t = t \+ (\d+), l = (\d+)", src[:cut]):
        if int(m.group(2)) < 56:
            rows.append(int(m.group(1)) - 3)
    rows += [1 + i for i in range(1, 8)]        # the seven military switches: t + 4 + i
    rows += [11 + i for i in (1, 2)]            # moon_cells, seal_caverns: t + 14 + i
    assert len(rows) == len(set(rows)), sorted(rows)
    assert {15, 16} <= set(rows), sorted(rows)  # the missions rows under the caverns' switch
    help_row = int(re.search(r"frame = \{t = t \+ (\d+), l = 0", src[cut:]).group(1)) + 20 - 3
    assert help_row > max(rows) and help_row + 3 <= 27, (help_row, sorted(rows))


@test("the settings, the window and the bridge actions compile under Lua 5.3")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-overseer-settings.lua", "gui/ai-overseer.lua", "ai-bridge-actions.lua"):
        ok = chk((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


@test("docs: military.md's Missions (13b), controls.md's switches, watch-in-game's checks")
def _():
    mil = (ROOT / "docs" / "military.md").read_text(encoding="utf-8")
    assert "## Missions (13b)" in mil
    for k in ("reserve", "one at a time", "threat", "World screen", "--here <Name>", "missions_back", "rescue",
              "recover_artifact", "explore", "raid", "`send_missions`"):
        assert k.lower() in mil.lower(), k
    ctl = (ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
    for k in ("**Missions to send out** (`missions`", "**Send missions by the World screen** (`send_missions`",
              "military.md#missions-13b"):
        assert k in ctl, k
    w = (ROOT / "docs" / "watch-in-game.md").read_text(encoding="utf-8")
    assert "probe_missions.py --watch" in w and "probe_missions.py --here <Name>" in w and "0.105.39" in w


if __name__ == "__main__":
    finish()
