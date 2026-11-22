"""(0.105.47) The Garden fort's gardens. The player (14 Nov): "garden fort
should have gardens". Tested here:

1. the field customs fire for surface fields: the dining level and the
   food-shop level go just under the fields above ground (fields.py from the
   report's farm plots; masterplan._surface_field_band), toward them, and
   the deep farms band still works; nothing for a default fort or without
   fields; the second way to the surface comes up by the fields;
2. the garden court: its layout (ai-layouts.garden_court) and its building
   on a stub map (ai-builder-court: site by the fields, walls, beds, paths,
   statues and seats, the meeting area; a dry run changes nothing), the
   brain's rule by the sliders (planner_garden), the design wish wired
   (planner_design hands garden_court to the court), the bridge's wiring;
3. the underground gardens: in the soil for the Garden fort, finished by the
   soil floor rule (garden in SOIL_FLOOR_KINDS on both sides), sooner by
   Agriculture (good_times' pace, the ladder).

    python tests/test_garden_fort.py
"""

from __future__ import annotations

import ast
import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts

import fields  # noqa: E402
import masterplan  # noqa: E402
import planner_building as pb  # noqa: E402
import planner_design  # noqa: E402
import planner_garden as G  # noqa: E402
import planner_growth  # noqa: E402
import planner_construct  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
from digest import SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


def _reset_py():
    fields.set_fields(None)


test = make_test(before=_reset_py)
CFG = PLANNER_CONFIG

SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 40}}
PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}
SURFACE = 60


def presets() -> dict:
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    block = re.search(r"^BUILTIN_PRESETS = \{.*?^\}", src, re.S | re.M).group(0)
    lua = LuaRuntime()
    lua.execute(block)
    t = lua.globals().BUILTIN_PRESETS
    return {name: dict(t[name].items()) for name in t.keys()}


PRESETS = presets()
GARDEN = PRESETS["Garden fort"]                  # agriculture 120, surface 80, grandeur 40
LOW_GARDEN = {"agriculture": 80}                 # the custom, Surface 0
DEFAULT: dict = {}


def memory(traits, soil=(58, 59)) -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {"100,60,160": {"kind": "surface", "elevation": SURFACE}}}
    assert masterplan.ensure(copy.deepcopy(STATE), m, dict(SITE, soil=list(soil)), traits, PROFILE)
    return m


def district(m, kind) -> dict:
    return next(x for x in m.atlas["plan"]["districts"] if x["kind"] == kind)


FIELDS_EAST = {"farms": {"plots_surface": 3, "plot_list": [
    {"id": 1, "x": 120, "y": 100, "elevation": SURFACE, "underground": False},
    {"id": 2, "x": 124, "y": 102, "elevation": SURFACE, "underground": False},
    {"id": 3, "x": 122, "y": 98, "elevation": SURFACE, "underground": False},
    {"id": 4, "x": 100, "y": 100, "elevation": 40, "underground": True}]},
    "map": {"elevation_offset": -100}}
FOOD = {"type": "start_project", "kind": "workshops", "shops": ["Still", "Kitchen"]}
MASON = {"type": "start_project", "kind": "workshops", "shops": ["Masons"]}


class Patched:
    def __init__(self, mod, **attrs):
        self.mod, self.attrs, self.real = mod, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.real[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)

    def __exit__(self, *a):
        for k, v in self.real.items():
            setattr(self.mod, k, v)


# --- 1. the field customs above ground ----------------------------------------------------------

@test("fields: the surface plots of the report, on their most common elevation; underground plots left out")
def _():
    f = fields.read(FIELDS_EAST)
    assert f == {"n": 3, "elevation": 60, "x": 122, "y": 100, "z": 160}, f
    assert fields.read({"farms": {"plots_surface": 2}}) == {"n": 2}
    assert fields.read({"farms": {"plots_surface": 0, "plot_list": []}}) is None
    assert fields.read({}) is None and fields.read(None) is None
    fields.note(FIELDS_EAST)
    assert fields.current()["x"] == 122
    assert fields.toward({"x": 100, "y": 100}, fields.current()) == "east"
    assert fields.toward({"x": 121, "y": 101}, fields.current()) is None      # round the spine


@test("field_hall: the Garden fort's dining level just under its surface fields, toward them, stamped")
def _():
    m = memory(GARDEN)                                   # soil 58-59: no farms 3 under the surface
    assert "customs" not in masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)   # no fields: as before
    fields.note(FIELDS_EAST)
    seen = []
    for i in range(4):
        h = masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)
        assert h["customs"] == ["field_hall"], h
        assert (h["elev_lo"], h["elev_hi"]) == (SURFACE - 2, SURFACE - 1), h
        assert h["dirs"][0] == "east", h
        seen.append(h["elev_target"])
        masterplan.note_result(m, {"type": "start_project", "kind": "dining", "plan": h},
                               {"ok": True, "project_id": 10 + i, "elevation": h["elev_target"],
                                "in_district": True}, STATE)
    assert seen[0] == SURFACE - 1 and set(seen) == {SURFACE - 1, SURFACE - 2}, seen   # just under them first
    w = masterplan.hint(m, "workshops", traits=GARDEN, profile=PROFILE, action=FOOD)
    assert w["customs"] == ["field_kitchens"] and w["elev_hi"] == SURFACE - 1, w
    ms = masterplan.hint(m, "workshops", traits=GARDEN, profile=PROFILE, action=MASON)
    assert "customs" not in ms, ms
    # the journal's stamp through apply_customs (the scorecard's "halls and kitchens by the fields")
    a = {"type": "start_project", "kind": "dining", "tables": 10}
    pb.apply_customs(a, m, GARDEN, PROFILE, 40)
    assert a["customs"] == ["field_hall"] and a["plan"]["elev_hi"] == SURFACE - 1, a
    a = dict(FOOD)
    pb.apply_customs(a, m, GARDEN, PROFILE, 40, urgent=True)
    assert a["customs"] == ["field_kitchens"], a


@test("field_hall: the deep farms band at Surface 0; under the fields first at Surface 50+; none for others")
def _():
    m = memory(LOW_GARDEN, soil=(55, 56))
    fields.note(FIELDS_EAST)
    h = masterplan.hint(m, "dining", traits=LOW_GARDEN, profile=PROFILE)
    fd = district(m, "farms")
    assert h["customs"] == ["field_hall"] and (h["elev_lo"], h["elev_hi"]) == (fd["lo"], fd["hi"]), h   # the deep farms
    assert h["elev_hi"] <= SURFACE - 3, h
    g = dict(GARDEN)
    m2 = memory(g, soil=(55, 56))
    h = masterplan.hint(m2, "dining", traits=g, profile=PROFILE)
    assert h["customs"] == ["field_hall"] and h["elev_hi"] == SURFACE - 1, h                # under the fields
    for traits in (DEFAULT, PRESETS["Merchant city"], PRESETS["War-hold"]):
        mm = memory(traits)
        h = masterplan.hint(mm, "dining", traits=traits, profile=PROFILE)
        assert "field_hall" not in (h or {}).get("customs", []), (traits, h)
    # fields only as a count (an old bridge): the band under the way in, no direction
    fields.set_fields({"n": 2})
    h = masterplan.hint(memory(GARDEN), "dining", traits=GARDEN, profile=PROFILE)
    assert h["customs"] == ["field_hall"] and h["elev_hi"] == SURFACE - 1, h


@test("field_hall: an underground-only fort keeps its ceiling; the band never reaches the surface")
def _():
    t = dict(LOW_GARDEN, surface=-100)
    m = memory(t)
    fields.note(FIELDS_EAST)
    h = masterplan.hint(m, "dining", traits=t, profile=PROFILE)
    ceil = masterplan.ceiling(m, t)
    assert h["elev_hi"] <= min(ceil, SURFACE - 1), (h, ceil)


@test("second way: the Garden fort's comes up by the fields; others as before")
def _():
    import planner_gates
    s = {"dwarves": {"total": 40}, "entrances": {"entrances": [{"kind": "surface", "x": 100, "y": 60, "z": 160}]},
         "map": {"elevation_offset": -100}, "date": {"year": 150, "tick": 0}, "projects": {"open": []}}
    fields.note(FIELDS_EAST)
    for traits, near in ((GARDEN, {"x": 122, "y": 100}), (DEFAULT, None)):
        m = Memory()
        props, notes = [], []
        planner_gates._second_way_rule(copy.deepcopy(s), m, CFG, traits, props, notes, {})
        ways = [p for p in props if p.action.get("type") == "dig_way_in"]
        assert len(ways) == 1, (props, notes)
        assert ways[0].action.get("near") == near, ways[0].action


@test("the switch: planner_config garden_fort off gives the old behaviour (no fields, no court, no pace, no soil gardens)")
def _():
    cfg = dict(CFG, garden_fort=False)
    fields.note(FIELDS_EAST, cfg["garden_fort"])
    assert fields.current() is None and not fields.enabled()
    m = memory(GARDEN)
    assert "customs" not in masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)
    h = masterplan.hint(m, "garden", traits=GARDEN, profile=PROFILE)
    assert h["district"] == masterplan.hint(memory(DEFAULT), "garden", traits=DEFAULT, profile=PROFILE)["district"] \
        or (h["elev_lo"], h["elev_hi"]) == (district(m, "halls")["lo"], district(m, "halls")["hi"]), h
    assert G.garden_pace(GARDEN, cfg) == 1.0
    props = []
    G._garden_court_rule({"dwarves": {"total": 40}}, cfg, 40, GARDEN, props, [], Memory(), {})
    assert not props
    a = {"type": "start_project", "kind": "garden"}
    assert planner_growth.ladder_score(a, {}, GARDEN, cfg) == planner_growth.ladder_score(a, {}, {"grandeur": 40}, cfg)
    s = {"projects": {"decorating": [{"id": 7, "kind": "garden"}]}}
    assert planner_construct._soil_candidates(s, Memory(), cfg) == []
    fields.note(FIELDS_EAST)
    assert fields.enabled() and fields.current()


# --- 3. the underground gardens -----------------------------------------------------------------

@test("gardens: the Garden fort's go in the soil (the farms district); a default fort's among the halls")
def _():
    m = memory(GARDEN)
    h = masterplan.hint(m, "garden", traits=GARDEN, profile=PROFILE)
    fd = district(m, "farms")
    assert (h["elev_lo"], h["elev_hi"]) == (fd["lo"], fd["hi"]) and "customs" not in h, (h, fd)
    md = memory(DEFAULT)
    h = masterplan.hint(md, "garden", traits=DEFAULT, profile=PROFILE)
    hd = district(md, "halls")
    assert (h["elev_lo"], h["elev_hi"]) == (hd["lo"], hd["hi"]), (h, hd)


@test("gardens: the soil floor rule finishes them (both sides list garden)")
def _():
    assert "garden" in planner_construct.SOIL_FLOOR_KINDS
    src = (ROOT / "lua" / "ai-builder-rooms.lua").read_text(encoding="utf-8")
    block = re.search(r"SOIL_FLOOR_KINDS = \{[^}]*\}", src).group(0)
    assert "garden = true" in block, block
    m = Memory()
    s = {"projects": {"decorating": [{"id": 7, "kind": "garden"}, {"id": 8, "kind": "storage"}],
                      "soil_floors": [{"project_id": 7, "tiles": 40}]}}
    assert planner_construct._soil_candidates(s, m, CFG) == [(7, "garden", 40)]


@test("gardens: sooner by Agriculture (the pace and the ladder); a default fort as before")
def _():
    assert G.garden_pace({}, CFG) == 1.0 and G.garden_pace({"agriculture": -100}, CFG) == 1.0
    assert 1.7 < G.garden_pace(GARDEN, CFG) < 1.8
    YEAR = 336 * 1200
    s = {"dwarves": {"total": 40}, "stocks": {"prepared_meals": 2000, "drink": 200}, "date": {"year": 160, "tick": 0},
         "others_on_map": {}, "jobs": {}}
    m = Memory()
    m.last_garden_tick = 160 * YEAR - int(1.2 * YEAR)    # 1.2 years ago
    with Patched(planner_growth, young_fort=lambda *a: False, _idle_share=lambda s: 0.5):
        m.last_garden_tick = 160 * YEAR - 2 * YEAR
        assert planner_growth.good_times(s, m, GARDEN, CFG)                         # (the rest of good times holds)
        m.last_garden_tick = 160 * YEAR - int(1.2 * YEAR)
        assert not planner_growth.good_times(s, m, GARDEN, CFG)                     # Grandeur alone: 1.5 years
        assert planner_growth.good_times(s, m, GARDEN, CFG, pace=G.garden_pace(GARDEN, CFG))   # ~0.87 years
    a = {"type": "start_project", "kind": "garden"}
    assert abs(planner_growth.ladder_score(a, {}, GARDEN, CFG)
               - planner_growth.ladder_score(a, {}, {"grandeur": 40}, CFG) - 1.2) < 1e-9


# --- 2. the garden court: the brain -------------------------------------------------------------

def court_state(**kw) -> dict:
    s = {"dwarves": {"total": 40}, "date": {"year": 160, "tick": 0}, "stocks": {"blocks": 80, "boulders": 20},
         "others_on_map": {}, "settings": {}, "buildings": {}, "garden_court": {}}
    s.update(kw)
    return s


@test("court: wanted by Agriculture, Grandeur and Surface (the Garden fort); not the others, never hidden")
def _():
    assert G.court_wanted(GARDEN, CFG)
    for name, t in PRESETS.items():
        if name != "Garden fort":
            assert not G.court_wanted(t, CFG), name
    assert not G.court_wanted(dict(GARDEN, surface=-100), CFG)
    assert not G.court_wanted(dict(GARDEN, outsiders=-150, caution=40), CFG)          # hidden_hold
    assert not G.court_wanted(dict(GARDEN, grandeur=0), CFG)
    # a design wish (nature lovers) above a low Surface
    m = Memory()
    m.culture = {"design": {"mode": "guided", "lang": {"landmarks": [{"kind": "garden_court"}]}}}
    assert G.court_wanted({}, CFG, m) and not G.court_wanted({"surface": -60}, CFG, m)


@test("court: the rule proposes one stage, with the sliders' options; waits, holds and stops as it should")
def _():
    m = Memory()
    with Patched(G, young_fort=lambda *a: False):
        props, notes = [], []
        G._garden_court_rule(court_state(), CFG, 40, GARDEN, props, notes, m, {})
        assert len(props) == 1 and props[0].rule == "garden_court", (props, notes)
        a = props[0].action
        assert a["type"] == "place_garden_court" and a["paths"] is True and a["statues"] == 4, a
        assert re.match(r"^[A-Za-z' ]{1,40}$", a["name"]), a
        # the default fort: nothing
        props = []
        G._garden_court_rule(court_state(), CFG, 40, DEFAULT, props, [], m, {})
        assert not props
        # the keep being built: waits (one building above ground at a time)
        props, notes = [], []
        G._garden_court_rule(court_state(buildings={"keep": {"stage": "walls"}}), CFG, 40, GARDEN, props, notes, m, {})
        assert not props and any("waits for the keep" in n for n in notes), notes
        # no material
        props, notes = [], []
        G._garden_court_rule(court_state(stocks={"blocks": 3}), CFG, 40, GARDEN, props, notes, m, {})
        assert not props and any("building material" in n for n in notes), notes
        # its walls waiting to be built: a note, no proposal; then the next stage
        props, notes = [], []
        G._garden_court_rule(court_state(garden_court={"stage": "walls", "walls_planned": 9}), CFG, 40, GARDEN,
                             props, notes, m, {})
        assert not props and any("9 wall tile" in n for n in notes), notes
        props = []
        G._garden_court_rule(court_state(garden_court={"stage": "walls", "walls_planned": 0},
                                         buildings={"keep": {"stage": "walls"}}), CFG, 40, GARDEN, props, [], m, {})
        assert len(props) == 1 and "beds" in props[0].reason, props       # (begun: no wait for the keep)
        props = []
        G._garden_court_rule(court_state(garden_court={"stage": "done", "done": True}), CFG, 40, GARDEN, props, [], m, {})
        assert not props
        # the Rules tab's construction switch off, a threat: quiet
        props = []
        G._garden_court_rule(court_state(settings={"construct": False}), CFG, 40, GARDEN, props, [], m, {})
        assert not props
        props = []
        G._garden_court_rule(court_state(others_on_map={"threats_that_can_reach_dwarves": 2}), CFG, 40, GARDEN,
                             props, [], m, {})
        assert not props
        props = []
        G._garden_court_rule(court_state(), CFG, 10, GARDEN, props, [], m, {})      # too small a fort
        assert not props


@test("court: the design track's garden_court landmark goes to the court (not dropped), and is not wished again")
def _():
    m = Memory()
    m.atlas = {}
    lm = planner_design.landmarks_of(m, create=True)
    e = {"id": 1, "kind": "garden_court", "name": "The Green Court", "status": "due", "by": "library"}
    lm["list"].append(e)
    notes = []
    planner_design._fallback({}, e, m, GARDEN, 0, [], notes)
    assert e["status"] == "court" and any("garden court" in n for n in notes), (e, notes)
    assert G.court_wished(m)
    lang = {"landmarks": [{"kind": "garden_court"}]}
    w = planner_design._wish(lang, m, GARDEN)
    assert w is None or w["kind"] != "garden_court", w
    # underground only: dropped as before
    e2 = {"id": 2, "kind": "garden_court", "name": "The Deep Court", "status": "due", "by": "library"}
    planner_design._fallback({}, e2, m, {"surface": -100}, 0, [], [])
    assert e2["status"] == "dropped", e2


@test("wiring: the action, its dry run, label, co-pilot ask, the section and its default, the holds")
def _():
    hub = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert re.search(r"^\s+place_garden_court = function\(a\)", hub, re.M)
    assert "'place_garden_court'," in hub.split("DRY_OK = {}")[1].split("}) do DRY_OK")[0]
    assert re.search(r"^\s+garden_court = function\(\) return safe\(", hub, re.M)
    assert "garden_court" in SECTION_DEFAULTS
    import overseer
    assert "place_garden_court" in overseer.ACTION_WORDS if hasattr(overseer, "ACTION_WORDS") else True
    src = py_family_src("overseer")
    assert '"place_garden_court": "' in src
    assert "place_garden_court" in overseer.BIG_MOVES
    import planner_recovery
    assert "place_garden_court" in planner_recovery.HOLD_TYPES
    parts = re.search(r"^PARTS = \{(.*?)\}", (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"), re.S | re.M)
    assert "'court'" in parts.group(1)


# --- 2. the garden court: the Lua side ----------------------------------------------------------

def _string_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


HARNESS = _string_assign(ROOT / "tests" / "test_builder.py", "HARNESS")
LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
LAY = LUA.globals().LAYOUTS
T = LUA.table_from
LUA.execute("df = df or {}; df.global = df.global or {}; df.global.world = df.global.world or {}")
LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}")
SAVED = {k: B[k] for k in ("pasture_anchors", "surface_farm_spots", "hall_planned_at", "hall_free_items",
                           "fell_tree", "deep_depot_mouth")}


def lua_reset():
    W.reset()
    for k, v in SAVED.items():
        B[k] = v
    B.CACHE = None
    B.pasture_anchors = LUA.eval("function() return {{x = 60, y = 60, z = 80}} end")
    B.surface_farm_spots = LUA.eval("function() return {{x = 90, y = 60, z = 80}} end")
    B.hall_planned_at = LUA.eval("function() return false end")
    B.hall_free_items = LUA.eval("function() return 0 end")
    B.deep_depot_mouth = LUA.eval("function() return {} end")
    B.fell_tree = LUA.eval("function(x, y, z) W_FELLED = (W_FELLED or 0) + 1 return true end")
    # open soil under the sky round the field at x90 y60 (z80), rock ground in a strip
    for x in range(64, 110):
        for y in range(40, 81):
            W.set(x, y, 80, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 81, T({"shape": "EMPTY", "outside": True}))
    W.set(90, 60, 80, T({"taken": True}))                  # the field's own plot


def lua_test(name):
    def deco(fn):
        def run():
            _reset_py()
            lua_reset()
            fn()
        return test(name)(run)
    return deco


def pts(lst):
    return [(p.x, p.y) for p in lst.values()]


@lua_test("layout: the court at r 5: a ring of 40, four 3x3 beds, a cross of paths, statues and seats apart")
def _():
    L = LAY.garden_court(T({"r": 5, "paths": True, "statues": 4}))
    ring, paths, statues, seats = pts(L.ring), pts(L.paths), pts(L.statues), pts(L.seats)
    assert len(ring) == 40 and len(set(ring)) == 40
    assert all(max(abs(x), abs(y)) == 5 for x, y in ring)
    beds = [(b.x, b.y, b.w, b.h) for b in L.beds.values()]
    assert sorted(beds) == [(-4, -4, 3, 3), (-4, 2, 3, 3), (2, -4, 3, 3), (2, 2, 3, 3)], beds
    bed_tiles = {(x, y) for bx, by, w, h in beds for x in range(bx, bx + w) for y in range(by, by + h)}
    assert len(paths) == 17 and all(x == 0 or y == 0 for x, y in paths)
    assert len(statues) == 4 and len(seats) == 8
    used = [set(paths), set(statues), set(seats), bed_tiles]
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            assert not used[i] & used[j], (i, j, used[i] & used[j])
    assert all(max(abs(x), abs(y)) <= 4 for s_ in used for x, y in s_)
    # r 4: 2x2 beds, no side seats; statues as asked; r clamped; no paths unless asked
    L4 = LAY.garden_court(T({"r": 4, "statues": 1}))
    assert [(b.w, b.h) for b in L4.beds.values()] == [(2, 2)] * 4 and len(pts(L4.statues)) == 1
    assert len(pts(L4.seats)) == 4 and len(pts(L4.paths)) == 0
    assert LAY.garden_court(T({"r": 20})).r == 6 and LAY.garden_court(None).r == 4


@lua_test("builder: a site by the fields, off the way in; the stages to the meeting area; a dry run changes nothing")
def _():
    s = B.find_garden_court_site()
    assert s, s
    assert s.r == 5 and s.z == 80 and s.soil == 81, (s.x, s.y, s.r, s.soil)
    assert abs(s.x - 60) > 8 or abs(s.y - 60) > 8                         # the wagons' road kept
    assert max(abs(s.x - 90), abs(s.y - 60)) <= 8, (s.x, s.y)              # by the field
    assert not (abs(s.x - 90) <= 5 and abs(s.y - 60) <= 5)                 # never over the field
    r = B.place_garden_court(True, T({"name": "Rose", "paths": True, "statues": 4}))
    assert r.ok and r.stage == "walls" and r.dry_run, dict(r)
    assert len(W.placed) == 0 and not W.persist["ai-overseer/garden_court"]
    r = B.place_garden_court(False, T({"name": "Rose", "paths": True, "statues": 4}))
    assert r.ok and r.stage == "walls" and r.walls == 40, dict(r)          # 39 walls and the door
    texts = [p.text for p in W.placed.values()]
    assert texts.count("Cw") == 39 and texts.count("d") == 1, texts
    st = B.garden_court_status()
    assert st.stage == "walls" and st.walls_planned == 0 and st.elevation == 80 + B.OFFSET, dict(st)
    # a wall waiting to be built: the next step waits
    c = W.persist["ai-overseer/garden_court"]
    ring0 = next(t for t in c.tiles.values() if t.t == "Cw")
    W.set(ring0.x, ring0.y, 80, T({"building": True}))
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert not r.ok and r.waiting and r.stage == "walls", dict(r)
    W.set(ring0.x, ring0.y, 80, T({"building": False}))
    n0 = len(W.placed)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "beds" and r.beds == 4 and r.paths == 17, dict(r)
    new = [p.text for p in list(W.placed.values())[n0:]]
    assert new.count("p(3x3)") == 4 and new.count("Cf") == 17, new
    B.hall_free_items = LUA.eval("function() return 2 end")              # two statues lie free
    n0 = len(W.placed)
    r = B.place_garden_court(False, T({"name": "Rose", "statues": 4}))
    assert r.ok and r.stage == "furnish" and r.statues == 2 and r.seats >= 7, dict(r)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "done" and r.zone, dict(r)
    zone = [p for p in W.placed.values() if p.mode == "zone"]
    assert len(zone) == 1 and zone[0].text == 'm{name="The Rose Garden Court"}(9x9)', [z.text for z in zone]
    st = B.garden_court_status()
    assert st.done and st.blocks_needed == 0 and st.walls_left == 39, dict(st)   # (the stub builds nothing)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert not r.ok and r.done


@lua_test("builder: no beds on rock, trees inside kept, the ring's trees felled first; the hall keeps clear of it")
def _():
    # rock ground over the whole open area: no beds; paths on rock are left as they are
    for x in range(64, 110):
        for y in range(40, 81):
            W.set(x, y, 80, T({"material": "STONE"}))
    s = B.find_garden_court_site()
    assert s and s.soil == 0
    r = B.place_garden_court(False, T({"name": "Stone", "paths": True}))
    assert r.ok and r.stage == "walls"
    r = B.place_garden_court(False, T({"name": "Stone", "paths": True}))
    assert r.ok and r.beds == 0 and r.paths == 0, dict(r)
    rect = B.court_rects()[1]
    assert (rect.x2 - rect.x1, rect.y2 - rect.y1) == (10, 10)
    h = B.find_hall_site("field_hall")                    # the surface hall keeps 3 tiles from the court
    assert h, h
    gap = max(rect.x1 - h.x2, h.x1 - rect.x2, rect.y1 - h.y2, h.y1 - rect.y2)
    assert gap > 3, (gap, (h.x1, h.y1, h.x2, h.y2), (rect.x1, rect.y1, rect.x2, rect.y2))
    # a fresh court with a tree on the ring's line: the open ground just 13 by 13
    lua_reset()
    for x in range(64, 110):
        for y in range(40, 81):
            if not (66 <= x <= 78 and 50 <= y <= 62):
                W.set(x, y, 80, T({"outside": False}))
    B.surface_farm_spots = LUA.eval("function() return {{x = 72, y = 64, z = 80}} end")
    for x in (76, 77, 78):                                 # every site's east wall meets one of them
        W.set(x, 58, 80, T({"shape": "TRUNK_BRANCH", "material": "TREE"}))
    s = B.find_garden_court_site()
    assert s and s.r == 5 and len(s.trees) == 1, s and (s.x, s.y, s.r)
    assert s.kept == (s.x + s.r) - 76, (s.x, s.kept)           # the ones inside are kept
    tx, ty = s.trees[1].x, s.trees[1].y
    LUA.execute("W_FELLED = 0")
    r = B.place_garden_court(False, T({"name": "Oak"}))
    assert r.ok and r.stage == "clearing" and r.trees >= 1 and LUA.eval("W_FELLED") >= 1, dict(r)
    r = B.place_garden_court(False, T({"name": "Oak"}))
    assert not r.ok and r.waiting and r.stage == "clearing", dict(r)
    W.set(tx, ty, 80, T({"shape": "FLOOR", "material": "SOIL"}))
    r = B.place_garden_court(False, T({"name": "Oak"}))
    assert r.ok and r.stage == "walls", dict(r)


@lua_test("builder: names checked; no site without open ground or anchors")
def _():
    r = B.place_garden_court(False, T({"name": "Rose<1>"}))
    assert not r.ok and r.rejected
    B.pasture_anchors = LUA.eval("function() return {} end")
    s, why = B.find_garden_court_site()
    assert s is None and "no surface entrance" in why
    lua_reset()
    for x in range(64, 110):
        for y in range(40, 81):
            W.set(x, y, 81, T({"shape": "FLOOR", "outside": False}))       # all roofed over
    s, why = B.find_garden_court_site()
    assert s is None and "no site for the garden court" in why, why


@lua_test("bridge: place_garden_court checks its arguments before the builder is called")
def _():
    hub = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    body = re.search(r"place_garden_court = function\(a\)\n(.*?)\n    end,", hub, re.S).group(1)
    env = LUA.eval("function(body) local calls = {}\n"
                   "local env = setmetatable({reject = function(w) return {ok = false, rejected = true, error = w} end,"
                   " reqscript = function() return {place_garden_court = function(d, o) table.insert(calls, {d, o})"
                   " return {ok = true, dry_run = d} end} end}, {__index = _G})\n"
                   "local f = assert(load('return function(a)\\n' .. body .. '\\nend', 'act', 't', env))()\n"
                   "return f, calls end")
    f, calls = env(body)
    assert f(T({"name": "Rose", "paths": True, "statues": 2, "dry_run": True})).dry_run
    o = calls[1][2]
    assert (o.name, o.paths, o.statues) == ("Rose", True, 2)
    for bad in ({"name": "R0se"}, {"paths": "yes"}, {"statues": 9}, {"statues": 1.5}):
        r = f(T(bad))
        assert not r.ok and r.rejected, bad


if __name__ == "__main__":
    finish()
