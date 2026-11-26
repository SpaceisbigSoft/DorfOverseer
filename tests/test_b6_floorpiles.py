"""(layout B, group B6) lua/ai-builder-floorpiles.lua: a floor workshop's
piles, given and linked.

floor_pile_units (which pile rooms a workshops request gets) on the
builder's fake fort; floor_book_piles (a finished floor project's piles
booked as their shops' feeders and linked) against a stand-in ai-pile-links
that records its calls, and against the real ai-pile-links in the fake game
tests/test_r41_pile_links.py gives it; the survey's fixture of fort A (the
need: feeders unlinked, shops with no pile).

    python tests/test_b6_floorpiles.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish, code_has  # noqa: E402,F401
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_builder as TB  # noqa: E402
import test_r41_pile_links as R41  # noqa: E402

LUA, B = TB.LUA, TB.B
FIXTURE = ROOT / "tests" / "fixtures" / "live" / "A-levels.json"

# The game for floor_book_piles: dfhack.buildings.findAtTile, the stockpile
# list and a stand-in ai-pile-links (LINKABLE copied from the real one) and
# ai-overseer-settings, given to the builder's fake fort.
GAME = LUA.execute(r"""
local G = {piles = {}, buildings = {}, calls = {}, settings = {link_feeders = true}, linkable = {},
           links_raise = false, settings_raise = false, remember_false = false, link_answer = nil}
function G.reset()
    for k in pairs(G.piles) do G.piles[k] = nil end
    for k in pairs(G.buildings) do G.buildings[k] = nil end
    G.calls = {}
    G.settings = {link_feeders = true}
    G.links_raise, G.settings_raise, G.remember_false, G.link_answer = false, false, false, nil
end
function G.pile(id, x1, y1, x2, y2, z)
    table.insert(G.piles, {id = id, x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z})
end
-- a 3x3 building round its centre tile
function G.building(id, cx, cy, z, btype)
    table.insert(G.buildings, {id = id, x1 = cx - 1, y1 = cy - 1, x2 = cx + 1, y2 = cy + 1, z = z,
                               centerx = cx, centery = cy, btype = btype or 'Workshop',
                               getType = function(self) return self.btype end})
end
_G.df = {global = {world = {buildings = {other = {STOCKPILE = G.piles}}}},
         building_type = {Workshop = 'Workshop', Furnace = 'Furnace', Door = 'Door'}}
dfhack.buildings = {findAtTile = function(pos)
    for _, b in ipairs(G.buildings) do
        if b.z == pos.z and pos.x >= b.x1 and pos.x <= b.x2 and pos.y >= b.y1 and pos.y <= b.y2 then return b end
    end
end}
local links = {LINKABLE = G.linkable}
function links.remember_feeder(x, y, z, shop_id, kind, flag)
    if G.links_raise then error('pile links broke') end
    table.insert(G.calls, {fn = 'remember_feeder', x = x, y = y, z = z, shop_id = shop_id, kind = kind, flag = flag})
    if G.remember_false then return false end
    return true
end
function links.link_feeder(o, dry_run)
    if G.links_raise then error('pile links broke') end
    table.insert(G.calls, {fn = 'link_feeder', pile_id = o.pile_id, dry_run = dry_run,
                           links_only = o.links_only, unlink = o.unlink})
    return G.link_answer or {ok = true, pile_id = o.pile_id}
end
local real = reqscript
_G.reqscript = function(name)
    if name == 'ai-pile-links' then
        if G.links_raise == 'load' then error('no ai-pile-links') end
        return links
    elseif name == 'ai-overseer-settings' then
        if G.settings_raise then error('no settings') end
        return {load_settings = function() return G.settings end}
    end
    return real(name)
end
return G
""")
for _k in R41.world()[1].LINKABLE:
    GAME.linkable[_k] = True

SEAMS = {n: B[n] for n in ("floor_pile_links", "floor_settings", "floor_stockpiles", "floor_building_at")}


def _reset():
    GAME.reset()
    for n, f in SEAMS.items():
        B[n] = f


test = make_test(before=_reset)
T, py = R41.T, R41.py


def units(shops, hint=None, have=(), style=None):
    p = {"kind": "workshops", "shops": list(shops)}
    if style is not None:
        p["style"] = style
    has = LUA.eval("function(set) return function(flag) return set[flag] == true end end")(
        LUA.table_from({f: True for f in have}))
    return py(B.floor_pile_units(T(LUA, p), T(LUA, hint) if hint is not None else None, has)) or []


def flags(rows):
    return [r["flag"] for r in rows]


# The worked example's second project: the stair at (60, 60) on z 70, the
# stone pile's room x 73-77 y 53-57, the Masons' shop centred on (81, 55).
def project(piles, build, z=70):
    return T(LUA, {"id": 57, "kind": "workshops", "z": z, "phase": "done", "anchor": {"x": 60, "y": 60},
                   "area": {"x1": 72, "y1": 52, "x2": 84, "y2": 58, "z": z},
                   "cells": {"build": build},
                   "floor": {"id": 3, "slots": 2, "hall": 13, "piles": piles}})


def masons_project(**row):
    GAME.pile(900, 73, 53, 77, 57, 70)
    GAME.building(910, 81, 55, 70)
    r = {"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}
    r.update(row)
    return project([r], [{"x": 21, "y": -5, "text": "wm"}])


def calls(fn=None):
    out = [py(c) for c in GAME.calls.values()]
    return [c for c in out if fn is None or c["fn"] == fn]


# --- 1 ---------------------------------------------------------------------------

@test("units: Masons -> one stone feeder (5 wide, not an output); Kitchen, Still and Craftsdwarfs each get theirs")
def _():
    assert units(["Masons"]) == [{"flag": "stone", "shop": "Masons", "room_size": 5, "output": False}]
    assert units(["Kitchen"]) == [{"flag": "food", "shop": "Kitchen", "room_size": 5, "output": False}]
    assert units(["Still"]) == [{"flag": "food", "shop": "Still", "room_size": 5, "output": False}]
    assert units(["Craftsdwarfs"]) == [{"flag": "stone", "shop": "Craftsdwarfs", "room_size": 5, "output": False}]


@test("units: Kitchen + Still in one request -> one food pile (the first shop's); Jewelers (no FEEDERS row) -> none")
def _():
    rows = units(["Kitchen", "Still"], {"piles_new": 3})
    assert flags(rows) == ["food"] and rows[0]["shop"] == "Kitchen", rows
    assert units(["Jewelers"]) == []
    assert units(["Jewelers", "Mechanics"], {"piles_new": 3}) == []


@test("units: every row's flag is a layouts.STOCKPILES name and its shop a layouts.WORKSHOPS name, for every shop "
      "the AI may place; a name the layout drops (unknown, the Depot) gets nothing")
def _():
    piles, shops = set(B.layouts.STOCKPILES.keys()), list(B.layouts.WORKSHOPS.keys())
    for shop in shops:
        rows = units([shop], {"piles_new": 3})
        assert len(rows) <= 2, (shop, rows)
        for r in rows:
            assert r["flag"] in piles and r["shop"] == shop and r["room_size"] == 5, (shop, r)
        assert len(set(flags(rows))) == len(rows), (shop, rows)
        feeder = B.FEEDERS[shop]
        # (0.105.125 item5) the screw press's sheet feeder is placed beside the shop by feeder_pile,
        # never in a floor plan: 'sheet' is not a layouts.STOCKPILES room kind, so its floor gets none
        if feeder is not None and feeder.flag not in piles:
            assert rows == [], (shop, rows)
        elif feeder is not None:
            assert rows and rows[0]["flag"] == feeder.flag and rows[0]["output"] is False, (shop, rows)
    for out_shop, flag in B.FLOOR_OUTPUTS.items():
        assert flag in piles and out_shop in shops, (out_shop, flag)
    assert units(["Depot"], {"piles_new": 3}) == [] and units(["NoSuchShop", 7], {"piles_new": 3}) == []
    assert flags(units(["Depot", "Masons"])) == ["stone"]


# --- 2 ---------------------------------------------------------------------------

@test("units: has_flag('stone') -> no stone feeder; piles_new 0 -> none; 2 with Masons -> stone then furniture; "
      "3 with Masons and Smelter -> stone, furniture, bars")
def _():
    # (no feeder needed: the budget is free for the shop's output pile, as the brief's order has it)
    assert flags(units(["Masons"], have=["stone"])) == ["furniture"]
    assert units(["Masons"], have=["stone"])[0]["output"] is True
    assert units(["Masons"], have=["stone", "furniture"]) == []
    assert units(["Jewelers", "Masons"], have=["stone", "furniture"]) == []
    assert flags(units(["Masons", "Carpenters"], have=["stone"])) == ["wood"]
    assert units(["Masons"], {"piles_new": 0}) == []
    rows = units(["Masons"], {"piles_new": 2})
    assert flags(rows) == ["stone", "furniture"] and [r["output"] for r in rows] == [False, True], rows
    rows = units(["Masons", "Smelter"], {"piles_new": 3})
    assert flags(rows) == ["stone", "furniture", "bars_blocks"], rows
    assert [r["shop"] for r in rows] == ["Masons", "Masons", "Smelter"], rows
    assert [r["output"] for r in rows] == [False, True, True], rows


@test("units: feeders before outputs and the budget holds; an output flag already listed as a feeder is skipped; "
      "an output the floor already has is skipped; piles_new past 3 is 3, junk is the default 1")
def _():
    rows = units(["Masons", "Carpenters", "Kitchen", "Loom"], {"piles_new": 3})
    assert flags(rows) == ["stone", "wood", "food"] and all(r["output"] is False for r in rows), rows
    assert flags(units(["Masons", "Carpenters"], {"piles_new": 3})) == ["stone", "wood", "furniture"]
    assert flags(units(["Loom"], {"piles_new": 3})) == ["cloth"]            # its output is cloth too
    assert flags(units(["Kitchen", "Still", "Butchers"], {"piles_new": 3})) == ["food"]
    assert flags(units(["Butchers"], {"piles_new": 3})) == ["food"] and units(["Butchers"])[0]["output"] is True
    assert flags(units(["Masons"], {"piles_new": 3}, have=["furniture"])) == ["stone"]
    assert len(units(["Masons", "Carpenters", "Kitchen", "Loom", "Leatherworks"], {"piles_new": 9})) == 3
    assert len(units(["Masons", "Carpenters"], {"piles_new": -4})) == 0
    for junk in ("many", 1.5, True, {"n": 2}):
        assert flags(units(["Masons", "Carpenters"], {"piles_new": junk})) == ["stone"], junk
    assert flags(units(["Masons", "Carpenters"], {})) == ["stone"]
    assert flags(units(["Masons", "Carpenters"])) == ["stone"]              # no hint at all


@test("units: room_size = pile_w clamped to 5-11 (3 -> 5, 20 -> 11, 7 -> 7, none or junk -> 5)")
def _():
    for w, want in ((3, 5), (20, 11), (7, 7), (5, 5), (11, 11), (None, 5), ("wide", 5), (6.5, 5)):
        hint = {"piles_new": 2} if w is None else {"piles_new": 2, "pile_w": w}
        rows = units(["Masons"], hint)
        assert [r["room_size"] for r in rows] == [want, want], (w, rows)
        # floor_site's storage room is made from the row
        L = B.layouts.make("storage", T(LUA, {"piles": [rows[0]["flag"]], "room_size": rows[0]["room_size"]}))
        L = L[0] if isinstance(L, tuple) else L
        assert L is not None and L.summary.room_size == want, w


# --- 3 ---------------------------------------------------------------------------

@test("units: the ore_piles custom (a list as the brain sends it, or a set) -> no stone feeder, the others stay")
def _():
    for customs in (["ore_piles"], ["cloister", "ore_piles"], {"ore_piles": True}):
        style = {"customs": customs}
        for shops in (["Masons"], ["Craftsdwarfs", "Smelter"], ["Masons", "Carpenters"]):
            assert "stone" not in flags(units(shops, {"piles_new": 3}, style=style)), (customs, shops)
        assert flags(units(["Masons"], style=style)) == ["furniture"], customs        # the budget goes on
        assert flags(units(["Masons", "Carpenters"], style=style)) == ["wood"], customs
        assert flags(units(["Masons", "Carpenters"], {"piles_new": 3}, style=style)) == ["wood", "furniture"], customs
        assert units(["Masons"], style=style, have=["furniture"]) == [], customs
    assert flags(units(["Masons"], style={"customs": ["armoury"]})) == ["stone"]
    assert flags(units(["Masons"], style={"customs": "ore_piles"})) == ["stone"]      # junk customs: none


# --- 4 ---------------------------------------------------------------------------

@test("units: junk params and hints -> {} (never raises); a has_flag that raises or is no function counts as no pile")
def _():
    empty = lambda v: v is not None and len(list(v.keys())) == 0       # noqa: E731
    f = B.floor_pile_units
    for junk in (None, 7, "workshops", True, LUA.table(), T(LUA, {"shops": "Masons"}), T(LUA, {"shops": 3}),
                 T(LUA, {"shops": []}), T(LUA, {"shops": [1, True, {"a": 1}]}), T(LUA, {"kind": "workshops"})):
        for hint in (None, 7, "x", T(LUA, {"piles_new": "x", "pile_w": {"a": 1}}), LUA.table()):
            assert empty(f(junk, hint, None)), (junk, hint)
            assert empty(f(junk, hint, "not a function")), (junk, hint)
    good = T(LUA, {"shops": ["Masons"], "style": 5})
    for hint in (7, "x", True):                       # a hint that is no table: the defaults
        assert flags(py(f(good, hint, None))) == ["stone"], hint
    assert flags(py(f(good, None, "not a function"))) == ["stone"]
    assert flags(py(f(good, None, LUA.eval("function() error('boom') end")))) == ["stone"]
    assert empty(f(T(LUA, {"shops": ["Masons"]}), T(LUA, {"piles_new": 0}), None))
    assert empty(f())


# --- 5 ---------------------------------------------------------------------------

@test("book: a finished project with a stone pile and a Masons shop: remember_feeder with map coordinates, the shop's "
      "building id, 'Masons', 'stone'; link_feeder with the pile's id, not a dry run")
def _():
    booked, linked = B.floor_book_piles(masons_project())
    assert (booked, linked) == (1, 1)
    assert calls() == [
        {"fn": "remember_feeder", "x": 73, "y": 53, "z": 70, "shop_id": 910, "kind": "Masons", "flag": "stone"},
        {"fn": "link_feeder", "pile_id": 900, "dry_run": False}], calls()


@test("book: a row's tile anywhere in the pile's room finds the pile, and it is booked by its corner (ai-pile-links "
      "finds a pile by its corner); a workshop still planned is found the same")
def _():
    booked, linked = B.floor_book_piles(masons_project(x=15, y=-5))
    assert (booked, linked) == (1, 1)
    c = calls("remember_feeder")[0]
    assert (c["x"], c["y"], c["z"], c["shop_id"]) == (73, 53, 70, 910), c


@test("book: a Kitchen's food pile: booked, not linked (not one of LINKABLE)")
def _():
    GAME.pile(901, 73, 53, 77, 57, 70)
    GAME.building(911, 81, 55, 70)
    p = project([{"x": 13, "y": -7, "flag": "food", "shop": "Kitchen"}], [{"x": 21, "y": -5, "text": "wz"}])
    assert B.floor_book_piles(p) == (1, 0)
    assert calls() == [{"fn": "remember_feeder", "x": 73, "y": 53, "z": 70, "shop_id": 911, "kind": "Kitchen",
                        "flag": "food"}], calls()


@test("book: link_feeders = false -> booked, not linked; settings that can't be read -> booked, not linked; "
      "a link the module refuses is not counted")
def _():
    GAME.settings.link_feeders = False
    assert B.floor_book_piles(masons_project()) == (1, 0)
    assert [c["fn"] for c in calls()] == ["remember_feeder"]
    _reset()
    GAME.settings_raise = True
    assert B.floor_book_piles(masons_project()) == (1, 0)
    assert [c["fn"] for c in calls()] == ["remember_feeder"]
    _reset()
    GAME.settings = LUA.table()                        # an older settings record without the switch: on
    assert B.floor_book_piles(masons_project()) == (1, 1)
    _reset()
    GAME.link_answer = T(LUA, {"ok": False, "rejected": True, "error": "the workshop is the player's"})
    assert B.floor_book_piles(masons_project()) == (1, 0)
    assert [c["fn"] for c in calls()] == ["remember_feeder", "link_feeder"]


@test("book: a pile whose stockpile is gone, a shop that was never placed, a shop name with no build cell, a pile on "
      "another level: skipped (nothing booked, nothing linked)")
def _():
    p = masons_project()
    GAME.piles[1] = None
    assert B.floor_book_piles(p) == (0, 0) and calls() == []
    _reset()
    p = masons_project()
    GAME.buildings[1] = None
    assert B.floor_book_piles(p) == (0, 0) and calls() == []
    _reset()
    assert B.floor_book_piles(masons_project(shop="Carpenters", flag="wood")) == (0, 0) and calls() == []
    _reset()
    p = masons_project()
    GAME.piles[1].z = 71
    assert B.floor_book_piles(p) == (0, 0) and calls() == []
    _reset()
    p = masons_project()                               # a door on the build cell is no workshop
    GAME.buildings[1].btype = "Door"
    assert B.floor_book_piles(p) == (0, 0) and calls() == []
    _reset()
    GAME.remember_false = True                         # ai-pile-links found no pile at the corner
    assert B.floor_book_piles(masons_project()) == (0, 0)
    assert [c["fn"] for c in calls()] == ["remember_feeder"]


@test("book: output piles are not booked: a row marked output, and a row whose flag is not its shop's feeder flag")
def _():
    GAME.pile(900, 73, 53, 77, 57, 70)
    GAME.pile(902, 67, 53, 71, 57, 70)
    GAME.building(910, 81, 55, 70)
    rows = [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"},
            {"x": 7, "y": -7, "flag": "furniture", "shop": "Masons"}]
    assert B.floor_book_piles(project(rows, [{"x": 21, "y": -5, "text": "wm"}])) == (1, 1)
    assert [c.get("pile_id") for c in calls("link_feeder")] == [900]
    _reset()
    assert B.floor_book_piles(masons_project(output=True)) == (0, 0) and calls() == []
    _reset()
    assert B.floor_book_piles(masons_project(shop="Jewelers")) == (0, 0) and calls() == []


@test("book: two piles and two shops: each pile with its own shop; two shops of one kind: the pile's nearest")
def _():
    GAME.pile(900, 73, 53, 77, 57, 70)                 # stone
    GAME.pile(903, 67, 53, 71, 57, 70)                 # wood
    GAME.building(910, 81, 55, 70)                     # Masons
    GAME.building(912, 87, 55, 70)                     # Carpenters
    rows = [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"},
            {"x": 7, "y": -7, "flag": "wood", "shop": "Carpenters"}]
    build = [{"x": 21, "y": -5, "text": "wm"}, {"x": 27, "y": -5, "text": "wc"}, {"x": 5, "y": 5, "text": "t"}]
    assert B.floor_book_piles(project(rows, build)) == (2, 2)
    got = {(c["kind"], c["flag"], c["shop_id"], c["x"]) for c in calls("remember_feeder")}
    assert got == {("Masons", "stone", 910, 73), ("Carpenters", "wood", 912, 67)}, got
    assert sorted(c["pile_id"] for c in calls("link_feeder")) == [900, 903]
    _reset()
    GAME.pile(900, 73, 53, 77, 57, 70)
    GAME.building(913, 93, 55, 70)                     # the far Masons, listed first
    GAME.building(910, 81, 55, 70)
    build = [{"x": 33, "y": -5, "text": "wm"}, {"x": 21, "y": -5, "text": "wm"}]
    assert B.floor_book_piles(project([rows[0]], build)) == (1, 1)
    assert calls("remember_feeder")[0]["shop_id"] == 910


@test("book: ai-pile-links raising (on a call, or as it loads): nothing propagates, 0, 0; one broken row does not "
      "stop the next")
def _():
    GAME.links_raise = True
    assert B.floor_book_piles(masons_project()) == (0, 0)
    _reset()
    GAME.links_raise = "load"
    assert B.floor_book_piles(masons_project()) == (0, 0) and calls() == []
    _reset()
    GAME.pile(900, 73, 53, 77, 57, 70)
    GAME.building(910, 81, 55, 70)
    rows = [7, {"x": "a", "y": -7, "flag": "stone", "shop": "Masons"}, {"flag": "stone", "shop": "Masons"},
            {"x": 13, "y": -7, "flag": "stone", "shop": 5}, {"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}]
    assert B.floor_book_piles(project(rows, [{"x": 21, "y": -5, "text": "wm"}])) == (1, 1)
    _reset()
    B.floor_building_at = LUA.eval("function() error('no buildings') end")
    assert B.floor_book_piles(masons_project()) == (0, 0)
    _reset()
    B.floor_stockpiles = LUA.eval("function() error('no world') end")
    assert B.floor_book_piles(masons_project()) == (0, 0)


@test("book: a project without floor.piles (a classic level, an older record), and junk: 0, 0, nothing called")
def _():
    GAME.pile(900, 73, 53, 77, 57, 70)
    GAME.building(910, 81, 55, 70)
    for p in (None, 7, "p", LUA.table(), T(LUA, {"z": 70, "anchor": {"x": 60, "y": 60}}),
              T(LUA, {"z": 70, "anchor": {"x": 60, "y": 60}, "floor": {"id": 3, "slots": 2, "hall": 13}}),
              T(LUA, {"z": 70, "anchor": {"x": 60, "y": 60}, "floor": {"piles": "stone"}}),
              T(LUA, {"z": 70, "floor": {"piles": [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}]}}),
              T(LUA, {"anchor": {"x": 60, "y": 60},
                      "floor": {"piles": [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}]}})):
        assert B.floor_book_piles(p) == (0, 0), p
    assert calls() == []
    # an older record anchored on its stair (anchor_of)
    p = T(LUA, {"z": 70, "stair": {"x": 60, "y": 60}, "cells": {"build": [{"x": 21, "y": -5, "text": "wm"}]},
                "floor": {"piles": [{"x": 13, "y": -7, "flag": "stone", "shop": "Masons"}]}})
    assert B.floor_book_piles(p) == (1, 1)


# --- the real ai-pile-links ---------------------------------------------------------

def real_links(shop_kind, flag, btype="Workshop", areas=True):
    """The real ai-pile-links in test_r41's fake game, in the builder's Lua engine, with a pile room and a shop as
    the worked example places them; the AI's levels are the builder's own level_areas() of the saved project."""
    env, w = LUA.execute(R41.FAKE, module_src("ai-pile-links.lua"))
    settings = {"stone": flag == "stone", "wood": flag == "wood"}
    settings[flag] = True
    pile = w.pile(T(LUA, {"x1": 73, "y1": 53, "x2": 77, "y2": 57, "z": 70, "settings": {"flags": settings}}))
    shop = w.shop(T(LUA, {"x1": 80, "y1": 54, "z": 70, "type": shop_kind, "btype": btype}))
    B.floor_pile_links = lambda: env
    B.floor_stockpiles = lambda: w.piles
    B.floor_building_at = LUA.eval("""function(shops) return function(x, y, z)
        for _, b in ipairs(shops) do
            if b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 then return b end
        end
    end end""")(w.shops)
    p = project([{"x": 13, "y": -7, "flag": flag, "shop": shop_kind}],
                [{"x": 21, "y": -5, "text": B.layouts.WORKSHOPS[shop_kind]}])
    if areas:
        data = B.load_projects()
        data.list[len(data.list) + 1] = p
        B.save_projects(data)
        env.ai_areas = B.level_areas
    return env, w, pile, shop, p


@test("real ai-pile-links: a floor project's stone pile is booked in its registry and linked to the Masons on both "
      "sides: its 'workshop stands in an AI level' test passes on the finished project's own area")
def _():
    TB.W.reset()
    env, w, pile, shop, p = real_links("Masons", "stone")
    assert B.floor_book_piles(p) == (1, 1)
    f = py(env.registry())["feeders"]
    assert len(f) == 1 and f[0]["id"] == pile.id and f[0]["shop"] == shop.id, f
    assert (f[0]["kind"], f[0]["flag"], f[0]["x"], f[0]["y"], f[0]["z"], f[0]["linked"]) == \
        ("Masons", "stone", 73, 53, 70, True), f
    assert py(w.list(shop.profile.links.take_from_pile)) == [pile.id]
    assert py(w.list(pile.links.give_to_workshop)) == [shop.id]
    assert pile.stockpile_flag.use_links_only is False        # it still takes loose stone
    rep = py(env.report())
    assert rep["feeders_ai"] == 1 and rep["unlinked"] == 0 and rep["feeders"][0]["linked"] is True, rep["feeders"]
    assert B.floor_book_piles(p) == (1, 0)                    # asked again: booked already, linked already


@test("real ai-pile-links: every LINKABLE kind is linked from a floor project (a WoodFurnace is a furnace); a "
      "Kitchen, a Still and a Craftsdwarfs are booked and left unlinked ('kind')")
def _():
    linkable = sorted(R41.world()[1].LINKABLE)
    assert linkable == ["Carpenters", "Clothiers", "Leatherworks", "Loom", "Masons", "WoodFurnace"], linkable
    for kind in linkable:
        TB.W.reset()
        flag = B.FEEDERS[kind].flag
        env, w, pile, shop, p = real_links(kind, flag, "Furnace" if kind == "WoodFurnace" else "Workshop")
        assert B.floor_book_piles(p) == (1, 1), kind
        assert py(w.list(shop.profile.links.take_from_pile)) == [pile.id], kind
    for kind in ("Kitchen", "Still", "Craftsdwarfs"):
        TB.W.reset()
        env, w, pile, shop, p = real_links(kind, B.FEEDERS[kind].flag)
        assert B.floor_book_piles(p) == (1, 0), kind
        row = py(env.report())["feeders"][0]
        assert row["linked"] is False and row["why"] == "kind" and row["kind"] == kind, row


@test("real ai-pile-links: a workshop outside every AI level is booked and not linked (its own refusal holds); a "
      "workshop the player linked is left alone")
def _():
    TB.W.reset()
    env, w, pile, shop, p = real_links("Masons", "stone", areas=False)          # W.areas: none
    assert B.floor_book_piles(p) == (1, 0)
    assert py(env.report())["feeders"][0]["why"] == "players_workshop"
    assert not py(w.list(shop.profile.links.take_from_pile))
    TB.W.reset()
    env, w, pile, shop, p = real_links("Masons", "stone")
    other = w.pile(T(LUA, {"x1": 90, "y1": 53, "x2": 92, "y2": 55, "z": 70}))
    shop.profile.links.take_from_pile.insert(shop.profile.links.take_from_pile, 0, other)
    assert B.floor_book_piles(p) == (1, 0)
    assert py(w.list(shop.profile.links.take_from_pile)) == [other.id]


# --- 6 ---------------------------------------------------------------------------

@test("fixture (fort A, the survey): its AI feeders are all unlinked and its Kitchen, Still and Craftsdwarfs have no "
      "feeder; on a floor each of those kinds is given a pile, and the LINKABLE ones are linked")
def _():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert d["feeders_ai"] == 11 and d["feeders_unlinked"] == 11            # the need: none linked
    by_kind: dict[str, list] = {}
    for s in d["shops"]:
        by_kind.setdefault(s["kind"], []).append(s)
    with_pile = {k for k, v in by_kind.items() if any(s.get("pile") for s in v)}
    unlinked = {k for k, v in by_kind.items() if any(s.get("pile") and not s["pile"]["linked"] for s in v)}
    no_pile = {k for k, v in by_kind.items() if any(not s.get("pile") for s in v)}
    assert no_pile == {"Kitchen", "Still", "Craftsdwarfs"}, no_pile
    assert sum(1 for s in d["shops"] if not s.get("pile")) == 3
    linkable = set(GAME.linkable.keys())
    want_linked = {"Masons", "Carpenters", "WoodFurnace", "Loom", "Clothiers", "Leatherworks"}
    assert want_linked <= unlinked and want_linked == linkable & with_pile, (unlinked, with_pile)
    # given: a pile for each shop kind of the fort that the AI may place on a workshops level
    for kind in sorted(by_kind):
        if B.layouts.WORKSHOPS[kind] is None:
            assert kind == "Depot", kind                 # the depot is no workshops-level shop
            continue
        rows = units([kind])
        assert len(rows) == 1 and rows[0]["flag"] == B.FEEDERS[kind].flag and rows[0]["output"] is False, (kind, rows)
        # the pile's flag is the one the survey found beside that shop, where it had one
        for s in by_kind[kind]:
            if s.get("pile"):
                assert s["pile"]["flag"] == rows[0]["flag"], (kind, s["pile"])
    for kind in ("Kitchen", "Still", "Craftsdwarfs"):
        assert len(units([kind])) == 1, kind
    # linked: the finished project books each and links the LINKABLE ones
    for kind in sorted(by_kind):
        if B.layouts.WORKSHOPS[kind] is None:
            continue
        _reset()
        row = units([kind])[0]
        GAME.pile(900, 73, 53, 77, 57, 70)
        GAME.building(910, 81, 55, 70, "Furnace" if kind in ("WoodFurnace", "Smelter") else "Workshop")
        p = project([{"x": 13, "y": -7, "flag": row["flag"], "shop": row["shop"]}],
                    [{"x": 21, "y": -5, "text": B.layouts.WORKSHOPS[kind]}])
        want = (1, 1) if kind in want_linked else (1, 0)
        assert B.floor_book_piles(p) == want, (kind, want)
        c = calls("remember_feeder")[0]
        assert (c["kind"], c["flag"], c["shop_id"]) == (kind, row["flag"], 910), c


# --- 7 ---------------------------------------------------------------------------

@test("the part: in PARTS (last, after 'court'), marked with the bridge's version, its names the builder's own, and "
      "nothing fetched while it loads (the fake fort raises for any module but ai-layouts and quickfort)")
def _():
    parts = list(B.PARTS.values())
    assert "floorpiles" in parts and parts.index("floorpiles") > parts.index("court"), parts
    assert B.PART_VERSIONS["ai-builder-floorpiles"] == B.PART_VERSIONS["ai-builder"]   # (bumped together)
    for name in ("floor_pile_units", "floor_book_piles", "FLOOR_OUTPUTS"):
        assert B[name] is not None, name
    lua2, b2, _w = TB.boot()                            # a fresh engine: only ai-layouts and quickfort known
    assert b2.floor_book_piles(b2.load_projects()) == (0, 0)
    p = lua2.eval("{z = 70, anchor = {x = 60, y = 60}, floor = {piles = {{x = 1, y = 1, flag = 'stone', "
                  "shop = 'Masons'}}}}")
    assert b2.floor_book_piles(p) == (0, 0)             # no ai-pile-links there: nothing propagates
    assert len(list(b2.floor_pile_units(lua2.eval("{shops = {'Masons'}}"), None, None).values())) == 1
    src = (ROOT / "lua" / "ai-builder-floorpiles.lua").read_text(encoding="utf-8")
    top = [ln for ln in src.splitlines() if "reqscript(" in ln and not ln.lstrip().startswith("--")]
    assert all(ln.startswith("function floor_") for ln in top), top


@test("FLOOR_OUTPUTS: the brief's table, exactly")
def _():
    want = {"Masons": "furniture", "Carpenters": "furniture", "Craftsdwarfs": "finished_goods",
            "Clothiers": "finished_goods", "Leatherworks": "finished_goods", "Smelter": "bars_blocks",
            "WoodFurnace": "bars_blocks", "Ashery": "bars_blocks", "SoapMaker": "bars_blocks", "Kitchen": "food",
            "Still": "food", "Butchers": "food", "Fishery": "food", "Quern": "food", "Millstone": "food",
            "Tanners": "leather", "Loom": "cloth"}
    assert dict(B.FLOOR_OUTPUTS.items()) == want


if __name__ == "__main__":
    finish()
