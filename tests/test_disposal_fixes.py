"""(0.105.27, disposal fixes) The independent verifier's findings on the
disposal round, each pinned by a regression test:

 1. empty_dump's max: the brain never asks more than the bridge takes (one
    limit, DISPOSAL_ACTION_MAX = DISPOSAL_MAX = MAX_CAP = 500);
 2. mark_dump never goes out with an empty reasons list ('free' always);
 3. mark_melt / mark_dump touch only items lying loose on the ground;
 4. ONE classifier (ai-util forbidden_reason, cistern_tiles): own dead =
    race AND civ, gear within the 3x3 round a body, the cistern's room,
    tunnel and shaft and the retired ones, never the plug;
 5. bodies counted apart (forbidden.corpses), out of by_reason, so a fort of
    bodies only asks for no unforbid;
 6. empty_dump removes only forbidden items, never the fort's remains or a
    living owner's;
 7. place_dump_zone: tiles with no item or building, and inside only a dead
    end (no through-path), else the dug room;
 8. mark_melt melts clutter, not stock: never in a pile or a bin, never a
    pick or an axe;
 9. the slow-game dump rule steps aside only at Rules dump / destroy;
10. the Rules widgets have room (end well inside the window);
11. unforbid_items refuses 'dumped'.

    python tests/test_disposal_fixes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, make_test, finish, code_has  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_disposal_actions as A      # ai-disposal on a fake fort  # noqa: E402
import test_disposal_brain as BR       # the brain's disposal state  # noqa: E402
import test_disposal_census as C       # ai-census on a fake fort  # noqa: E402
import test_disposal_settings as S     # the builder's fake fort (place_dump_zone)  # noqa: E402
from planner_config import PLANNER_CONFIG, DISPOSAL_ACTION_MAX  # noqa: E402
from planner_core import player_rules  # noqa: E402
from planner_industry import _slow_game_rules, disposal_places_dump  # noqa: E402

LUA_DIR = ROOT / "lua"
UTIL = (LUA_DIR / "ai-util.lua").read_text(encoding="utf-8")
DISPOSAL = (LUA_DIR / "ai-disposal.lua").read_text(encoding="utf-8")
CENSUS = (LUA_DIR / "ai-census.lua").read_text(encoding="utf-8")
ACTS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
CISTERN = (LUA_DIR / "ai-builder-cistern.lua").read_text(encoding="utf-8")

mk, opts, skipped = A.mk, A.opts, A.skipped


def lua_set(src: str, name: str) -> set:
    body = re.search(rf"local {name} = \{{(.*?)\}}", src, re.S).group(1)
    return set(re.findall(r"(\w+) = true", body))


# --- 1. one limit for a disposal call ----------------------------------------------------

@test("1. the brain's DISPOSAL_ACTION_MAX, the bridge's DISPOSAL_MAX and ai-disposal's MAX_CAP are one 500")
def _():
    bridge = int(re.search(r"^local DISPOSAL_MAX = (\d+)", ACTS, re.M).group(1))
    cap = int(re.search(r"^MAX_CAP = (\d+)", DISPOSAL, re.M).group(1))
    assert DISPOSAL_ACTION_MAX == bridge == cap == 500, (DISPOSAL_ACTION_MAX, bridge, cap)
    assert "int_in(a.max, 1, DISPOSAL_MAX)" in ACTS
    for k in ("disposal_unforbid_max", "disposal_melt_max", "disposal_dump_max", "disposal_empty_max"):
        assert PLANNER_CONFIG[k] <= DISPOSAL_ACTION_MAX, k


@test("1. a dump holding 800 items: empty_dump asks 500, the most the bridge takes (it asked 800 before)")
def _():
    s, m = BR.state()
    s["disposal"]["dumped_items"] = 800
    got, _ = BR.run(s, m)
    assert got["disposal_empty"].action == {"type": "empty_dump", "max": 500}, got["disposal_empty"].action
    # even with the config raised past it
    cfg = dict(PLANNER_CONFIG, disposal_empty_max=5000, disposal_dump_max=900, disposal_unforbid_max=900)
    props = []
    from planner_industry import _disposal_rules
    _disposal_rules(s, cfg, props, [], m, player_rules(s))
    for p in props:
        if "max" in p.action:
            assert p.action["max"] <= 500, p.action


# --- 2. mark_dump's reasons --------------------------------------------------------------

@test("2. War-hold (keep_enemy_gear) with dead unburied: mark_dump asks for the free junk, never reasons []")
def _():
    s, m = BR.state(keep_enemy_gear=True)
    s["dead"]["unburied"] = 3
    got, _ = BR.run(s, m)
    a = got["disposal_dump"].action
    assert a["reasons"] == ["free"], a


@test("2. every reasons list the brain sends is one the bridge accepts (non-empty, known names)")
def _():
    dump_ok, unf_ok = lua_set(ACTS, "DUMP_REASONS"), lua_set(ACTS, "DISPOSAL_REASONS")
    for kw in ({}, {"keep_enemy_gear": True}, {"disposal_player_items": True},
               {"keep_enemy_gear": True, "disposal_player_items": True}):
        for unburied in (0, 2):
            s, m = BR.state(**kw)
            s["dead"]["unburied"] = unburied
            got, _ = BR.run(s, m)
            for rule, ok in (("disposal_dump", dump_ok), ("disposal_unforbid", unf_ok)):
                if rule in got:
                    r = got[rule].action["reasons"]
                    assert r and set(r) <= ok, (kw, unburied, rule, r)


# --- 3. only what lies on the ground ------------------------------------------------------

@test("3. mark_melt and mark_dump never touch an item in a bin or a unit's hands (forbid, melt, dump unchanged)")
def _():
    lua, env, w = A.world()
    w.dump(50, 10, 10, 150)
    w.furnaces[1] = lua.table_from({"type": 1})
    inbin = [mk(lua, w, kind=k, metal=metal, wear=3, flags={"forbid": True, "dead_dwarf": True,
                                                          "in_inventory": True, "on_ground": False})
             for k, metal in (("WEAPON", True), ("ARMOR", True), ("PANTS", False), ("SHOES", False))]
    inbin.append(mk(lua, w, kind="MEAT", flags={"rotten": True, "in_inventory": True, "on_ground": False}))
    inbin.append(mk(lua, w, kind="PANTS", wear=3, flags={"in_inventory": True, "on_ground": False}))
    for fn in ("mark_melt", "mark_dump"):
        r = env[fn](opts(lua, player_items=True, reasons=["own_dead", "free"]) if fn == "mark_dump"
                    else opts(lua, player_items=True), False)
        assert r.n == 0, (fn, dict(r))
    for it in inbin:
        assert not it.flags.melt and not it.flags.dump, dict(it.flags)
    assert all(it.flags.forbid for it in inbin[:4])
    # the same lying loose are taken
    loose = mk(lua, w, kind="PANTS", wear=3, flags={"forbid": True, "dead_dwarf": True})
    r = env.mark_dump(opts(lua), False)
    assert r.n == 1 and loose.flags.dump, dict(r)


# --- 4. one classifier ----------------------------------------------------------------------

UTIL_FAKE = r"""
local util_src, site, units = ...
local env = setmetatable({}, {__index = _G})
env.df = {global = {plotinfo = {race_id = 1, civ_id = 7}, world = {items = {other = {CORPSE = {}, CORPSEPIECE = {}}}}},
          item_type = setmetatable({}, {__index = function(_, k) return k end}),
          unit = {find = function(id) return units[id] end}}
env.dfhack = {persistent = {getSiteData = function(k, d) local v = site[k]; if v == nil then return d end return v end},
              items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
                       getOwner = function(it) return it.owner end},
              units = {isDead = function(u) return u.dead == true end}}
assert(load(util_src, 'ai-util', 't', env))()
function env.item(kind, x, y, z, flags, extra)
    local t = {kind = kind, pos = {x = x, y = y, z = z}, flags = flags or {forbid = true, on_ground = true},
               getType = function(self) return self.kind end}
    for k, v in pairs(extra or {}) do t[k] = v end
    local o = env.df.global.world.items.other
    if o[kind] then table.insert(o[kind], t) end
    return t
end
return env
"""


def util_world(site=None, units=None):
    """ai-util on a fake game; site and units are Python dicts."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(UTIL_FAKE, UTIL, lt(lua, site or {}), lt(lua, units or {}))
    return lua, env


def lt(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: lt(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([lt(lua, v) for v in d])
    return d


@test("4. ai-util cistern_tiles: room, tunnel and shaft, retired cisterns too, never the plug")
def _():
    plan = {"cistern": {"x1": 10, "y1": 10, "x2": 11, "y2": 11, "z": 50}, "intake_z": 53,
            "tunnel_path": [{"x": 20, "y": 20}, {"x": 21, "y": 20}, {"x": 22, "y": 20}], "shaft": {"x": 12, "y": 12}}
    retired = [{"cistern": {"x1": 30, "y1": 30, "x2": 30, "y2": 31, "z": 40}},
               {"cistern": {"x1": 60, "y1": 60, "x2": 60, "y2": 60, "z": 45}, "intake_z": 45,
                "tunnel_path": [{"x": 61, "y": 60}, {"x": 62, "y": 60}]}]
    _, env = util_world(site={"ai-overseer/cistern": {"plan": plan}, "ai-overseer/cistern/retired": retired})
    t = set(dict(env.cistern_tiles()).keys())
    want = {"10,10,50", "11,10,50", "10,11,50", "11,11,50",             # the room
            "20,20,53", "21,20,53",                                      # the tunnel; 22,20 is the plug
            "12,12,50", "12,12,51", "12,12,52", "12,12,53",              # the shaft
            "30,30,40", "30,31,40", "60,60,45", "61,60,45"}              # retired: rooms, a tunnel
    assert t == want, (t - want, want - t)


@test("4. own dead = the fort's race AND civ; a dwarf of another civ is another's (census and actions alike)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(UTIL_FAKE, UTIL, lua.table_from({}),
                      lua.table_from({11: lua.table_from({"civ_id": 7}), 12: lua.table_from({"civ_id": 9})}))
    ctx = env.forbid_context()
    own = env.item("CORPSE", 5, 5, 5, None, lua.table_from({"race": 1, "unit_id": 11}))
    other_civ = env.item("CORPSE", 9, 9, 5, None, lua.table_from({"race": 1, "unit_id": 12}))
    goblin = env.item("CORPSEPIECE", 20, 20, 5, None, lua.table_from({"race": 2, "unit_id": 99}))
    assert tuple(env.forbidden_reason(own, ctx)) == ("own_dead", "own")
    assert tuple(env.forbidden_reason(other_civ, ctx)) == ("other_dead", "other")
    assert tuple(env.forbidden_reason(goblin, ctx)) == ("other_dead", "other")
    # but nothing of the fort's race is ever destroyed (empty_dump's own test)
    assert env.fort_remains(other_civ, "CORPSE", ctx) and env.fort_remains(own, "CORPSE", ctx)
    assert not env.fort_remains(goblin, "CORPSEPIECE", ctx)


@test("4. gear within the 3x3 round another's body is other_dead; two tiles off, or in a bin, it isn't")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(UTIL_FAKE, UTIL, lua.table_from({}), lua.table_from({}))
    ctx = env.forbid_context()
    env.item("CORPSE", 20, 20, 5, None, lua.table_from({"race": 2}))
    diag = env.item("HELM", 21, 21, 5)
    far = env.item("HELM", 22, 20, 5)
    held = env.item("HELM", 19, 19, 5, lua.table_from({"forbid": True, "in_inventory": True}))
    boulder = env.item("BOULDER", 20, 21, 5)
    assert env.forbidden_reason(diag, ctx)[0] == "other_dead"
    assert env.forbidden_reason(far, ctx)[0] == "unknown"
    assert env.forbidden_reason(held, ctx)[0] == "unknown"
    assert env.forbidden_reason(boulder, ctx)[0] == "unknown"


@test("4. the census and ai-disposal both classify through ai-util forbidden_reason (no copies left)")
def _():
    assert re.search(r"^function forbidden_reason\(it, ctx, kind, x, y, z\)", UTIL, re.M)
    assert re.search(r"^function cistern_tiles\(\)", UTIL, re.M)
    assert "U.forbidden_reason(it, ctx, kind, x, y, z)" in DISPOSAL
    assert "ctx.U.forbidden_reason, it, ctx, t, x, y, z" in CENSUS
    for src, name in ((CENSUS, "census"), (DISPOSAL, "disposal")):
        for copy in ("function cistern_tiles", "function corpse_of", "function corpse_tiles", "settle_pending",
                     "DEAD_GEAR = {", "function owner_of"):
            assert copy not in src, (name, copy)
    # the retired cistern keeps its tunnel and shaft for cistern_tiles
    assert "tunnel_path = p0.tunnel_path" in CISTERN and "shaft = p0.shaft" in CISTERN


@test("4. the actions agree with the census: a dwarf of another civ's gear by the body, diagonal, is let go")
def _():
    lua, env, w = A.world()
    w.unit(lua.table_from({"id": 5, "civ_id": 9, "pos": lua.table_from({"x": 0, "y": 0, "z": 0}), "dead": True}))
    env.df["global"].plotinfo.civ_id = 7
    env.df.unit = lua.table_from({"find": lua.eval("function(id) return {civ_id = 9} end")})
    mk(lua, w, kind="CORPSE", race=1, unit_id=5, flags={"forbid": True}, pos=(30, 30, 130))
    helm = mk(lua, w, kind="HELM", flags={"forbid": True}, pos=(31, 31, 130))
    r = env.unforbid_items(opts(lua, reasons=["other_dead"]), False)
    assert r.n == 1 and not helm.flags.forbid and dict(r.by_reason) == {"other_dead": 1}, (dict(r), skipped(r))


# --- 5. bodies apart -------------------------------------------------------------------------

@test("5. the census: bodies in forbidden.corpses {own, other}, none in by_reason")
def _():
    _, env = C.world()
    fb = C.forbidden(env)
    assert dict(fb.corpses) == {"own": 1, "other": 2}, dict(fb.corpses)
    assert sum(dict(fb.by_reason).values()) == fb.total - 3


@test("5. a fort holding only forbidden bodies (the new census) asks for no unforbid_items")
def _():
    s, m = BR.state()
    fb = m.census["items"]["forbidden"]
    fb["by_reason"] = {"other_dead": 0, "own_dead": 0, "used_ammo": 0, "dumped": 0, "ai": 0, "unknown": 0}
    fb["corpses"] = {"own": 0, "other": 200}
    fb["by_type"] = {"CORPSE": 150, "CORPSEPIECE": 50}
    fb["total"], fb["metal"], fb["worn"] = 200, 0, 0
    got, _ = BR.run(s, m)
    assert "disposal_unforbid" not in got and "disposal_melt" not in got, sorted(got)


@test("5. a census from before the fix (bodies inside other_dead, no corpses key) is counted again, not acted on")
def _():
    s, m = BR.state()
    fb = m.census["items"]["forbidden"]
    del fb["corpses"]
    fb["by_reason"] = {"other_dead": 200, "own_dead": 0, "used_ammo": 0, "dumped": 0, "ai": 0, "unknown": 0}
    fb["by_type"], fb["metal"], fb["worn"] = {"CORPSE": 150, "CORPSEPIECE": 50}, 0, 0
    got, _ = BR.run(s, m)
    assert "census" in got and "disposal_unforbid" not in got and "disposal_dump" not in got, sorted(got)


# --- 6. empty_dump ------------------------------------------------------------------------------

@test("6. empty_dump: only forbidden items; never a citizen's body, a dwarf's of any civ, a dead dwarf's or a living owner's")
def _():
    lua, env, w = A.world()
    env.df["global"].plotinfo.civ_id = 7
    env.df.unit = lua.table_from({"find": lua.eval("function(id) if id == 5 then return {civ_id = 7} end "
                                                   "return {civ_id = 9} end")})
    w.dump(50, 10, 10, 150)
    citizen = mk(lua, w, kind="CORPSE", race=1, unit_id=5, flags={"forbid": True, "dead_dwarf": True}, pos=(11, 11, 150))
    dwarf = mk(lua, w, kind="CORPSEPIECE", race=1, unit_id=6, flags={"forbid": True}, pos=(10, 11, 150))
    civ = mk(lua, w, kind="CORPSE", race=3, unit_id=5, flags={"forbid": True}, pos=(12, 11, 150))
    ring = mk(lua, w, kind="RING", flags={"forbid": True, "dead_dwarf": True}, pos=(10, 10, 150))
    alive = w.unit(lua.table_from({"pos": lua.table_from({"x": 200, "y": 200, "z": 10})}))
    owned = mk(lua, w, kind="SHOES", flags={"forbid": True, "owned": True}, owner=alive, pos=(11, 10, 150))
    free = mk(lua, w, kind="CRAFTS", flags={}, pos=(12, 10, 150))
    goblin = mk(lua, w, kind="CORPSE", race=2, unit_id=8, flags={"forbid": True}, pos=(10, 12, 150))
    rags = mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(11, 12, 150))
    r = env.empty_dump(opts(lua), False)
    assert set(w.removed.values()) == {goblin.id, rags.id}, (list(w.removed.values()), skipped(r))
    for it in (citizen, dwarf, civ, ring, owned, free):
        assert not it.flags.removed
    s = skipped(r)
    assert s.get("own_remains") == 4 and s.get("not_forbidden") == 1 and s.get("owned") == 1, s


# --- 7. place_dump_zone ---------------------------------------------------------------------------

wtest = make_test(before=S._reset_world)
W, B, LUA = S.W, S.B, S.LUA


@wtest("7. inside: the hall's free floor is a through-path, never the dump; an alcove with an item is skipped")
def _():
    S.alcove(62, 67, 80, (63, 66))
    W.set(63, 68, 80, LUA.table_from({"items": True}))
    S.alcove(70, 67, 80, (71, 66))
    r = B.place_dump_zone(True, False)
    assert r.ok and (r.x, r.y, r.z) == (70, 67, 80) and r.zone_id is not None, dict(r)


@wtest("7. inside: an alcove open on two sides (a through-path) is no dump: the room is dug instead")
def _():
    S.alcove(62, 67, 80, (63, 66))
    W.set(65, 68, 80, LUA.table_from({"shape": "FLOOR"}))       # a second way out, into a corridor
    for x in range(66, 70):
        W.set(x, 68, 80, LUA.table_from({"shape": "FLOOR"}))
    r = B.place_dump_zone(True, False)
    assert r.ok and r.digging and r.zone_id is None, dict(r)


@wtest("7. inside: the dug room waits while something other than the dug rock lies in it")
def _():
    for z in range(77, 81):
        for x in range(40, 81):
            for y in range(55, 66):
                if (x, y) != (60, 60):
                    W.set(x, y, z, LUA.table_from({"taken": True}))
    r = B.place_dump_zone(True, False)
    assert r.ok and r.digging, dict(r)
    room = [(x, y) for y in range(r.y, r.y + 3) for x in range(r.x, r.x + 3)]
    for x, y in room + [(r.door.x, r.door.y)]:
        W.set(x, y, r.z, LUA.table_from({"shape": "FLOOR", "designated": False}))
    W.set(room[4][0], room[4][1], r.z, LUA.table_from({"items": True}))   # can't be read as rock: wait
    d = B.place_dump_zone(True, False)
    assert not d.ok and d.waiting and "hauled away" in d.error and not S.zones(), dict(d)
    W.set(room[4][0], room[4][1], r.z, LUA.table_from({"items": False}))
    d = B.place_dump_zone(True, False)
    assert d.ok and d.zone_id is not None, dict(d)


@wtest("7. outside: the dump's spot has no item on any tile")
def _():
    for x in range(45, 80):
        for y in range(45, 80):
            if (x, y) != (60, 60):
                W.set(x, y, 80, LUA.table_from({"shape": "FLOOR", "material": "SOIL", "outside": True,
                                                 "items": (x + y) % 3 == 0 and x < 75}))
    r = B.place_dump_zone(False, False)
    assert r.ok, dict(r)
    for x in range(r.x, r.x + 3):
        for y in range(r.y, r.y + 3):
            assert not W.get(x, y, 80)["items"], (x, y)
    assert r.x >= 75 - 2


# --- 8. mark_melt: clutter, not stock -----------------------------------------------------------

@test("8. mark_melt: stock in a pile or a bin, lightly worn spares and picks/axes stay; worn loose clutter goes")
def _():
    lua, env, w = A.world()
    w.piles[1] = lua.table_from({"x1": 60, "y1": 60, "x2": 80, "y2": 80, "z": 130})
    w.furnaces[1] = lua.table_from({"type": 1})
    pile = mk(lua, w, kind="WEAPON", metal=True, wear=3)                                   # in the pile (70,70,130)
    inbin = mk(lua, w, kind="ARMOR", metal=True, wear=3, flags={"in_inventory": True, "on_ground": False})
    spare = mk(lua, w, kind="WEAPON", metal=True, wear=1, pos=(10, 10, 130))               # lightly worn, loose
    pick = mk(lua, w, kind="WEAPON", metal=True, wear=3, pos=(11, 10, 130),
              subtype={"skill_melee": 0, "id": "ITEM_WEAPON_PICK"})
    axe = mk(lua, w, kind="WEAPON", metal=True, wear=3, flags={"forbid": True, "dead_dwarf": True},
             pos=(12, 10, 130), subtype={"skill_melee": 1, "id": "ITEM_WEAPON_AXE_BATTLE"})
    unknown_sub = mk(lua, w, kind="WEAPON", metal=True, wear=3, pos=(13, 10, 130), subtype=False)
    junk = mk(lua, w, kind="HELM", metal=True, wear=2, pos=(14, 10, 130))                 # worn, loose: clutter
    loot = mk(lua, w, kind="ARMOR", metal=True, wear=0, maker_race=2, pos=(15, 10, 130))  # foreign-made, loose
    piled_loot = mk(lua, w, kind="ARMOR", metal=True, wear=0, maker_race=2, pos=(65, 65, 130))
    r = env.mark_melt(opts(lua), False)
    assert {it.id for it in (junk, loot)} == {v.id for v in w["items"].values() if v.flags.melt}, \
        (dict(r), skipped(r))
    for it in (pile, inbin, spare, pick, axe, unknown_sub, piled_loot):
        assert not it.flags.melt
    assert skipped(r).get("tool") == 3, skipped(r)
    # keep_enemy_gear keeps the foreign-made loot
    loot.flags.melt = False
    r = env.mark_melt(opts(lua, keep_enemy_gear=True), False)
    assert not loot.flags.melt and skipped(r).get("enemy_gear") == 1, skipped(r)


@test("8. ai-disposal's is_tool: MINING or AXE skill, or PICK / AXE in the id; unreadable counts as a tool")
def _():
    lua, env, _ = A.world()
    t = lambda **kw: lua.table_from({"subtype": lua.table_from(kw)})  # noqa: E731
    assert env.is_tool(t(skill_melee=0, id="X"), "WEAPON") and env.is_tool(t(skill_melee=1, id="X"), "WEAPON")
    assert env.is_tool(t(skill_melee=9, id="ITEM_WEAPON_PICK"), "WEAPON")
    assert env.is_tool(t(skill_melee=9, id="ITEM_WEAPON_AXE_GREAT"), "WEAPON")
    assert not env.is_tool(t(skill_melee=2, id="ITEM_WEAPON_SWORD_SHORT"), "WEAPON")
    assert env.is_tool(lua.table_from({}), "WEAPON") and not env.is_tool(lua.table_from({}), "ARMOR")


# --- 9. the slow game's dump --------------------------------------------------------------------

def slow_props(level):
    s, m = BR.state(level)
    s["logistics"] = {"counts": {"items": PLANNER_CONFIG["fps_items_heavy"] + 1, "units": 500, "jobs": 10}}
    s["fps_low"] = 5
    s.setdefault("buildings", {})["zones"] = {}
    props = []
    _slow_game_rules(s, 30, dict(PLANNER_CONFIG), props, [], m)
    return s, [p.rule for p in props]


@test("9. a slow fort at Rules store or melt still gets the old garbage dump; at dump or destroy _disposal_rules places it")
def _():
    for level, old_rule in (("store", True), ("melt", True), ("dump", False), ("destroy", False)):
        s, rules = slow_props(level)
        assert ("dump" in rules) == old_rule, (level, rules)
        assert disposal_places_dump(s) == (not old_rule), level
    s, rules = slow_props("store")
    del s["disposal"]
    assert not disposal_places_dump(s)


# --- 10. the Rules widgets ---------------------------------------------------------------------

@test("10. the disposal widgets end at column 110 or before (they ended at 118 of a ~120-wide inside)")
def _():
    part = GUI[GUI.index("-- (0.105.27) forbidden items and junk"):GUI.index("-- (0.105.0) the squads hide")]
    frames = re.findall(r"frame = \{t = t \+ (\d+), l = (\d+), w = (\d+)\}", part)
    assert len(frames) == 3, frames
    for t, l, w in frames:
        assert int(l) >= 56 and int(l) + int(w) <= 110, (t, l, w)
    labels = re.findall(r"label = '([^']*)',\n\s*label_width = (\d+)", part)
    settings = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    names = re.search(r"DISPOSAL_NAMES = \{(.*?)\}", settings, re.S).group(1)
    longest = max(len(n) for n in re.findall(r"'([^']*)'", names))
    for (text, width), (_, _, w) in zip(labels, frames):
        assert len(text) < int(width) and int(width) + max(longest, 3) <= int(w), (text, width, w, longest)


# --- 11. never unforbid the dump's --------------------------------------------------------------

@test("11. unforbid_items: 'dumped' (or 'ai') refused by the bridge and by ai-disposal itself")
def _():
    assert "dumped" not in lua_set(ACTS, "DISPOSAL_REASONS")
    lua, env, w = A.world()
    w.dump(50, 10, 10, 150)
    it = mk(lua, w, kind="PANTS", flags={"forbid": True}, pos=(11, 11, 150))
    for bad in (["dumped"], ["used_ammo", "dumped"], ["ai"]):
        r = env.unforbid_items(opts(lua, reasons=bad, player_items=True), False)
        assert not r.ok and r.rejected, dict(r)
    assert it.flags.forbid


@test("all the touched Lua compiles under Lua 5.3")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-util.lua", "ai-disposal.lua", "ai-census.lua", "ai-bridge-actions.lua",
                 "ai-builder-surface.lua", "ai-builder-cistern.lua", "gui/ai-overseer.lua"):
        ok = chk((LUA_DIR / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


if __name__ == "__main__":
    finish()
