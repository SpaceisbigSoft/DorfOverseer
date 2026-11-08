"""(0.105.30, construction seams) The joins between the five construction
groups and the deep depot fix, once merged:

1. the hall's options (windows, block floor, statue) decided by the brain's
   sliders and passed through the bridge, checked;
2. the keep's `stair` stage understood by _keep_rule (it waits, with a note);
3. the Rules switch `construct`: settings, sanitize, for_ai, the window,
   player_rules, docs;
4. the wing walls recorded on the entrance's saved data and counted as
   ai.wings, not gate pieces;
5. find_surface_rect's spacing from a way in a level down, with the deep
   depot's road;
6. every construction action the brain proposes: ACTIONS, its parameters,
   a label, DRY_OK; the gate styles and GAP.

    python tests/test_construct_seams.py
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
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import overseer  # noqa: E402
import planner_construct as pc  # noqa: E402
from planner import Memory, plan  # noqa: E402
from planner_core import PLANNER_CONFIG, Proposal, refusal_key, player_rules  # noqa: E402
from planner_industry import _keep_rule  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
import test_preset as TP  # noqa: E402  (the bridge with a stub DFHack; its tests don't run on import)

LUA_DIR = ROOT / "lua"
CFG = PLANNER_CONFIG
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
GARDEN = {"agriculture": 120, "husbandry": 80, "surface": 80, "welfare": 40, "grandeur": 40}
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
BRIDGE_ACTIONS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
HUB = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
GATES_SRC = (LUA_DIR / "ai-gates.lua").read_text(encoding="utf-8")


def fort(traits=None) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits or {})
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["stocks"]["blocks"] = 400
    return s


def keep_refused(m: Memory, n: int = 3) -> Memory:
    m.refusals[refusal_key(Proposal("keep", {"type": "place_keep"}, "", 7))] = {"n": n, "until": 0, "at": 0}
    return m


def hall(s, traits, m=None, rules_=None):
    ps, notes = [], []
    pc._hall_rule(s, CFG, s["dwarves"]["total"], traits, ps, notes, m if m is not None else keep_refused(Memory()),
                  rules_)
    return [p.action for p in ps if p.action.get("type") == "place_hall"], notes


def _harness(path: str, name: str = "HARNESS") -> str:
    tree = ast.parse((ROOT / "tests" / path).read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


# --- 1. the hall's options --------------------------------------------------------

@test("hall options: windows and a statue at Grandeur 40+, a block floor at Craftsmanship 40+; none below")
def _():
    for g, c, want in ((40, 0, (True, False, True)), (39, 40, (False, True, False)),
                       (60, 60, (True, True, True)), (0, 39, (False, False, False))):
        traits = dict(GARDEN, grandeur=g, craftsmanship=c)
        acts, _ = hall(fort(traits), traits)
        assert acts == [{"type": "place_hall", "kind": "field_hall", "windows": want[0], "floor": want[1],
                         "statue": want[2]}], (g, c, acts)
    assert CFG["hall_windows_grandeur"] == 40 and CFG["hall_statue_grandeur"] == 40
    assert CFG["hall_floor_craftsmanship"] == 40


BL = LuaRuntime(unpack_returned_tuples=True)
BH = BL.execute(_harness("test_hygiene_bridge.py"), HUB, str(LUA_DIR))


def bt(d):
    if isinstance(d, dict):
        return BL.table_from({k: bt(v) for k, v in d.items()})
    return d


@test("hall options: the bridge passes windows, floor and statue on as true/false; anything else is refused")
def _():
    BH.scripts = BL.table()
    BH.halted = False
    M = BH.module()
    BH.scripts["ai-builder"] = BL.eval("""{place_hall = function(kind, dry, opts)
        return {ok = true, kind = kind, dry_run = dry, windows = opts.windows, floor = opts.floor,
                statue = opts.statue} end}""")
    r = BH.act(M, bt({"type": "place_hall", "kind": "field_hall", "windows": True, "floor": False,
                      "statue": True}))
    assert r.ok and r.windows is True and r.floor is False and r.statue is True and r.dry_run is False, dict(r)
    r = BH.act(M, bt({"type": "place_hall", "kind": "market_hall", "dry_run": True}))
    assert r.ok and r.windows is False and r.floor is False and r.statue is False and r.dry_run is True, dict(r)
    for bad in ({"windows": "yes"}, {"floor": 1}, {"statue": {}}):
        r = BH.act(M, bt(dict({"type": "place_hall", "kind": "field_hall"}, **bad)))
        assert not r.ok and r.rejected and "true or false" in r.error, (bad, dict(r))


# --- 2. the keep's stair stage ----------------------------------------------------

def keep(k):
    s = fort(GARDEN)
    s["buildings"]["keep"] = k
    ps, notes = [], []
    _keep_rule(s, CFG, s["dwarves"]["total"], GARDEN, ps, notes, Memory())
    return [p for p in ps if p.action.get("type") == "place_keep"], notes


@test("keep: while its stair is planned it waits with a note; built, the roof goes on (not 'its roof is built')")
def _():
    ps, notes = keep({"stage": "stair", "stair_planned": 1, "roof_planned": 1, "walls_planned": 0})
    assert not ps and any("stair up to the roof is still to build" in n for n in notes), (ps, notes)
    ps, notes = keep({"stage": "stair", "stair_planned": 1})              # roof_planned left out
    assert not ps and any("stair" in n for n in notes), notes
    ps, notes = keep({"stage": "stair", "stair_planned": 0, "roof_planned": 0})
    assert len(ps) == 1 and "stair up to its roof is built" in ps[0].reason, ps
    assert "call it finished" not in ps[0].reason
    ps, notes = keep({"stage": "roof", "roof_planned": 3})
    assert not ps and any("3 roof tile(s) still to build" in n for n in notes), notes
    ps, _ = keep({"stage": "roof", "roof_planned": 0})
    assert len(ps) == 1 and "its roof is built" in ps[0].reason
    assert "stair" in pc.KEEP_OPEN


# --- 3. the Rules switch `construct` ----------------------------------------------

@test("construct switch: player_rules on by default; off in the settings or the rules, no hall")
def _():
    s = fort(GARDEN)
    assert player_rules(s)["construct"] is True
    acts, _ = hall(s, GARDEN)
    assert acts
    s["settings"]["construct"] = False
    assert player_rules(s)["construct"] is False
    assert hall(s, GARDEN)[0] == []
    assert "Rules tab" in pc.construct_quiet(s, Memory(), GARDEN, CFG)
    s2 = fort(GARDEN)
    assert hall(s2, GARDEN, rules_={"construct": False})[0] == []
    ps, _ = plan(s, keep_refused(Memory()))
    assert not [p for p in ps if p.action.get("type") in ("place_hall", "build_wings", "floor_rooms")]


def lua_list(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)]


@test("construct switch: default on, kept by sanitize and for_ai; set_rules takes it")
def _():
    TP.reset()
    S = TP.H.settings()
    d = S.defaults()
    assert d.construct is True and S.for_ai(d).construct is True
    assert S.sanitize(TP.t({"construct": False})).construct is False
    assert S.for_ai(S.sanitize(TP.t({"construct": False}))).construct is False
    assert S.sanitize(TP.t({"construct": "no"})).construct is False      # (as every switch: only true is on)
    assert S.sanitize(TP.t({})).construct is True
    r = TP.act({"type": "set_rules", "rules": {"construct": False}})
    assert r.ok and TP.saved().construct is False, dict(r)
    TP.reset()


def rules_frames():
    """(row, l, w, view) of the Rules page's controls before the military
    section, with the window's numbers (9 optional levels, the jail 8th, the
    hospital 2nd: t = 15)."""
    src = GUI[GUI.index("function RulesPage:init()"):GUI.index("t = t + 11")]
    jrow, hrow, t = 8, 2, 15
    out = []
    for m in re.finditer(r"view_id = '(\w+)',\s*frame = \{t = ([^,]+), l = (\d+), w = (\d+)\}", src):
        view, expr, l, w = m.group(1), m.group(2).strip(), int(m.group(3)), int(m.group(4))
        rows = []
        if " + i" in expr:
            for i in (1, 2, 3):
                rows.append(eval(expr, {"jrow": jrow, "hrow": hrow, "t": t, "i": i}))
        else:
            rows.append(eval(expr, {"jrow": jrow, "hrow": hrow, "t": t}))
        for r in rows:
            out.append((r, l, w, view))
    for m in re.finditer(r"widgets\.Label\{frame = \{t = ([^,]+), l = (\d+)\}, text = \{\s*\{text = '([^']*)'", src):
        expr = m.group(1).strip()
        if "i" in expr.split("+")[-1] and "t +" not in expr:
            continue
        r = eval(expr, {"jrow": jrow, "hrow": hrow, "t": t})
        out.append((r, int(m.group(2)), len(m.group(3)), "label"))
    return out


@test("construct switch: the Rules tab's toggle, set and refreshed, in a free row of the right-hand column")
def _():
    assert code_has(GUI, "view_id = 'construct'") and code_has(GUI, "p:set_field('construct', v)")
    assert code_has(GUI, "self.subviews.construct:setOption(s.construct ~= false, false)")
    m = re.search(r"view_id = 'construct',.*?label = '([^']*)',\s*label_width = (\d+)", GUI, re.S)
    assert m and len(m.group(1)) <= int(m.group(2)), m and m.groups()
    frames = rules_frames()
    mine = [f for f in frames if f[3] == "construct"]
    assert len(mine) == 1, frames
    r, l, w, _ = mine[0]
    for r2, l2, w2, v in frames:
        if v != "construct" and r2 == r:
            assert l2 + w2 <= l or l + w <= l2, (v, r2, l2, w2, mine)
    assert l + w <= 118
    doc = (ROOT / "docs" / "controls.md").read_text(encoding="utf-8")
    assert "`construct`" in doc and "Construct halls, gate wings, floors" in doc


# --- 4. the wings, recorded and counted ---------------------------------------------

GL = LuaRuntime(unpack_returned_tuples=True)
GM, GW = GL.execute(_harness("test_construct_gates.py", "GATES_HARNESS"), module_src("ai-gates.lua"))
GL.execute("PERSIST = {}")
GL.eval("""function(M) M.dfhack = {persistent = {
    getSiteData = function(k, d) local v = PERSIST[k]; if v == nil then return d end; return v end,
    saveSiteData = function(k, v) PERSIST[k] = v end}} end""")(GM)


def gset_map(levels, width=40, height=19):
    m = GL.table()
    for z, rows in levels.items():
        lvl = GL.table()
        for y, r in enumerate(rows):
            lvl[y] = r
        m[z] = lvl
    GW.map = m
    GW.size = GL.table_from({1: width, 2: height})
    GW.keepouts = GL.table()


def gatehouse_fort():
    width = 40
    surface = ["o" * width] * 8 + ["o" * 10 + "t" + "o" * (width - 11)] + ["o" * width] * 10
    below = (["#" * width] * 8 + ["#" * 10 + "s" + "." * (width - 11)] + ["#" * 10 + "." * (width - 10)] * 4
             + ["#" * width] * 6)
    gset_map({0: below, 1: surface}, width)
    starts = GL.table_from({i + 1: GL.table_from({"x": 30 + i, "y": 10, "z": 0}) for i in range(3)})
    GW.buildings = GL.table_from({
        1: GL.table_from({"id": 7, "kind": "hatch", "x1": 10, "y1": 8, "x2": 10, "y2": 8, "z": 1, "name": ""}),
        2: GL.table_from({"id": 40, "kind": "bridge", "x1": 10, "y1": 3, "x2": 10, "y2": 3, "z": 1,
                          "name": "AI gatehouse bridge"})})
    return starts


def scan(starts):
    es, _, _ = GM.find_entrances(starts, GW.buildings)
    e = es[1]
    e.id = 1
    GM.GATES = GL.table_from({"scanned": False, "entrances": GL.table_from({1: e})})
    return e


@test("wings: build_wings records its tiles on the entrance's saved data; a new scan puts them back; the summary says so")
def _():
    GL.execute("PERSIST = {}")
    starts = gatehouse_fort()
    e = scan(starts)
    assert e.gatehouse == "standing" and e.wing_pieces is None
    GM.place_hook = lambda text, pos: True
    try:
        assert GM.build_wings(1, True).ok
        assert GL.globals().PERSIST["ai-overseer/wings"] is None          # a dry run records nothing
        r = GM.build_wings(1, False)
        assert r.ok and r.walls == 10, dict(r)
    finally:
        GM.place_hook = None
    rec = GL.globals().PERSIST["ai-overseer/wings"]
    spot = f"{e.x},{e.y},{e.z}"
    got = sorted(rec[spot][i] for i in range(1, len(rec[spot]) + 1))
    assert got == sorted(r.pieces[i] for i in range(1, 11)) and len(got) == 10, got
    assert len(e.wing_pieces) == 10
    e2 = scan(starts)                                   # a later scan (or a reload): the record comes back
    assert e2.wing_pieces is not None and len(e2.wing_pieces) == 10
    s = GM.GATES_ORIG.summary() if GM.GATES_ORIG else GM.summary()
    assert s.entrances[1].wings == "standing", dict(s.entrances[1])
    # built again: no tile twice
    GM.place_hook = lambda text, pos: True
    try:
        GM.build_wings(1, False)
    finally:
        GM.place_hook = None
    assert len(GL.globals().PERSIST["ai-overseer/wings"][spot]) == 10
    GM.GATES = GL.table_from({"scanned": False})


CL = LuaRuntime(unpack_returned_tuples=True)
_rep = (ROOT / "tests" / "test_construct_report.py").read_text(encoding="utf-8")
CW = CL.execute(re.search(r'FAKE = r"""(.*?)"""', _rep, re.S).group(1),
                (LUA_DIR / "ai-constructions.lua").read_text(encoding="utf-8"))


def ct(d):
    if isinstance(d, dict):
        return CL.table_from({k: ct(v) for k, v in d.items()})
    if isinstance(d, list):
        return CL.table_from([ct(v) for v in d])
    return d


@test("wings: the saved record counts as ai.wings, not as gate pieces, though in the gate's box and before a scan")
def _():
    CW.reset()
    CW.persist["ai-overseer/wings"] = ct({"100,100,80": ["103,100,80", "104,100,80"]})
    CW.scripts["ai-gates"] = ct({"GATES": {"entrances": [
        {"id": 1, "kind": "surface", "x": 100, "y": 100, "z": 80, "width": 1}]}})
    CW.scripts["ai-builder"] = CL.eval("{registry_report = function() return {} end}")
    CW.con(103, 100, 80, 1, 1, False)            # wing walls, inside the gate's box
    CW.con(104, 100, 80, 1, 1, False)
    CW.con(99, 100, 80, 1, 1, False)             # a gate wall
    a = CW.env.survey(True).ai
    assert a.wings == 2 and a.gate_pieces == 1, (a.wings, a.gate_pieces)
    CW.scripts["ai-gates"] = ct({"GATES": {}})   # no scan this session: still counted
    a = CW.env.survey(True).ai
    assert a.wings == 2, a.wings


# --- 5. find_surface_rect and the deep depot's road ----------------------------------

LB = LuaRuntime(unpack_returned_tuples=True)
LB.globals().LUA_DIR = str(LUA_DIR)
B, BW = LB.execute(_harness("test_builder.py"), (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
B.DEEP_DEPOT_SECONDS = 20
B.DEEP_WAGON_SECONDS = 10
LB.execute("WAGON_BLD = {}; ANCH = {{x = 60, y = 60, z = 80}}")
LB.eval("""function(B)
  B.wagon_building = function(x, y, z) return WAGON_BLD[x .. ',' .. y .. ',' .. z] end
  B.pasture_anchors = function() return ANCH end
  B.elevation_offset = function() return 0 end
end""")(B)


@test("spacing: with the depot road dug and its way in a level down, the surface spots keep min_d from it; the road goes on")
def _():
    BW.reset()
    LB.execute("df = df or {}; df.global = {cur_year = 250, cur_year_tick = 0, "
               "world = {buildings = {other = {TRADE_DEPOT = {}}}}}; ANCH = {{x = 60, y = 60, z = 80}}")
    LB.eval("""function(W) for x = 0, 119 do for y = 0, 119 do
      local t = W.get(x, y, 80)
      if t.shape == 'WALL' then W.set(x, y, 80, {shape='FLOOR', material='SOIL', outside=true}) end
      W.set(x, y, 81, {shape='EMPTY', outside=true}) end end end""")(BW)
    r = B.place_deep_depot(False)
    assert r.ok and r.stage == "digging", dict(r)
    d = B.deep_depot_data()
    shape = {"h": "RAMP_TOP", "ramp": "RAMP", "d": "FLOOR"}
    tiles = [(t.x, t.y, t.z, t.r) for t in d.tiles.values()]
    for x, y, z, rr in tiles:
        BW.set(x, y, z, LB.table_from({"shape": shape[rr], "designated": False, "outside": rr == "h"}))
    mouth = {(t.x, t.y) for t in B.deep_depot_mouth().values()}
    ramp = sorted((x, y, z) for x, y, z, rr in tiles if rr == "ramp")[1]       # the road's way in, z79
    LB.globals().ANCH = LB.table_from([LB.table_from({"x": ramp[0], "y": ramp[1], "z": ramp[2]})])
    for w, h, md in ((5, 5, 6), (3, 3, 8), (3, 3, 6)):                         # refuse, dump, cages
        sp = B.find_surface_rect(w, h, md, LB.table(), B.GROUND)
        assert sp and sp.z == ramp[2] + 1, (w, h, md)
        rect = {(sp.x + i, sp.y + j) for i in range(w) for j in range(h)}
        assert not rect & mouth, (w, h, sorted(rect & mouth))
        near = min(max(abs(x - ramp[0]), abs(y - ramp[1])) for x, y in rect)
        assert near >= md, (w, h, md, near)
    p = B.place_deep_depot(False)
    assert p.ok and p.stage == "placed", dict(p)


# --- 6. every construction action, end to end -----------------------------------------

# what the brain sends, by action (planner_construct, planner_industry, planner_gates)
BRAIN_PARAMS = {"place_hall": ("kind", "windows", "floor", "statue"), "build_wings": ("entrance_id",),
                "floor_rooms": ("project_id",), "fortify_entrance": ("entrance_id", "style"),
                "place_keep": (), "deep_depot": ()}
DRY_RUN_BY_BRAIN = ("place_hall", "build_wings", "floor_rooms", "place_keep", "deep_depot")


def act_body(name: str) -> str:
    m = re.search(rf"^function {name}\(a\)\n(.*?)^end", BRIDGE_ACTIONS, re.S | re.M)
    assert m, name
    return m.group(1)


@test("actions: each construction action is in ACTIONS, reads the brain's parameters, has a label; DRY_OK where dry-run")
def _():
    BH.scripts = BL.table()
    M = BH.module()
    for t, params in BRAIN_PARAMS.items():
        assert BL.eval(f"function(M) return type(M.ACTIONS.{t}) == 'function' and M.ACTIONS.{t} == M.act_{t} end")(M), t
        body = act_body(f"act_{t}")
        for k in params:
            if t == "place_hall" and k in ("windows", "floor", "statue"):
                assert "HALL_OPTS" in body and k in BRIDGE_ACTIONS[BRIDGE_ACTIONS.index("HALL_OPTS = "):][:80], k
            else:
                assert f"a.{k}" in body, (t, k)
        words = overseer.short(dict({"type": t}, **{k: 1 for k in params}))
        assert words and not words.startswith(t) and words != t, (t, words)
    for t in DRY_RUN_BY_BRAIN:
        assert M.DRY_OK[t] is True, t
    assert {"place_hall", "build_wings", "deep_depot"} <= overseer.BIG_MOVES
    assert overseer.short({"type": "fortify_entrance", "style": "sealed"}) == "wall a narrow cavern opening shut"
    assert "drawbridge" in overseer.short({"type": "fortify_entrance", "style": "wagon"})
    # the brain's proposals carry exactly those parameters
    acts, _ = hall(fort(GARDEN), GARDEN)
    assert set(acts[0]) - {"type"} == set(BRAIN_PARAMS["place_hall"]), acts


@test("gate styles: the bridge's GATE_STYLES and ai-gates GAP both hold wagon and sealed, and the same styles")
def _():
    m = re.search(r"local GATE_STYLES = \{(.*?)\}", BRIDGE_ACTIONS, re.S)
    styles = set(re.findall(r"(\w+) = true", m.group(1)))
    gap = set(re.findall(r"(\w+) = \d", re.search(r"^GAP = \{(.*?)\}", GATES_SRC, re.S | re.M).group(1)))
    assert {"wagon", "sealed"} <= styles and {"wagon", "sealed"} <= gap, (styles, gap)
    assert styles == gap, (styles ^ gap)
    assert GM.GAP.wagon == 3 and GM.GAP.sealed == 0
    for st in ("wagon", "sealed"):
        assert f"|{st}" in act_body("act_fortify_entrance"), st


@test("Lua 5.3: every file touched by the seams compiles")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for name in ("ai-bridge-actions.lua", "ai-gates.lua", "ai-constructions.lua", "ai-overseer-settings.lua",
                 "gui/ai-overseer.lua", "ai-builder-halls.lua", "ai-builder-surface.lua", "ai-bridge.lua"):
        ok = chk((LUA_DIR / name).read_text(encoding="utf-8"), name)
        assert ok[0], (name, ok)


if __name__ == "__main__":
    finish()
