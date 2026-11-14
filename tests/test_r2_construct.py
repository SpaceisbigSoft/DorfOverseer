"""(0.105.47, R2 J13) Why five construction lines read 0 in all six forts
(8-13 Nov), each cause with a test:

- the keep's ring and court and the halls lost every tile under a tree's
  crown (DF: not outside) as "the fort's own rock or rooms (under a roof)";
- the keep's court refusal named nothing ("no open, flat ground ...") and
  counted a surface cut off by a shut gate as unreachable; no 5x5 court;
- the keep's ring named only the first way in's first bad tile;
- the gatehouse (A, the War-hold) refused "no wall can go at x109 y148
  (floor)": canopy ground again, and only the first way out's reason;
- soil floors asked for halls the bridge's report shows hold no soil;
- the scorecard read the season files of a line the keeper dropped (A was
  restored to its start and replayed, gatehouse and wings built), counted
  seal_cavern (door locks) as cavern walls, and read 0 where there was
  nothing to do (no cavern opening, no soil).

    python tests/test_r2_construct.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import memstore  # noqa: E402
import overseer  # noqa: E402
import planner_construct as pc  # noqa: E402
import scorecard  # noqa: E402
from planner import Memory  # noqa: E402
from planner_core import PLANNER_CONFIG  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def _harness(path: str) -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


# --- the builder, on test_builder's fake fort -------------------------------------------------

LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(_harness("test_builder.py"),
                   (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
B.KEEP_COURT_SECONDS = 20
REAL_WALK = B.walk_group


def T(**kw):
    return LUA.table_from(kw)


def reset():
    W.reset()
    B.walk_group = REAL_WALK
    LUA.execute("df = df or {}; df.global = df.global or {}; df.global.world = df.global.world or {}; "
                "df.global.world.buildings = {other = {TRADE_DEPOT = {}, FARM_PLOT = {}}}")


def ground(x0, x1, y0, y1, z, **kw):
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            W.set(x, y, z, T(shape="FLOOR", material="SOIL", outside=True, **kw))
            W.set(x, y, z + 1, T(shape="EMPTY", outside=True))


def anchors():
    return LUA.table_from({1: T(x=60, y=60, z=80)})


def court(a):
    r = B.find_keep_court(a)
    return r if isinstance(r, tuple) else (r, None)


@test("canopy: ground under a tree's crown is open ground for the keep and halls; under a built roof it isn't")
def _():
    reset()
    W.set(10, 10, 80, T(shape="FLOOR", material="SOIL", outside=False, subterranean=False))
    W.set(10, 10, 81, T(shape="EMPTY", outside=False))
    W.set(10, 10, 82, T(shape="EMPTY", outside=False))
    W.set(10, 10, 83, T(shape="BRANCH", material="TREE"))
    assert B.canopy_ground(10, 10, 80) and B.keep_tile(10, 10, 80) == "ground"
    assert "under a roof" not in B.keep_tile_why(10, 10, 80)
    # a built floor over it: the fort's roof, not a grove
    W.set(10, 10, 82, T(shape="FLOOR", material="CONSTRUCTION"))
    assert not B.canopy_ground(10, 10, 80) and B.keep_tile(10, 10, 80) is None
    assert "under a roof" in B.keep_tile_why(10, 10, 80)
    # underground (or the flag unread): never
    W.set(10, 10, 82, T(shape="EMPTY"))
    W.set(10, 10, 80, T(subterranean=True))
    assert not B.canopy_ground(10, 10, 80)
    W.set(10, 10, 80, T(subterranean=None))
    assert not B.canopy_ground(10, 10, 80)


@test("keep court: a grove's ground (under the crowns) takes the court; before 0.105.47 it was 'under a roof'")
def _():
    reset()
    ground(85, 100, 40, 60, 78)
    for x in range(85, 101):
        for y in range(40, 61):
            W.set(x, y, 78, T(outside=False, subterranean=False))   # the crowns' shade
            W.set(x, y, 79, T(outside=False))
            W.set(x, y, 80, T(shape="BRANCH", material="TREE"))
    site, why = court(anchors())
    assert site and site.court and site.z == 78, why


@test("keep court: a 5x5 court where no 7x7 fits; a refusal counts why the courts failed")
def _():
    reset()
    ground(85, 91, 40, 46, 78)         # 7x7 of flat ground: only a 5x5 inside fits (r 3)
    site, why = court(anchors())
    assert site and site.r == 3, why
    reset()
    ground(85, 91, 40, 46, 78)
    for x in range(85, 92):
        W.set(x, 43, 78, T(shape="RAMP"))     # a slope across it: no court at all
    site, why = court(anchors())
    assert site is None and "open tile(s) looked at" in why and "a ramp tile" in why, why


@test("keep court: the surface past a shut gate (another walk group) is the dwarves' ground too")
def _():
    reset()
    ground(85, 100, 40, 60, 78)
    W.set(60, 60, 80, T(shape="STAIR_DOWN", outside=True))
    # the citizens' group is 1 (inside); the surface's 2, joined only through the way in
    LUA.globals().B_PEEK = W.peek
    B.walk_group = LUA.eval("""function(x, y, z)
        local t = B_PEEK(x, y, z)
        if not t or t.shape == 'WALL' then return 0 end
        if t.outside then return 2 end
        if z >= 60 and z <= 80 then return 1 end
        return 0 end""")
    site, why = court(anchors())
    assert site and site.court, why


@test("keep ring: each way in's first bad tile is named, not only the first's")
def _():
    reset()
    a = LUA.table_from({1: T(x=60, y=60, z=80), 2: T(x=30, y=30, z=80)})
    site, why = B.find_keep_ring(a)
    assert site is None and "x56 y56" in why and "; r4 is all rock" in why, why


# --- the gates: the gatehouse's open ground ---------------------------------------------------

GL = LuaRuntime(unpack_returned_tuples=True)
M, GW = GL.execute(_harness("test_gates.py"), module_src("ai-gates.lua"))


def shaft_world(surface_rows, width=40):
    below = (["#" * width] * 8 + ["#" * 10 + "s" + "." * (width - 11)] + ["#" * 10 + "." * (width - 10)] * 4
             + ["#" * width] * 6)
    m = GL.table()
    for z, rows in ((0, below), (1, surface_rows)):
        level = GL.table()
        for y, r in enumerate(rows):
            level[y] = r
        m[z] = level
    GW.map = m
    GL.execute("local M, w = ...; M.map_size = function() return w, 19, 2 end", M, width)
    GW.buildings = GL.table_from({1: GL.table_from({"id": 7, "kind": "hatch", "x1": 10, "y1": 8, "x2": 10, "y2": 8,
                                                    "z": 1, "name": "", "closed": False})})
    starts = GL.table_from({i + 1: GL.table_from({"x": 30 + i, "y": 10, "z": 0}) for i in range(3)})
    es, _, _ = M.find_entrances(starts, GW.buildings)
    return es[1]


@test("gatehouse (A, 8-13 Nov): ground under a tree's crown round the hatch takes its walls")
def _():
    rows = ["o" * 40] * 7 + ["o" * 9 + "nnn" + "o" * 28, "o" * 9 + "ntn" + "o" * 28, "o" * 9 + "nnn" + "o" * 28] \
        + ["o" * 40] * 9
    e = shaft_world(rows)
    assert e.lid and e.gatehouse == "possible", (e.lid, e.gatehouse, e.gatehouse_why)
    # crowns only north and south of it (the top still meets the open ground)
    rows = ["o" * 40] * 4 + ["o" * 8 + "nnnnn" + "o" * 27] * 4 + ["o" * 10 + "t" + "o" * 29] \
        + ["o" * 8 + "nnnnn" + "o" * 27] + ["o" * 40] * 9
    e = shaft_world(rows)
    assert e.lid and e.gatehouse == "possible", (e.lid, e.gatehouse, e.gatehouse_why)


@test("gatehouse: a refusal names every way out's reason and what stands on the tile")
def _():
    rows = ["o" * 40] * 8 + ["o" * 10 + "t" + "o" * 29] + ["o" * 40] * 10
    real = M.tile
    # a stockpile on the open ground all round the hatch (occupied, outside)
    M.tile = GL.eval("""function(real)
        return function(x, y, z)
            local t = real(x, y, z)
            if t and z == 1 and math.abs(x - 10) <= 1 and math.abs(y - 8) <= 1 and not (x == 10 and y == 8) then
                t.occupied = true
            end
            return t
        end end""")(real)
    GW.at = GL.table_from({f"{x},{y},1": "Stockpile" for x in (9, 10, 11) for y in (7, 8, 9)})
    try:
        e = shaft_world(rows)
        why = str(e.gatehouse_why)
        assert e.gatehouse == "none", why
        assert why.count("; ") >= 3 and "north: " in why and "a Stockpile stands there" in why, why
    finally:
        M.tile = real
        GW.at = GL.table()


# --- the soil floors ---------------------------------------------------------------------------

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
GARDEN = {"agriculture": 120, "husbandry": 80, "surface": 80, "welfare": 40, "grandeur": 40}


def soil_fort(report=None):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(GARDEN)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["stocks"]["blocks"] = 400
    s["projects"]["decorating"] = [{"id": 7, "kind": "dining", "phase": "decorate"},
                                   {"id": 9, "kind": "temple", "phase": "decorate"}]
    if report is not None:
        s["constructions"] = {"soil_floors": report}
    return s


def soil_props(s):
    ps, notes = [], []
    pc._soil_floor_rule(s, s["settings"]["traits"], PLANNER_CONFIG, ps, notes, Memory())
    return ps


@test("soil floors (B, C, F: 16 refusals): a hall the bridge's soil report leaves out has no soil: not asked")
def _():
    assert [p.action["project_id"] for p in soil_props(soil_fort())] == [7]      # no report: asked, as before
    assert not soil_props(soil_fort([]))                                         # the report: none has soil
    assert [p.action["project_id"] for p in soil_props(soil_fort([{"project_id": 9, "tiles": 12}]))] == [9]


# --- the scorecard -------------------------------------------------------------------------------

def measures(c, floored=0):
    return scorecard.construction_measures({"constructions": c}, {"soil_floored": floored})


@test("scorecard: no cavern opening on the fort's walk, none walled: no data, not a 0")
def _():
    base = {"total": 3, "surface": {"total": 0}, "ai": {"gate_pieces": 0, "wings": 0, "cavern_walls": 0,
                                                         "soil_floors": 0}}
    assert measures(dict(base, cavern_openings=0))["cavern_walls"] is None
    assert measures(dict(base, cavern_openings=2))["cavern_walls"] == 0
    assert measures(base)["cavern_walls"] == 0                  # an older bridge: as before


@test("scorecard: no finished hall in soil and nothing floored: soil floors no data; floored ones still count")
def _():
    base = {"total": 3, "surface": {"total": 0}, "ai": {"gate_pieces": 0, "wings": 0, "cavern_walls": 0,
                                                         "soil_floors": 0}}
    assert measures(dict(base, soil_floors=[], soil_floors_placed=0))["soil_floors"] is None
    assert measures(dict(base, soil_floors=[{"project_id": 7, "tiles": 20}], soil_floors_placed=0))["soil_floors"] == 0
    assert measures(dict(base, soil_floors=[], soil_floors_placed=0), floored=0)["soil_floors"] is None
    assert measures(base)["soil_floors"] == 0


@test("scorecard: a cavern opening walled is fortify_entrance's sealed style, not seal_cavern's door locks")
def _():
    d = {"year": 255, "tick": 0}
    j = [{"kind": "decision", "date": {"year": 251, "tick": 0}, "action": {"type": "fortify_entrance", "style": "sealed"},
          "result": {"ok": True}},
         {"kind": "decision", "date": {"year": 251, "tick": 5}, "action": {"type": "seal_cavern"}, "result": {"ok": True}}]
    c = scorecard.journal_counts(j, d)
    assert c["ok"]["fortify_entrance:sealed"] == 1, dict(c["ok"])
    assert scorecard.FLAT_ACTIONS["cavern_walls"] == ("fortify_entrance:sealed",)


@test("keep_state (A, 13 Nov): the game gone back in the same run replaces the season and sets the dropped line aside")
def _():
    tmp = Path(tempfile.mkdtemp())
    old = (memstore.FORTS_DIR, overseer.PRESET_FILE, dict(memstore.ALIASES))
    memstore.FORTS_DIR = tmp / "forts"
    overseer.PRESET_FILE = tmp / "keeper-preset.json"
    memstore.ALIASES.clear()
    try:
        key = "region4#1430"
        overseer.note_preset(key, "War-hold")
        for y, sn, w in ((250, "spring", 1), (250, "summer", 1), (258, "spring", 1)):
            overseer.keep_state({"date": {"year": y, "season": sn, "tick": 1}, "walls": w}, key)
        d = memstore.fort_dir(key) / "states"
        # the same season again, nothing later: kept (as before)
        overseer.keep_state({"date": {"year": 258, "season": "spring", "tick": 9}, "walls": 99}, key)
        assert json.loads((d / "258-spring.json").read_text())["walls"] == 1
        # restored to 250 summer: that season replaced, 258 spring set aside
        overseer.keep_state({"date": {"year": 250, "season": "summer", "tick": 2}, "walls": 5}, key)
        assert json.loads((d / "250-summer.json").read_text())["walls"] == 5
        assert not (d / "258-spring.json").exists() and (d / "dropped" / "258-spring.json").exists()
        assert json.loads((d / "250-spring.json").read_text())["walls"] == 1      # earlier ones stay
        # the replay reaches 258 spring again: written anew
        overseer.keep_state({"date": {"year": 258, "season": "spring", "tick": 3}, "walls": 18}, key)
        assert json.loads((d / "258-spring.json").read_text())["walls"] == 18
        assert sorted(p.name for p in d.glob("*.json")) == ["250-spring.json", "250-summer.json", "258-spring.json"]
    finally:
        memstore.FORTS_DIR, overseer.PRESET_FILE = old[0], old[1]
        memstore.ALIASES.clear()
        memstore.ALIASES.update(old[2])


if __name__ == "__main__":
    finish()
