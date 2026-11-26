"""(r2h7) Round 2, group h7: the rules refused every time.

  1. seal_cavern: 0 of 24 in R3 (A, B, C). The planner counted the cavern
     well's door and hatch as lockable, the bridge refused them ("no door or
     hatch on the way down to lock", later "only cavern well doors on the
     way down, left open"). Now one test, ai-threats seal_lockable, used by
     the openings report (each row's `lockable`, which the brain counts) and
     by seal_cavern itself; a refusal for want of anything lockable carries
     `nothing_lockable` and isn't asked again while its back-off runs; a
     fort whose only way down is the cavern well is told so, not refused; a
     real cavern door with a beast below is locked.
  2. place_siege_shop: 0 of 64 ("no free 7x7 of roofed floor within 15
     tiles of that entrance"; A 42, D 40, E 21 in the 15-16 Nov run). A
     siege workshop is 5x5 and need not stand by the gate: anywhere in the
     fort, a 5x5 of free floor whose ring is wall or free floor in one run
     (a workshop level's empty room will do; a corridor never).
  3. stuck_sweep -> finish_project: 71 of 71 refused "N buildings still
     waiting", the same levels for up to 146 days (15-16 Nov: C project 70,
     a dining level 0 of 16; temples 54, 68 at 4 of 8, 3 of 7). The sweep's
     give-up now closes the level with its waiting pieces left planned
     (leave_planned); a well level is left to the well rule.
  4. hunts: `hunt_send` 0 in six forts: a lone thief's alarm forbade them,
     and a hidden cavern beast was never a target. Now an alarm the AI
     raised for a lone sneaker already seen or gone (no thief inside, nothing
     else holding the alarm) lets hunting go on; a great danger unseen in a
     cavern is listed (hidden) and hunted only on a clearly better matchup;
     one behind the AI's seal is judged (a win: the seal's kill plan's).
  5. residency: a neutral fort (Outsiders between the stances) answered no
     petition to stay (E 30 waiting up to 78 days, F 10): declined after
     `r2h7_residency_neutral_days`.

    python tests/test_r2_h7.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner  # noqa: E402,F401
import planner_threats as pt  # noqa: E402
import planner_stuck as PST  # noqa: E402
import planner_hunt as PH  # noqa: E402
import planner_visitors as PV  # noqa: E402
from planner_core import Memory, Proposal, abs_tick, refusal_key, note_refusal, PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(pt.PLANNER_CONFIG)
DAY = 1200

# --- the live rows: B (R3 evidence state-last.json), Cavern1 z 123-146 -----------------
CAVERNS = [{"discovered": True, "name": "Cavern1", "open": False, "seen": 1997, "z_bottom": 123, "z_top": 146},
           {"discovered": False, "name": "Cavern2", "open": False, "seen": 0, "z_bottom": 114, "z_top": 118},
           {"discovered": False, "name": "Cavern3", "open": False, "seen": 0, "z_bottom": 19, "z_top": 23}]
WELL_SKIP = "cavern well 13: its shaft gate keeps the cavern out (open); the door would cut the well off"
BEAST = {"id": 50, "name": "Shedim, Forgotten Beast", "kind": "forgotten beast", "layer": "Cavern1"}


def need_lua():
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")


def py(v):
    if hasattr(v, "items"):
        d = dict(v.items())
        if d and all(isinstance(k, int) for k in d):
            return [py(d[k]) for k in sorted(d)]
        return {k: py(x) for k, x in d.items()}
    return v


THREATS_GAME = r"""
local src = ...
local G = {saved = {}, citizens = {}, tiles = {}, mods = {}, flags = {}, blocks = {}}
local e = setmetatable({G = G}, {__index = _G})
e.reqscript = function(n) return G.mods[n] end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local feats = {map_features = {}, feature_global_idx = {}}
e.df = {global = {cur_year = 1, cur_year_tick = 0, world = {features = feats}},
        building = {find = function(id) for _, b in pairs(G.tiles) do if b.id == id then return b end end end},
        building_type = {Door = 'Door', Hatch = 'Hatch', Wall = 'Wall'},
        feature_init_subterranean_from_layerst = {is_instance = function(_, f) return f.cavern == true end}}
e.dfhack = {persistent = {getSiteData = function(k, d) return G.saved[k] or d end,
                          saveSiteData = function(k, v) G.saved[k] = v end},
            units = {getReadableName = function(u) return u.name end, getCitizens = function() return G.citizens end},
            buildings = {findAtTile = function(p) return G.tiles[p.x .. ',' .. p.y .. ',' .. p.z] end},
            maps = {getTileFlags = function(x, y, z) return {} end, getTileBlock = function() return nil end},
            gui = {showAnnouncement = function() end}}
function G.bld(id, ty) return {id = id, jobs = {}, door_flags = {forbidden = false, closed = false},
    getType = function() return ty end, getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
assert(load(src, 'ai-threats', 't', e))()
return e
"""


def threats_rig():
    lua = LuaRuntime(unpack_returned_tuples=True)
    E = lua.execute(THREATS_GAME, module_src("ai-threats.lua"))
    return lua, E


def fort(rows):
    s = copy.deepcopy(BASE)
    s["map"]["elevation_offset"] = -129
    s["threats"] = {"sealed": {}, "openings": {"list": [dict(o) for o in rows], "n": len(rows)},
                    "cavern_citizens": {"list": [], "n": 0}}
    s["deep"] = {"caverns": copy.deepcopy(CAVERNS), "dangers": [dict(BEAST)], "cursed": []}
    s["civ_alert"], s["civ_alert_ready"] = False, True
    return s


def run_beasts(s, m):
    props, notes = [], []
    pt._cavern_beasts(s, CFG, m, s["threats"], pt.threat_rules_of(s), props, notes)
    return props, notes


def seals(props):
    return [p for p in props if p.rule == "seal_cavern" and not p.action.get("open")]


def bridge_rows(lua, E, setup):
    """The openings report of a fake fort (setup puts its openings and buildings in)."""
    d = E.load_state()
    setup(lua, E, d)
    E.reqscript("ai-util").site_put(E.STATE_KEY, d)
    return py(E.openings_report(E.load_state(), 0, None))["list"]


def r3_well(lua, E, d, blocked=None):
    """B's two openings: the cavern well's shaft hatch (z143) and its gallery door, which the
    seal leaves open (its shaft gate is linked), or with a dwarf beyond it."""
    G, t = E.G, lua.table_from
    G.tiles["131,129,143"] = G.bld(516, "Hatch")
    G.tiles["116,140,165"] = G.bld(173, "Door")
    G.mods["ai-well-safety"] = t({"door_blocked": lambda o, *a: blocked,
                                  "door_seal_skip": lambda o: WELL_SKIP if o.source == "cavern well 13 door" else None,
                                  "fort_doors": lambda: t({})})
    E.note_opening(d, 131, 129, 143, "well", "cavern well 13", 0)
    E.note_opening(d, 116, 140, 165, "gate", "cavern well 13 door", 0)


def cave_door(lua, E, d):
    """A door the gates' scan put on a cavern entrance (the way down that isn't a well)."""
    G = E.G
    G.tiles["140,150,147"] = G.bld(600, "Door")
    E.note_opening(d, 140, 150, 147, "gate", "cavern entrance 5", 0)


def lua_seal(E, lua):
    return py(E.seal_cavern("all caverns", lua.table_from({}), False, False, 19, 146, True))


# --- 1. the seal ------------------------------------------------------------------------

@test("1: B's rows (well hatch + well door left open): the bridge marks both unlockable, the planner asks "
      "no seal and says the well is the only way; the bridge would refuse with nothing_lockable")
def _():
    need_lua()
    lua, E = threats_rig()
    rows = bridge_rows(lua, E, lambda l, e, d: r3_well(l, e, d))
    assert [r["lockable"] for r in rows] == [False, False], rows
    door = next(r for r in rows if r["building"] == "Door")
    assert door["seal_skip"] == WELL_SKIP, door
    assert pt.seal_lockable_rows(rows) == []
    props, notes = run_beasts(fort(rows), Memory())
    assert not seals(props), [(p.action, p.reason) for p in seals(props)]
    assert any("only way down on record is the cavern well" in n for n in notes), notes
    r = lua_seal(E, lua)
    assert r["ok"] is False and r["nothing_lockable"] is True and r["well_kept"] == 1, r
    assert E.G.tiles["116,140,165"].door_flags.forbidden is False


@test("1: a dwarf beyond the well's door: unlockable (well_blocked), the seal waits (waiting, nothing_lockable)")
def _():
    need_lua()
    lua, E = threats_rig()
    rows = bridge_rows(lua, E, lambda l, e, d: r3_well(l, e, d, blocked="Morul"))
    door = next(r for r in rows if r["building"] == "Door")
    assert door["lockable"] is False and door["well_blocked"] == "Morul" and "seal_skip" not in door, door
    assert not seals(run_beasts(fort(rows), Memory())[0])
    r = lua_seal(E, lua)
    assert r.get("waiting") is True and r["nothing_lockable"] is True and "Morul" in r["error"], r


@test("1: a real cavern door and a beast below: the bridge marks it lockable, the planner asks, the seal "
      "locks it (sealing happens); the well's openings stay as they are")
def _():
    need_lua()
    lua, E = threats_rig()

    def setup(l, e, d):
        r3_well(l, e, d)
        cave_door(l, e, d)
    rows = bridge_rows(lua, E, setup)
    lk = pt.seal_lockable_rows(rows)
    assert [r["id"] for r in lk] == [600], rows
    props, _ = run_beasts(fort(rows), Memory())
    sp = seals(props)
    assert sp and sp[0].action["type"] == "seal_cavern" and sp[0].action.get("openings") is True, props
    assert "1 door(s) and hatch(es) on record, 1 open" in sp[0].reason, sp[0].reason
    r = py(E.seal_cavern("all caverns", lua.table_from({}), False, False, 19, 146, True))
    assert r["ok"] is True and r["locked"] == 1, r
    assert E.G.tiles["140,150,147"].door_flags.forbidden is True
    assert E.G.tiles["116,140,165"].door_flags.forbidden is False       # the well's door left open
    assert E.G.tiles["131,129,143"].door_flags.forbidden is False       # its shaft hatch: the watcher's
    # the next report says it is sealed: nothing left to ask
    rows = py(E.openings_report(E.load_state(), 0, None))["list"]
    s = fort(rows)
    s["threats"]["sealed"] = {"all caverns": {"days": 0}}
    assert not seals(run_beasts(s, Memory())[0])


@test("1: the planner and the bridge agree on every kind of opening (one test, seal_lockable)")
def _():
    need_lua()
    lua, E = threats_rig()
    G, t = E.G, lua.table_from
    G.tiles["10,10,150"] = G.bld(1, "Door")             # a cavern entrance door: lockable
    G.tiles["11,10,150"] = G.bld(2, "Hatch")            # a hatch on a way down: lockable
    G.tiles["12,10,150"] = G.bld(3, "Wall")             # something else stands there: not
    G.tiles["14,10,143"] = G.bld(5, "Hatch")            # a cavern well's shaft hatch: never
    G.tiles["15,10,150"] = G.bld(6, "Door")             # a well's door, skipped
    G.mods["ai-well-safety"] = t({"door_blocked": lambda o, *a: None,
                                  "door_seal_skip": lambda o: "kept" if o.x == 15 else None,
                                  "fort_doors": lambda: t({})})
    d = E.load_state()
    for x, kind, src in ((10, "gate", "cavern entrance 1"), (11, "way_down", "Cavern1"), (12, "gate", "x"),
                         (13, "open", "cavern entrance 2"), (15, "gate", "cavern well 9 door")):
        E.note_opening(d, x, 10, 150, kind, src, 0)
    E.note_opening(d, 14, 10, 143, "well", "cavern well 9", 0)
    E.reqscript("ai-util").site_put(E.STATE_KEY, d)
    rows = py(E.openings_report(E.load_state(), 0, None))["list"]
    by_x = {r["x"]: r for r in rows}
    want = {10: True, 11: True, 12: False, 13: False, 14: False, 15: False}
    assert {x: by_x[x]["lockable"] for x in want} == want, by_x
    assert {r["x"] for r in pt.seal_lockable_rows(rows)} == {10, 11}
    # the seal locks exactly those
    r = lua_seal(E, lua)
    assert r["ok"] and r["locked"] == 2, r
    assert [G.tiles[k].door_flags.forbidden for k in ("10,10,150", "11,10,150", "14,10,143", "15,10,150")] \
        == [True, True, False, False]
    # an older bridge's row (no `lockable`): judged as before
    old = [{"building": "Door", "kind": "gate", "x": 1, "y": 1, "z": 1},
           {"building": "Door", "kind": "gate", "seal_skip": "x", "x": 2, "y": 1, "z": 1},
           {"building": "Hatch", "kind": "well", "x": 3, "y": 1, "z": 1}]
    assert [o["x"] for o in pt.seal_lockable_rows(old)] == [1]


@test("1: a seal refused 'only cavern well doors on the way down, left open' isn't asked again while its "
      "back-off runs (R3 12:24-12:26 A, B: asked on)")
def _():
    rows = [{"building": "Door", "built": True, "closed": True, "id": 7, "kind": "gate", "locked": False,
             "source": "cavern entrance 1", "x": 140, "y": 150, "z": 147}]       # an older row: no lockable
    s = fort(rows)
    m = Memory()
    p = seals(run_beasts(s, m)[0])
    assert p, "asked once"
    note_refusal(m, p[0], {"ok": False, "rejected": True, "error": "only cavern well doors on the way down, left "
                                                                   "open: cavern well 55: its shaft gate keeps"},
                 abs_tick(s))
    assert pt._seal_refused_none(m, s)
    assert not seals(run_beasts(s, m)[0])


# --- 2. the siege workshop --------------------------------------------------------------

SIEGE_GAME = r"""
local src = ...
local W = {over = {}}
local e = setmetatable({W = W}, {__index = _G})
e.reqscript = function() return {} end
e.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
e.df = {global = {world = {buildings = {all = {}, other = {WORKSHOP_ANY = {}}}}}}
e.dfhack = {}
assert(load(src, 'ai-siege', 't', e))()
return e
"""


def siege_rig():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute(SIEGE_GAME, module_src("ai-siege.lua"))


def gkey(x, y, z):
    return (z * 4096 + y) * 4096 + x


def ascii_fort(lua, rows, z=150):
    """A level from text: '#' wall, '.' free floor (inside), 'o' a building on floor, '+' a door,
    'E' the gate's opening. Returns (entrance, inside, T)."""
    tiles, inside, e = {}, {}, None
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c == "#":
                tiles[(x, y)] = {"shape": "WALL", "walk": False}
            else:
                tiles[(x, y)] = {"shape": "FLOOR", "walk": True, "occupied": c in "o+"}
                inside[gkey(x, y, z)] = True
                if c == "E":
                    e = {"x": x, "y": y, "z": z, "inside_list": [gkey(x, y, z)]}
    T = lambda x, y, zz: lua.table_from(tiles[(x, y)]) if zz == z and (x, y) in tiles else None  # noqa: E731
    ent = lua.table_from({k: (lua.table_from(v) if isinstance(v, list) else v) for k, v in e.items()})
    return ent, lua.table_from(inside), T


# A's entrance: a stair down into a 3-wide gatehouse and a corridor; a dining hall
# full of tables; one empty 5x5 room of a workshop level, its 3-wide door onto a corridor
A_LEVEL = [
    "##################################",
    "#############E####################",
    "############...###################",
    "############...###################",
    "############...###################",
    "#.................................#",
    "#.................................#",
    "#.................................#",
    "#####.#############.####...########",
    "#o.o.o.o#########.....##.....######",
    "#.o.o.o.#########.....##.....######",
    "#o.o.o.o#########.....##.....######",
    "#.o.o.o.#########.....##.....######",
    "#o.o.o.o#########.....##.....######",
    "##################################",
]


@test("2: A's gate has no 7x7 beside it (the old test refuses, as in the run); the workshop goes in the "
      "nearest free 5x5 whose ring is one run: the empty workshop room, never the 5-wide corridor")
def _():
    need_lua()
    lua, S = siege_rig()
    e, inside, T = ascii_fort(lua, A_LEVEL)
    assert S.shop_spot(e, inside, T) is None                      # the run's refusal, every time
    sp = py(S.shop_spot_anywhere(e, inside, T))
    # the two rooms at x 17-21 (opens 1 wide at x 19) and x 24-28 (3 wide at x 24-26): both one run;
    # the corridor (y 5-7, 3 high) is no 5x5; the dining hall is full of tables
    assert sp and sp["z"] == 150 and sp["y"] == 11 and sp["x"] in (19, 26), sp
    # a 5-wide corridor joining two stairs: never (its open sides are two runs); its dead end would do
    corr = ["#####################",
            "#E#################.#",
            "#.#################.#",
            "#...................#",
            "#...................#",
            "#...................#",
            "#...................#",
            "#...................#",
            "#####################"]
    e2, in2, T2 = ascii_fort(lua, corr)
    assert S.shop_spot_anywhere(e2, in2, T2) is None
    # a room off the stair, one wider than the workshop: the side away from the stair
    dead2 = ["###########",
             "#E#########",
             "#.#########",
             "#......####",
             "#......####",
             "#......####",
             "#......####",
             "#......####",
             "###########"]
    e4, in4, T4 = ascii_fort(lua, dead2)
    sp4 = py(S.shop_spot_anywhere(e4, in4, T4))
    assert sp4 and (sp4["x"], sp4["y"]) in ((4, 5),), sp4


@test("2: place_shop: falls back to the fort-wide spot, says so (by_gate absent); none anywhere: refused with "
      "the real reason, not '7x7 within 15 tiles'")
def _():
    need_lua()
    lua, S = siege_rig()
    e, inside, T = ascii_fort(lua, A_LEVEL)
    placed = []
    S.shop_count = lambda: 0
    src = module_src("ai-siege.lua")
    assert "SHOP_SCAN_MAX" in src and "error = ('no free 7x7" not in src

    def world(e_, in_, T_):
        e_.id = 1
        mods = {"ai-gates": lua.table_from({"GATES": lua.table_from({"entrances": lua.table_from([e_]),
                                                                       "inside": in_})}),
                "ai-builder": lua.table_from({"qf_try": lambda *a: (placed.append(a) or True)})}
        S.reqscript = lambda n: mods.get(n)
        S.tile = T_
    world(e, inside, T)
    r = py(S.place_shop(1, True))
    assert r["ok"] is True and r["at"]["y"] == 11 and "by_gate" not in r and placed, r
    closed = ["#####", "#E###", "#####"]
    e2, in2, T2 = ascii_fort(lua, closed)
    world(e2, in2, T2)
    r = py(S.place_shop(1, True))
    assert r["rejected"] and "no free 5x5" in r["error"], r


@test("2 (item27): place_mood_shop: a mood's smelter on the fort-wide free spot (no level), its quickfort key; "
      "an unknown kind or one placed and unbuilt: refused")
def _():
    need_lua()
    lua, S = siege_rig()
    e, inside, T = ascii_fort(lua, A_LEVEL)
    placed = []
    e.id = 1
    mods = {"ai-gates": lua.table_from({"GATES": lua.table_from({"entrances": lua.table_from([e]), "inside": inside})}),
            "ai-builder": lua.table_from({"qf_try": lambda *a: (placed.append(a) or True)})}
    S.reqscript = lambda n: mods.get(n)
    S.tile = T
    r = py(S.place_mood_shop("Smelter", True))
    assert r["ok"] is True and r["kind"] == "Smelter" and "by_gate" not in r and placed, r
    cells = placed[-1][1]
    assert cells[1].text == "es", cells[1].text
    r = py(S.place_mood_shop("Throne", True))
    assert r["rejected"] and "no such mood workshop" in r["error"], r
    lua.execute("""local S = ...
        S.df.global.world.buildings.other.FURNACE_ANY = {{type = 'Smelter',
            getBuildStage = function() return 0 end, getMaxBuildStage = function() return 1 end}}
        S.df.furnace_type = setmetatable({}, {__index = function(_, k) return k end})""", S)
    r = py(S.place_mood_shop("Smelter", True))
    assert r["rejected"] and "waits to be built" in r["error"], r


# (0.105.119 item41) A, 25 Nov: "no free 5x5 of roofed floor" while a mood waited. A fort of
# 3-wide rooms: the siege workshop finds no 5x5, a mood's shop (every one 3x3) takes a room
ROOMS_3 = ["###########",
           "#E#########",
           "#.#########",
           "#.###...###",
           "#.......###",
           "#.###...###",
           "#.#########",
           "###########"]


@test("item41 siege: a mood's shop searches a 3x3 footprint (a 3-wide room takes it); the siege workshop "
      "keeps its 5x5 (none here: refused, '5x5' said)")
def _():
    need_lua()
    lua, S = siege_rig()
    e, inside, T = ascii_fort(lua, ROOMS_3)
    assert S.shop_spot_anywhere(e, inside, T) is None
    placed = []
    e.id = 1
    mods = {"ai-gates": lua.table_from({"GATES": lua.table_from({"entrances": lua.table_from([e]), "inside": inside})}),
            "ai-builder": lua.table_from({"qf_try": lambda *a: (placed.append(a) or True)})}
    S.reqscript = lambda n: mods.get(n)
    S.tile = T
    S.shop_count = lambda: 0
    r = py(S.place_mood_shop("Smelter", True))
    assert r["ok"] is True and r["at"]["x"] == 6 and r["at"]["y"] == 4, r
    r = py(S.place_shop(1, True))
    assert r["rejected"] and "no free 5x5" in r["error"], r
    src = module_src("ai-siege.lua")
    assert "place_one(e, G, key, kind, false, dry_run, 1)" in src and "place_one(e, G, 'ws', 'siege workshop', true, dry_run)" in src


# --- 3. the stuck sweep's give-up -------------------------------------------------------

@test("3: C's dining level (0 of 16 pieces, tables and chairs) and the temples: the sweep's retire leaves "
      "them planned (leave_planned), not the plain finish the bridge refused 71 times")
def _():
    r = {"kind": "project", "id": 70, "state": "furnish", "what": "dining"}
    proj = {"furnish": {"days": 94, "done": 0, "placed": 16, "waiting": {"Table": 8, "Chair": 8}}}
    _, retire, _ = PST._remedies(r, proj, None, 94, CFG)
    assert retire == {"type": "finish_project", "project_id": 70, "stalled": True, "leave_planned": True}, retire
    temple = {"furnish": {"days": 99, "done": 4, "placed": 8, "waiting": {"Statue": 2, "Workshop": 0, "Coffin": 2}}}
    _, retire, _ = PST._remedies(dict(r, id=54, what="temple"), temple, None, 99, CFG)
    assert retire.get("leave_planned") is True and "give_up" not in retire
    # a young shop: left planned too (not taken off before shop_piece_wait_days)
    young = {"furnish": {"days": 100, "done": 0, "placed": 1, "waiting": {"Workshop": 1}}}
    _, retire, _ = PST._remedies(dict(r, id=74, what="workshops"), young, None, 121, CFG)
    assert retire.get("leave_planned") is True and "give_up" not in retire, retire
    # an old shop only: the 0.105.51 give_up as before
    old = {"furnish": {"days": 400, "done": 0, "placed": 1, "waiting": {"Workshop": 1}}}
    _, retire, _ = PST._remedies(dict(r, id=74, what="workshops"), old, None, 121, CFG)
    assert retire == {"type": "finish_project", "project_id": 74, "stalled": True, "give_up": True}, retire
    # a well level (E's project 7, 0 of 1): the well rule's, the sweep leaves it
    assert PST._skip({"kind": "project", "what": "well", "state": "furnish"}, {"furnish": {}}, None, CFG)


@test("3 lua: finish_project leave_planned: the level is done, its waiting pieces left planned (none taken off); "
      "with give_up too the waiting shops are taken off; a well level is refused; a plain finish still refuses")
def _():
    need_lua()
    import test_builder as TB
    TB._reset(True)
    B, LUA = TB.B, TB.LUA
    real_drop, real_prog = B.drop_waiting_shops, B.furnish_progress
    try:
        calls = LUA.eval("{}")
        B.drop_waiting_shops = LUA.eval("function(calls) return function(p) table.insert(calls, p.id); return 1 end end")(calls)
        B.furnish_progress = LUA.eval("function() return {placed = 16, done = 0, waiting = {Table = 8, Chair = 8}} end")
        r = TB.styled(kind="storage", piles=["food"], style={"smooth": 0})
        TB.finish_digging()
        B.furnish_project(r.project_id, True)
        got = B.finish_project(r.project_id, False, True)
        assert not got.ok and "16 buildings still waiting" in got.error, dict(got)     # the run's refusal
        got = B.finish_project(r.project_id, False, True, False, None, True)
        assert got.ok and got.phase in ("done", "decorate") and got.left_planned == 16 and calls[1] is None, dict(got)
        B.furnish_progress = LUA.eval("function() return {placed = 3, done = 1, waiting = {Workshop = 1, Bed = 1}} end")
        r2 = TB.styled(kind="storage", piles=["food"], style={"smooth": 0})
        TB.finish_digging()
        B.furnish_project(r2.project_id, True)
        got = B.finish_project(r2.project_id, False, True, True, None, True)
        assert got.ok and got.dropped == 1 and got.left_planned == 1 and calls[1] == r2.project_id, dict(got)
        # a well level
        data = B.load_projects()
        r3 = TB.styled(kind="storage", piles=["food"], style={"smooth": 0})
        TB.finish_digging()
        B.furnish_project(r3.project_id, True)
        data = B.load_projects()
        for p in data.list.values():
            if p.id == r3.project_id:
                p.kind = "well"
        B.save_projects(data)
        got = B.finish_project(r3.project_id, False, True, False, None, True)
        assert not got.ok and "well" in got.error, dict(got)
    finally:
        B.drop_waiting_shops, B.furnish_progress = real_drop, real_prog
    # (r5 p5) the bridge's finish_project run on a stand-in ai-builder (tests/bridge_behaviour.py), not its text
    import bridge_behaviour as BB
    got, _, _ = BB.forwarded("finish_project", {"project_id": 4, "leave_planned": True}, "ai-builder", "finish_project")
    assert got[0][1][0] == 4 and got[0][1][5] is True, got                  # leave_planned passed on
    got, _, _ = BB.forwarded("finish_project", {"project_id": 4, "leave_planned": "yes"}, "ai-builder", "finish_project")
    assert got[0][1][5] is False, got                                       # only true


# --- 4. hunts ---------------------------------------------------------------------------

def hunt_fort(alarm=True, thieves=(), intrusion=None, cause="intruder"):
    s = copy.deepcopy(BASE)
    s["civ_alert"] = alarm
    s["threats"] = {"thieves": {"list": [dict(x) for x in thieves]}}
    m = Memory()
    m.ai_alert_raised = alarm
    now = abs_tick(s)
    m.alarm_gov = {"on": {"tick": now - 3 * DAY, "cause": cause, "key": cause,
                          "why": "DF reports an intruder on the map (0 game hour(s) ago), nobody seen yet"}}
    m.intrusion = intrusion if intrusion is not None else {"tick": now - 3 * DAY, "civ": -1, "invaders": 1}
    return s, m


@test("4: the alarm the AI raised for a lone sneaker, seen or gone, no thief inside: hunting goes on; still "
      "unseen, a thief inside, a siege's record, another cause or the player's own alarm: no hunt")
def _():
    rules_ = {}
    s, m = hunt_fort()
    assert PH.thief_alarm_over(s, m, CFG) is True
    assert PH._blocked(s, m, CFG, rules_, "ai") is None
    # still unseen (within intrusion_alert_days)
    s, m = hunt_fort()
    m.intrusion = {"tick": abs_tick(s) - DAY // 2, "civ": -1, "invaders": 1}
    assert PH._blocked(s, m, CFG, rules_, "ai") == "the alarm is up"
    # a thief still inside
    s, m = hunt_fort(thieves=[{"id": 9, "name": "Thief", "kind": "thief", "inside": True}])
    assert PH._blocked(s, m, CFG, rules_, "ai") == "the alarm is up"
    # caught (caged): dealt with
    s, m = hunt_fort(thieves=[{"id": 9, "name": "Thief", "kind": "thief", "inside": True, "caged": True}])
    assert PH._blocked(s, m, CFG, rules_, "ai") is None
    # a siege's record (a civilisation)
    s, m = hunt_fort(intrusion={"tick": 0, "civ": 41, "invaders": 30})
    assert PH._blocked(s, m, CFG, rules_, "ai") == "the alarm is up"
    # a cavern beast's alarm
    s, m = hunt_fort(cause="cavern")
    assert PH._blocked(s, m, CFG, rules_, "ai") == "the alarm is up"
    # the player's alarm (the AI raised none)
    s, m = hunt_fort()
    m.ai_alert_raised = False
    assert PH._blocked(s, m, CFG, rules_, "ai") == "the alarm is up"


def hunt_state(targets, squads):
    s = copy.deepcopy(BASE)
    s["civ_alert"] = False
    s["hunt"] = {"targets": targets, "squads": squads, "hunts": [], "history": []}
    return s


SQUADS = [{"id": i, "name": f"Squad {i}", "soldiers": 10, "power": 600, "armed": 10, "armored": 10,
           "ranged": 0, "at_home": True} for i in (1, 2, 3)]


def hidden_beast(power_ok=True, **kw):
    t = {"id": 77, "name": "Holemucks, Forgotten Beast", "kinds": ["forgotten beast"], "great_danger": True,
         "why": "danger", "size": 200000, "pos": {"x": 120, "y": 120, "z": 130}, "layer": "Cavern1",
         "region": "cavern", "flier": False, "fire_breather": False, "route": {"ok": True, "length": 80,
                                                                              "blocked_by": "none"},
         "near_workers": 0, "seen_ticks": 5000, "can_reach_dwarves": False, "kill_ok": True, "hidden": True}
    t.update(kw)
    return t


@test("4: a hidden great beast in a cavern: hunted only on a better matchup (r2h7_hunt_hidden_ratio_mult); "
      "behind the AI's seal: judged, a win handed to the seal's kill plan, a loss kept sealed")
def _():
    cfg = dict(CFG)
    t = hidden_beast()
    need = PH.need_of(t, None)
    s = hunt_state([t], copy.deepcopy(SQUADS))
    props, notes = [], []
    PH._hunt_rule(s, cfg, props, notes, Memory())
    sent = [p for p in props if p.action.get("type") == "hunt_send"]
    # the same beast seen: sent with fewer squads (or the same) than hidden
    t2 = hidden_beast(hidden=None)
    s2 = hunt_state([t2], copy.deepcopy(SQUADS))
    p2, n2 = [], []
    PH._hunt_rule(s2, cfg, p2, n2, Memory())
    sent2 = [p for p in p2 if p.action.get("type") == "hunt_send"]
    assert sent2, n2
    if sent:
        assert len(sent[0].action["squad_ids"]) >= len(sent2[0].action["squad_ids"]), (sent, sent2)
    # with the bar so high no party clears it: the hidden one isn't sent, the seen one is
    cfg2 = dict(cfg, r2h7_hunt_hidden_ratio_mult=1000.0)
    p3, n3 = [], []
    PH._hunt_rule(s, cfg2, p3, n3, Memory())
    assert not [p for p in p3 if p.action.get("type") == "hunt_send"], p3
    assert need > 0
    # behind the seal: judged
    ts = hidden_beast(hidden=None, route={"ok": False, "blocked_by": "seal"})
    p4, n4 = [], []
    PH._hunt_rule(hunt_state([ts], copy.deepcopy(SQUADS)), cfg, p4, n4, Memory())
    assert not [p for p in p4 if p.action.get("type") == "hunt_send"]
    assert any("kill plan opens the way" in n for n in n4), n4
    weak = [dict(q, soldiers=3, armed=3, power=5) for q in SQUADS[:1]]
    p5, n5 = [], []
    PH._hunt_rule(hunt_state([ts], weak), cfg, p5, n5, Memory())
    assert any("behind the AI's cavern seal; kept there" in n for n in n5), n5


HUNT_GAME = r"""
local src = ...
local e = setmetatable({}, {__index = _G})
e.reqscript = function() return {} end
e.df = {global = {}}
e.dfhack = {}
assert(load(src, 'ai-hunt', 't', e))()
return e
"""


@test("4 lua: target_ok: a hidden unit is no target, but a hidden great danger is (listed hidden)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(HUNT_GAME, module_src("ai-hunt.lua"))
    t = lua.table_from
    ok, why = H.target_ok(t({"hidden": True, "danger": True}))
    assert ok is False and why == "hidden"
    ok, why = H.target_ok(t({"hidden": True, "great_hidden": True, "danger": True}))
    assert ok is True and why == "danger"
    ok, why = H.target_ok(t({"hidden": True, "great_hidden": True, "dead": True}))
    assert ok is False
    src = module_src("ai-hunt.lua")
    assert "f.great_hidden and region ~= 'cavern'" in src and "hidden = f.great_hidden or nil" in src


# --- 5b. cavern_farm (A, 15-16 Nov: 60 refusals "x128 y127 z143 is not in a cavern", the same tile) ----

@test("5b lua: cavern_farm given the fort's side of the junction (no cavern tile): the nearest cavern tile is "
      "taken; nothing near: refused as before")
def _():
    need_lua()
    # test_provisions' fake fort (its helpers only: that file ends in finish(), so it isn't imported)
    src = (ROOT / "tests" / "test_provisions.py").read_text(encoding="utf-8")
    TP = type(sys)("tp_helpers")
    TP.__dict__["__file__"] = str(ROOT / "tests" / "test_provisions.py")
    exec(compile(src[:src.index("\n@test(")], "test_provisions_head", "exec"), TP.__dict__)
    cut = src.index("def cave_floor(")
    exec(compile(src[cut:src.index("\n@test(", cut)], "test_provisions_cave", "exec"), TP.__dict__)
    lua, env, w = TP.world()
    TP.cave_floor(w, 20, 20, 25, 25)
    # x 18 y 20 z 80: beside the cavern's edge, not a feature tile (the stub reads it as soil outside)
    r = py(env.cavern_farm(TP.T(lua, {"at": {"x": 18, "y": 20, "z": 80}, "tiles": 12}), True))
    assert r["ok"] and r["dry_run"], r
    r = py(env.cavern_farm(TP.T(lua, {"at": {"x": 5, "y": 5, "z": 100}, "tiles": 12}), False))
    assert r["rejected"] and "is not in a cavern" in r["error"], r


# --- 5. residency -----------------------------------------------------------------------

def petitions_fort(outsiders, days):
    s = copy.deepcopy(BASE)
    s.setdefault("settings", {})["traits"] = {"outsiders": outsiders}
    s["petitions"] = {"pending": [{"applicant": {"on_map": True, "unit": 2358}, "days": d, "id": 3154 + i,
                                   "name": "Vabok, Bard", "reason": "entertain_people", "type": "Residency"}
                                  for i, d in enumerate(days)], "residents": [], "residents_n": 0}
    return s


# (merge 0.105.57) test 5 (residency declined after r2h7_residency_neutral_days) was retired: r2h9's
# residency_verdict weighs every petition at once and supersedes it (tests/test_r2_h9.py covers residency).

if __name__ == "__main__":
    finish()
