"""(0.105.39, G4) The Rules switches for Phase 13b's missions: `missions`
(off / rescue / explore / all; (r10 p3, the player 22 Nov) default all, the
raid policy deciding the raids) and `send_missions` ((r10 p3) default on) in
lua/ai-overseer-settings.lua (defaults, sanitize, for_ai, old saves,
set_rules), the Army tab's rows in the window, and the docs; in a real Lua
engine (lupa, Lua 5.3).

    python tests/test_missions_settings.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import gui_behaviour as GB  # noqa: E402  (r5 p5) the window on a stub gui
import test_preset as TP      # the bridge and the settings with a stub DFHack  # noqa: E402


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


@test("defaults (r10 p3): all, and send_missions on; for_ai hands both to the brain")
def _():
    S = TP.H.settings()
    d = S.defaults()
    assert d.missions == "all" and d.send_missions is True
    a = S.for_ai(d)
    assert a.missions == "all" and a.send_missions is True
    s = S.load_settings()                 # nothing saved: the defaults
    assert s.missions == "all" and s.send_missions is True


@test("sanitize: each choice kept; an unknown value reads the default (all); send_missions only true when true")
def _():
    S = TP.H.settings()
    rev = S.CONTACT_REV          # (r10 p3) a save with the contact revision: its values as they are
    for m in ("off", "rescue", "explore", "all"):
        assert S.sanitize(TP.t({"missions": m, "contact_rev": rev})).missions == m
        assert S.for_ai(TP.t({"missions": m, "contact_rev": rev})).missions == m
    for bad in ("All", "raid", 1, True, False, ""):
        assert S.sanitize(TP.t({"missions": bad, "contact_rev": rev})).missions == "all", bad
    assert S.sanitize(TP.t({"send_missions": True, "contact_rev": rev})).send_missions is True
    assert S.sanitize(TP.t({"send_missions": "yes", "contact_rev": rev})).send_missions is False
    assert S.sanitize(TP.t({"send_missions": False, "contact_rev": rev})).send_missions is False
    assert S.for_ai(TP.t({"send_missions": True})).send_missions is True


@test("an old save without them reads the defaults and keeps its other settings")
def _():
    S = TP.H.settings()
    TP.H.persist["ai-overseer/settings"] = TP.t({"version": 2, "mode": "copilot", "send_messenger": True,
                                                 "construct": False})
    s = S.load_settings()
    assert s.missions == "all" and s.send_missions is True          # (r10 p3) the new defaults
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
    assert r.changed.missions.old == "all" and r.changed.missions.new == "explore"     # (r10 p3) 'all' the default
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


@test("presets: every preset sets missions 'all'; none names send_messenger, send_missions or raid_policy, so they "
      "stay as the fort has them ((r10 p3) on / 'ai' by default, the player's own off kept)")
def _():
    S = TP.H.settings()
    keys = lua_list(S.PRESET_RULE_KEYS)
    for k in ("missions", "send_missions", "send_messenger", "raid_policy"):
        assert k in keys, k
    for name in TP.PRESETS:
        p0 = S.load_preset(name, S.defaults())             # (r10 p3) a new fort: everything on, the AI decides
        assert p0.missions == "all" and p0.send_missions is True and p0.raid_policy == "ai", name
        assert p0.send_messenger is True, name
        s = S.defaults()
        s.missions, s.raid_policy, s.send_messenger, s.send_missions = "rescue", "off", False, False
        p = S.load_preset(name, s)                          # the player's own "off": kept
        assert p.missions == "all" and p.send_missions is False and p.raid_policy == "off", name
        assert p.send_messenger is False, name
        # and a player's own choice is kept
        s2 = S.defaults()
        s2.raid_policy, s2.send_missions, s2.send_messenger = "reactive", True, True
        p2 = S.load_preset(name, s2)
        assert p2.raid_policy == "reactive" and p2.send_missions is True and p2.send_messenger is True, name
    for name in TP.PRESETS:
        r = S.BUILTIN_PRESET_RULES[name]
        assert r.send_messenger is None and r.send_missions is None and r.raid_policy is None, name


@test("raid_policy (J17): ai / aggressive / reactive / off, (r10 p3) default ai, sanitized, for_ai, set_rules, in RULE_CHOICES")
def _():
    S = TP.H.settings()
    assert lua_list(S.RAID_POLICY_CHOICES) == ["ai", "aggressive", "reactive", "off"]
    assert lua_list(S.RULE_CHOICES.raid_policy) == ["ai", "aggressive", "reactive", "off"]
    for m in lua_list(S.RAID_POLICY_CHOICES):
        assert S.RAID_POLICY_NAMES[m] and len(S.RAID_POLICY_NAMES[m]) <= 24, m
    assert S.defaults().raid_policy == "ai" and S.for_ai(S.defaults()).raid_policy == "ai"
    assert S.defaults().send_missions is True and S.defaults().send_messenger is True
    for m in ("ai", "aggressive", "reactive", "off"):
        assert S.sanitize(TP.t({"raid_policy": m, "contact_rev": S.CONTACT_REV})).raid_policy == m
    assert S.sanitize(TP.t({"raid_policy": "war"})).raid_policy == "ai"
    r = TP.act({"type": "set_rules", "rules": {"raid_policy": "reactive"}})
    assert r.ok and TP.saved().raid_policy == "reactive", dict(r)
    assert not TP.act({"type": "set_rules", "rules": {"raid_policy": "always"}}).ok



# --- the window ---------------------------------------------------------------------------

# (r5 p5) the window built on a stub gui (tests/gui_behaviour.py), not its source cut by regexes

@test("window: the Army tab's Missions cycle and World screen switch, refreshed, with their help")
def _():
    # (r5 p5) behaviour, not source text
    S = TP.H.settings()
    m = GB.control("MilitaryPage", "missions", kind="CycleHotkeyLabel", values=lua_list(S.MISSION_CHOICES), pad=4)
    assert [v for _, v in m.options] == lua_list(S.MISSION_CHOICES)
    assert [n for n, _ in m.options] == [S.MISSION_NAMES[x] for x in lua_list(S.MISSION_CHOICES)]
    GB.control("MilitaryPage", "send_missions", kind="ToggleHotkeyLabel", values=[True, False], default=True)   # (r10 p3)
    on = GB.find(GB.page(GB.window({"send_missions": True}), "MilitaryPage"), "send_missions")
    assert on.initial_option is True
    odd = GB.find(GB.page(GB.window({"send_missions": "yes", "contact_rev": S.CONTACT_REV}), "MilitaryPage"),
                  "send_missions")
    assert odd.initial_option is False                                 # only true is on
    texts = [w.text for w in GB.widgets(GB.page(GB.window(), "MilitaryPage")) if w.text]
    assert S.MISSION_HELP in texts, texts


@test("window (J17): the Raids cycle on the Army tab's free row t+14, l=76, set and refreshed")
def _():
    # (r5 p5) behaviour, not source text
    S = TP.H.settings()
    w = GB.control("MilitaryPage", "raid_policy", kind="CycleHotkeyLabel", values=lua_list(S.RAID_POLICY_CHOICES), pad=4)
    assert w.row == 11 and w.l >= 76, w                                # t + 14 with the header's t = -3


@test("window: the Army tab's left-column rows don't collide and stay inside the 28 shown")
def _():
    # (r5 p5) behaviour, not source text
    win = GB.window()
    army = GB.page(win, "MilitaryPage")
    ws = GB.widgets(army)
    left = [w for w in ws if w.row is not None and w.l is not None and w.l < 56 and w.kind != "WrappedLabel"]
    rows = [w.row for w in left if w.l < 30]                           # one control per row in the left column
    assert len(rows) == len(set(rows)), sorted(rows)
    assert GB.find(army, "missions").row == 15 and GB.find(army, "send_missions").row == 16
    assert GB.find(army, "seal_caverns").row < 15                      # the missions rows under the caverns' switch
    help_row = max(w.row for w in ws if w.kind == "WrappedLabel")
    assert help_row > max(rows) and help_row + 3 <= GB.visible_rows(win) - 1, (help_row, sorted(rows))
    assert GB.overlaps(army) == [], GB.overlaps(army)


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
