"""(0.105.27, group settings) Tests for the disposal Rules keys (disposal,
disposal_player_items, keep_enemy_gear: defaults, sanitize, for_ai, the
window, the War-hold preset, set_rules) and the builder's place_dump_zone
(outside and inside, on test_builder's fake fort), in a real Lua engine.

    python tests/test_disposal_settings.py
"""

from __future__ import annotations

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

import test_preset as TP      # the bridge with a stub DFHack (its tests don't run on import)  # noqa: E402
import test_builder as TB     # the builder on a fake fort  # noqa: E402

GUI = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
SETTINGS = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
SURFACE = (ROOT / "lua" / "ai-builder-surface.lua").read_text(encoding="utf-8")


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)]


# --- the Rules keys ------------------------------------------------------------------

test = make_test(before=TP.reset)


@test("disposal keys: defaults destroy / off / off, kept through sanitize and for_ai; bad values repaired")
def _():
    S = TP.H.settings()
    d = S.defaults()
    assert d.disposal == "destroy" and d.disposal_player_items is False and d.keep_enemy_gear is False
    a = S.for_ai(d)
    assert a.disposal == "destroy" and a.disposal_player_items is False and a.keep_enemy_gear is False
    assert lua_list(S.DISPOSAL_CHOICES) == ["store", "melt", "dump", "destroy"]
    for m in lua_list(S.DISPOSAL_CHOICES):
        assert S.DISPOSAL_NAMES[m], m
        assert S.sanitize(TP.t({"disposal": m})).disposal == m
    s = S.sanitize(TP.t({"disposal": "melt", "disposal_player_items": True, "keep_enemy_gear": True}))
    a = S.for_ai(s)
    assert a.disposal == "melt" and a.disposal_player_items is True and a.keep_enemy_gear is True
    bad = S.sanitize(TP.t({"disposal": "burn", "disposal_player_items": "yes", "keep_enemy_gear": 1}))
    assert bad.disposal == "destroy" and bad.disposal_player_items is False and bad.keep_enemy_gear is False
    assert S.sanitize(TP.t({})).disposal == "destroy"


@test("disposal keys: keep_enemy_gear is a preset rule; War-hold sets it on, the others leave it")
def _():
    S = TP.H.settings()
    keys = lua_list(S.PRESET_RULE_KEYS)
    assert "keep_enemy_gear" in keys and "disposal" not in keys
    assert S.BUILTIN_PRESET_RULES["War-hold"].keep_enemy_gear is True
    for name in TP.PRESETS:
        if name != "War-hold":
            assert S.BUILTIN_PRESET_RULES[name].keep_enemy_gear is None, name
    r = TP.act({"type": "apply_preset", "name": "War-hold"})
    assert r.ok and TP.saved().keep_enemy_gear is True and r.rules.keep_enemy_gear is True, dict(r)
    TP.reset()
    r = TP.act({"type": "apply_preset", "name": "Monastery"})
    assert r.ok and TP.saved().keep_enemy_gear is False


@test("disposal keys: set_rules takes disposal as one of its four choices and the two switches as on/off")
def _():
    r = TP.act({"type": "set_rules", "rules": {"disposal": "dump", "keep_enemy_gear": True,
                                               "disposal_player_items": True}})
    assert r.ok and r.changed.disposal.new == "dump" and r.changed.disposal.old == "destroy", dict(r)
    s = TP.saved()
    assert s.disposal == "dump" and s.keep_enemy_gear is True and s.disposal_player_items is True
    for bad in ({"disposal": "burn"}, {"disposal": True}, {"keep_enemy_gear": "yes"},
                {"mode": "autopilot"}, {"tribute": "pay"}):
        r = TP.act({"type": "set_rules", "rules": bad})
        assert not r.ok and r.rejected, bad
    assert TP.saved().disposal == "dump"
    r = TP.act({"type": "set_rules", "rules": {"disposal": "store"}, "dry_run": True})
    assert r.ok and r.changed.disposal.new == "store" and TP.saved().disposal == "dump"


@test("disposal keys: the Rules tab has the cycle and both switches, set and refreshed, clear of other rows")
def _():
    for v in ("disposal", "disposal_player_items", "keep_enemy_gear"):
        assert code_has(GUI, f"view_id = '{v}'") and code_has(GUI, f"p:set_field('{v}', v)"), v
        assert code_has(GUI, f"self.subviews.{v}:setOption("), v
    assert code_has(GUI, "S.DISPOSAL_CHOICES") and code_has(GUI, "S.DISPOSAL_NAMES")
    # the right-hand column at t+5..t+8 beside the military list (its rows end at l=52; the
    # only wide rows there are attack_policy at t+4 and gear_weapon/prisoners from t+13)
    import re
    mil = GUI[GUI.index("view_id = 'attack_policy'"):GUI.index("function RulesPage:refresh")]
    frames = re.findall(r"frame = \{t = t \+ (\d+)(?: \+ i)?, l = (\d+)(?:, w = (\d+))?\}", mil)
    mine = [(int(t), int(l), int(w or 30)) for t, l, w in frames if int(l) >= 56]
    others = [(int(t), int(l), int(w or 50)) for t, l, w in frames if int(l) < 56]
    # (0.105.41) the siege switches at t+9..t+12 (frames by f[3]); "Peace offered" and its
    # help line at t+15, t+16; cavern logging at t+17; (0.105.45) kill zones at t+18, l=76; hunting at t+19, l=64; the lure switch at t+3
    # (the missions row beside it ends at column 74)
    assert sorted(t for t, _, _ in mine) == [3, 5, 6, 7, 8, 15, 16, 17, 18, 19], mine
    for t, l, w in others:
        if t in (5, 6, 7, 8):                   # the list's seven run t+5..t+11 at l=2, w=50
            assert l + w <= 56, (t, l, w)
    ok = LuaRuntime(unpack_returned_tuples=True).eval(
        "function(src) local f, e = load(src, 'gui', 't', {}); return f ~= nil, e end")(GUI)
    assert ok[0], ok


@test("disposal keys: the settings, the window, the builder part and the bridge compile under Lua 5.3")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-overseer-settings.lua", "ai-builder-surface.lua", "ai-bridge-actions.lua", "gui/ai-overseer.lua"):
        ok = chk((ROOT / "lua" / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


@test("disposal keys: docs/controls.md names the three keys")
def _():
    doc = (ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
    for k in ("`disposal`", "`disposal_player_items`", "`keep_enemy_gear`", '"disposal": "dump"'):
        assert k in doc, k


# --- place_dump_zone on the fake fort -------------------------------------------------

B, W, LUA = TB.B, TB.W, TB.LUA
ZONE_IDS = {"n": 0}


def _reset_world():
    W.reset()
    B.TRY_BESIDE = False
    ZONE_IDS["n"] = 0
    B.dump_zones = LUA.eval("function() return {} end")
    B.dump_keep_away = LUA.eval("function() return {} end")
    B.dump_zone_id_at = LUA.eval("function(x, y, z) return 900 + x end")


wtest = make_test(before=_reset_world)


def zones():
    return [c for c in W.placed.values() if c.mode == "zone"]


def designated():
    return [k for k, t in W.tiles.items() if t.designated]


def alcove(x, y, z, door):
    """(0.105.27 fixes) A dead-end 3x3 of floor at (x, y) on level z, opening
    to the hall through the one tile `door`."""
    for yy in range(y, y + 3):
        for xx in range(x, x + 3):
            W.set(xx, yy, z, LUA.table_from({"shape": "FLOOR"}))
    W.set(door[0], door[1], z, LUA.table_from({"shape": "FLOOR"}))


@wtest("place_dump_zone inside: a named dump zone on a free dead-end 3x3 near the entrance, never at it nor in the hall")
def _():
    alcove(62, 67, 80, (63, 66))
    r = B.place_dump_zone(True, True)
    assert r.ok and r.inside is True and r.dry_run and r.zone_id is None and not zones(), dict(r)
    r = B.place_dump_zone(True, False)
    assert r.ok and r.inside is True and r.why and (r.x, r.y, r.z) == (62, 67, 80), dict(r)
    assert r.zone_id == 901 + r.x
    z = zones()
    assert len(z) == 1 and z[0].text == 'd{name="AI dump"}(3x3)' and (z[0].x, z[0].y, z[0].z) == (r.x, r.y, r.z)
    assert max(abs(r.x + 1 - 60), abs(r.y + 1 - 60)) >= 3, (r.x, r.y)
    assert max(abs(r.x + 1 - 60), abs(r.y + 1 - 60)) <= 20, (r.x, r.y)


@wtest("place_dump_zone inside: kept 10 tiles from the meeting hall, dining hall and food")
def _():
    B.dump_keep_away = LUA.eval("function() return {{x1 = 50, y1 = 55, x2 = 66, y2 = 65, z = 80},"
                                " {x1 = 50, y1 = 55, x2 = 66, y2 = 65, z = 79}} end")
    alcove(62, 67, 80, (63, 66))          # too near the hall
    alcove(78, 67, 80, (79, 66))          # far enough
    r = B.place_dump_zone(True, False)
    assert r.ok and (r.x, r.y, r.z) == (78, 67, 80), dict(r)
    assert r.x > 66 + 10 or r.x + 2 < 50 - 10, (r.x, r.y, r.z)
    assert r.zone_id is not None


@wtest("place_dump_zone: a dump already on that side of the walls is kept, no second one")
def _():
    B.dump_zones = LUA.eval("function() return {{id = 44, x1 = 70, y1 = 58, x2 = 72, y2 = 60, z = 78, inside = true}} end")
    r = B.place_dump_zone(True, False)
    assert r.ok and r.existing and r.zone_id == 44 and r.inside is True and not zones(), dict(r)
    # an inside one doesn't count for outside (nowhere open outside here)
    r = B.place_dump_zone(False, False)
    assert not r.ok and r.inside is False and r.why and not zones(), dict(r)


@wtest("place_dump_zone inside: no free floor, so a 3x3 room is dug through a doorway; the zone once it is dug")
def _():
    for z in range(77, 81):
        for x in range(40, 81):
            for y in range(55, 66):
                if (x, y) != (60, 60):
                    W.set(x, y, z, LUA.table_from({"taken": True}))
    r = B.place_dump_zone(True, True)
    assert r.ok and r.digging and r.dry_run and not designated(), dict(r)
    r = B.place_dump_zone(True, False)
    assert r.ok and r.digging and r.inside is True and r.zone_id is None and not zones(), dict(r)
    room = [(x, y) for y in range(r.y, r.y + 3) for x in range(r.x, r.x + 3)]
    for x, y in room:
        assert W.get(x, y, r.z).designated, (x, y)
    door = W.get(r.door.x, r.door.y, r.z)
    assert door.designated and (r.door.x, r.door.y) not in room
    assert len(designated()) == 10, len(designated())
    assert max(abs(r.x + 1 - 60), abs(r.y + 1 - 60)) <= 20
    rx, ry, rz = r.x, r.y, r.z
    # still being dug: waits, digs nothing more
    w = B.place_dump_zone(True, False)
    assert not w.ok and w.waiting and len(designated()) == 10, dict(w)
    # dug: the zone goes in the room
    for x, y in room + [(r.door.x, r.door.y)]:
        W.set(x, y, rz, LUA.table_from({"shape": "FLOOR", "designated": False}))
    d = B.place_dump_zone(True, False)
    assert d.ok and d.inside and (d.x, d.y, d.z) == (rx, ry, rz) and d.zone_id == 901 + rx, dict(d)
    assert [c.text for c in zones()] == ['d{name="AI dump"}(3x3)']
    assert W.persist["ai-overseer/dump-room"].room is None


@wtest("place_dump_zone inside: never digs into water, an aquifer or the sky")
def _():
    for z in range(77, 81):
        for x in range(40, 81):
            for y in range(55, 66):
                if (x, y) != (60, 60):
                    W.set(x, y, z, LUA.table_from({"taken": True}))
        for x in range(35, 86):
            for y in (53, 67):
                W.set(x, y, z, LUA.table_from({"aquifer": True}))
        for y in range(50, 71):
            for x in (38, 82):
                W.set(x, y, z, LUA.table_from({"liquid": True}))
    r = B.place_dump_zone(True, False)
    assert not r.ok and r.inside is True and r.why and not designated(), dict(r)


@wtest("place_dump_zone outside: the existing place_surface dump on open ground, with its zone id")
def _():
    for x in range(45, 80):
        for y in range(45, 80):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True}))
    r = B.place_dump_zone(False, True)
    assert r.ok and r.inside is False and r.dry_run and r.zone_id is None and not zones(), dict(r)
    r = B.place_dump_zone(False, False)
    assert r.ok and r.inside is False and r.z == 80 and r.zone_id == 900 + r.x + 1 and r.why, dict(r)
    z = zones()
    assert len(z) == 1 and z[0].text == "d(3x3)" and (z[0].x, z[0].y) == (r.x, r.y)
    assert not (r.x - 8 < 60 < r.x + 3 + 8 and r.y - 8 < 60 < r.y + 3 + 8), (r.x, r.y)


@wtest("place_dump_zone: the function is in ai-builder-surface.lua and returns the contract's fields")
def _():
    assert code_has(SURFACE, "function place_dump_zone(inside, dry_run)")
    r = B.place_dump_zone(True, True)
    for k in ("ok", "x", "y", "z", "inside", "why"):
        assert r[k] is not None, k


if __name__ == "__main__":
    finish()
