"""(D0 merge) Where the Design track's seven groups meet, checked on the
merged tree:

- G6's site / validate / start / build path on the real G5 ai-blueprints
  (G6 was written against a stand-in), the two agreeing on the turn (q
  quarter turns clockwise, y south), and a refusal's position on a turned
  drawing;
- G2's six library landmarks through G5's Lua and Python check_format and
  to_layouts, then G6's validate_landmark and the builder's check_site on
  the fake fort;
- G1 + G2 + G3 + G4 at Scripts: plan()'s proposals and the layouts they make
  byte-identical to main's (git archive main) over the fixtures, and the
  layouts snapshot is main's; at Guided a level carries the new style keys
  and G4's parse_style takes them;
- G7's loop end to end at Guided and Architect with design_ai off (library
  landmarks): the brain's actions run by the real bridge part
  (ai-bridge-design.lua) and builder on the fake fort, the game the only fake;
- the guarded tests of G2 and G5 run (no SKIPPED);
- G3's settings: nothing saved reads Guided; settings saved before this round
  (no design key) read Scripts, through every saving path and into plan().

    python tests/test_d0_merge.py
"""

from __future__ import annotations

import atexit
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime, lua_type
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

sys.path.insert(0, str(ROOT / "brain"))

import test_d0_sites as S6        # G6's fake fort, on the real ai-blueprints  # noqa: E402
import test_preset as TP          # the bridge and the settings with a stub DFHack  # noqa: E402
import d0_layout_snapshot as SNAP  # noqa: E402

import blueprint  # noqa: E402
import design  # noqa: E402
import design_rules  # noqa: E402
import planner_design as PD  # noqa: E402
from planner import TICKS_PER_DAY, Memory, plan, record  # noqa: E402

LUA, B, W = S6.LUA, S6.B, S6.W
lt, lua_list, codes = S6.lt, S6.lua_list, S6.codes
NOW = S6.NOW
LUA_DIR = ROOT / "lua"
FIXTURES = ROOT / "tests" / "fixtures"
LIBRARY = blueprint.load_library()

test = make_test(before=S6._reset)        # the fake fort's tests
plain = make_test()                       # the rest


def py(v):
    """A Lua value as a Python one, nested (a table 1..n a list; an empty table a list)."""
    if lua_type(v) != "table":
        return v
    keys = list(v.keys())
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[i]) for i in range(1, len(keys) + 1)]
    return {k: py(x) for k, x in v.items()}


def tile_set(t) -> set:
    """A Lua {x = {y = true}} set as {(x, y)} (read in Lua: py() would take a column for a list)."""
    return {(x, y) for x, col in (t.items() if t is not None else []) for y in col.keys()}


def bpm():
    return B.blueprints()


def dug_symbol(s: str, ground: str) -> bool:
    if ground == "surface":
        return False
    return s in ".,@<>X^+*O" or bool(re.match(r"^[a-z]$", s))       # (E1) openings and rails are dug first


# --- 1. G6 on the real G5 ---------------------------------------------------------------

@test("G6 runs on the real lua/ai-blueprints.lua (not its stand-in)")
def _():
    assert S6.REAL_BLUEPRINTS
    M = bpm()
    for name in ("check_format", "cost", "rotate", "to_layouts", "BP_LIMITS", "ITEMS", "ALPHABET", "ZONES"):
        assert M[name] is not None, name
    assert M.ALPHABET.rock == "_#.,@<>X^+*O" and M.BP_LIMITS.cost_max == 2500      # (E1) '*' and 'O'


@test("the turn: G5's rotate/to_layouts and G6's turn_xy/grid_cells agree, every library drawing, q 0-3")
def _():
    M = bpm()
    for kind, bp in LIBRARY.items():
        L = lt(bp)
        for q in range(4):
            tl = M.to_layouts(L, q)
            cells = py(B.grid_cells(L, q))
            for k, lv in enumerate(lua_list(tl.levels), 1):
                g5 = tile_set(lv.tiles)
                if bp.get("ground") == "surface":
                    g5 = {(c["x"], c["y"]) for c in py(lv.construct) or []}
                    g6 = {(c["lx"], c["ly"]) for c in cells[k - 1] if c["sym"] in "WFRUDIO"}
                else:
                    g6 = {(c["lx"], c["ly"]) for c in cells[k - 1] if dug_symbol(c["sym"], "rock")}
                assert g5 == g6, (kind, q, k, sorted(g5 ^ g6)[:6])
            # level 1's '@' at (0, 0); G6's turn of a grid offset is G5's rotation of the grid
            rb = M.rotate(L, q)
            rows = [rb.levels[1].grid[i] for i in range(1, len(rb.levels[1].grid) + 1)]
            r0 = next(r for r, row in enumerate(rows) if "@" in row)
            c0 = rows[r0].index("@")
            orig = bp["levels"][0]["grid"]
            jy = next(r for r, row in enumerate(orig) if "@" in row)
            jx = orig[jy].index("@")
            for gy, row in enumerate(orig):
                for gx, s in enumerate(row):
                    lx, ly = B.turn_xy(gx - jx, gy - jy, q)
                    assert rows[r0 + ly][c0 + lx] == s, (kind, q, gx, gy)


@plain("the convention: q turns clockwise with y south (north goes east), as G6's Q_OF_DIR expects")
def _():
    M = bpm()
    bp = {"v": 1, "ground": "rock", "levels": [{"grid": ["__@__", ".....", ".....", "....."]}], "legend": {}}
    assert blueprint.check_format(bp)[0], blueprint.check_format(bp)[1]
    for q, side in ((0, "y>=0"), (1, "x<=0"), (2, "y<=0"), (3, "x>=0")):
        tl = M.to_layouts(lt(bp), q)
        xy = tile_set(tl.levels[1].tiles)
        assert xy, q
        ok = {"y>=0": all(y >= 0 for _, y in xy), "x<=0": all(x <= 0 for x, _ in xy),
              "y<=0": all(y <= 0 for _, y in xy), "x>=0": all(x >= 0 for x, _ in xy)}[side]
        assert ok, (q, side, xy)
    # north (0, -1) goes east (1, 0) after one turn, in both modules
    assert tuple(B.turn_xy(0, -1, 1)) == (1, 0)
    one = M.rotate(lt({"levels": [{"grid": ["ab", "cd"]}]}), 1)
    assert [one.levels[1].grid[1], one.levels[1].grid[2]] == ["ca", "db"]


# an asymmetric rock drawing (7 x 7, two levels): an L of rooms off the stair
def l_drawing():
    g1 = ["___@___",
          "___.___",
          "___>...",
          "___...,",
          "_______",
          "_______",
          "_______"]
    g2 = ["_______",
          "_______",
          "___<___",
          "___.___",
          "___.___",
          "__...__",
          "__..,__"]
    return {"v": 1, "name": "The Bend", "purpose": "descent", "ground": "rock",
            "levels": [{"grid": g1}, {"grid": g2}], "legend": {}}


def map_of(site, bp, k, gx, gy):
    """Where grid tile (gx, gy) of level k lands, by G5's own rotation (a ',' marker)."""
    M = bpm()
    marked = copy.deepcopy(bp)
    for lv in marked["levels"]:
        lv["grid"] = [row.replace(",", ".") for row in lv["grid"]]
    row = marked["levels"][k - 1]["grid"][gy]
    marked["levels"][k - 1]["grid"][gy] = row[:gx] + "," + row[gx + 1:]
    rb = M.rotate(lt(marked), site.q)
    g1 = [rb.levels[1].grid[i] for i in range(1, len(rb.levels[1].grid) + 1)]
    r0 = next(r for r, x in enumerate(g1) if "@" in x)
    c0 = g1[r0].index("@")
    gk = [rb.levels[k].grid[i] for i in range(1, len(rb.levels[k].grid) + 1)]
    r = next(r for r, x in enumerate(gk) if "," in x)
    c = gk[r].index(",")
    return site.anchor.x + (c - c0), site.anchor.y + (r - r0), site.z - (k - 1)


@test("a refusal on a turned drawing: its position is on the drawing's own grid (q 1, 2, 3)")
def _():
    bp = l_drawing()
    assert blueprint.check_format(bp)[0], blueprint.check_format(bp)[1][:3]
    seen_q = set()
    for sid in ("S1", "S2", "S3", "S4"):
        W.reset()
        r = B.landmark_sites(lt({"w": 7, "h": 7, "levels": 2, "ground": "rock"}), "descent", 4)
        assert r.ok, py(r)
        site = B.offered_site(sid)
        if site is None:
            continue
        ok, reasons = B.validate_landmark(lt(bp), site, 2500)[:2]
        assert ok, (sid, [x.words for x in lua_list(reasons)])
        for k, gx, gy in ((1, 6, 3), (2, 2, 6)):
            W.reset()
            B.landmark_sites(lt({"w": 7, "h": 7, "levels": 2, "ground": "rock"}), "descent", 4)
            site = B.offered_site(sid)
            x, y, z = map_of(site, bp, k, gx, gy)
            W.set(x, y, z, S6.T({"aquifer": True}))
            ok, reasons = B.validate_landmark(lt(bp), site, 2500)[:2]
            rs = lua_list(reasons)
            assert not ok and rs[0].code == "AQUIFER", (sid, site.q, [x.words for x in rs])
            assert (rs[0].level, rs[0].x, rs[0].y) == (k, gx, gy), (sid, site.q, rs[0].words)
            assert rs[0].words.startswith(f"L{k} x{gx} y{gy}:"), rs[0].words
        seen_q.add(int(site.q))
    assert {1, 2, 3} <= seen_q, seen_q


# --- 2. the library landmarks ----------------------------------------------------------

def lua_check(bp):
    ok, rs = bpm().check_format(lt(bp))
    return bool(ok), [(r.code, r.level, r.x, r.y, r.words) for r in lua_list(rs)]


@plain("the six library landmarks pass G5's Lua and Python check_format, with the same cost")
def _():
    assert sorted(LIBRARY) == ["chronicle_hall", "descent", "gate_hall", "god_hall", "great_hall", "necropolis",
                               "ziggurat"]                                     # (E1) chronicle_hall
    for kind, bp in LIBRARY.items():
        ok, rs = blueprint.check_format(bp)
        lok, lrs = lua_check(bp)
        assert ok and lok and not rs and not lrs, (kind, rs[:2], lrs[:2])
        assert blueprint.cost(bp) == {k: int(v) for k, v in py(bpm().cost(lt(bp))).items()}, kind


def exempt_for(site):
    """The fort-side opening of level 1's corridor, as validate_landmark exempts it."""
    return LUA.eval("""function(from)
        return function(x, y, t)
          return math.max(math.abs(x - from.x), math.abs(y - from.y)) <= 1 and t ~= nil and t.shape ~= 'WALL'
        end end""")(site["from"] or site.anchor)


@test("the library translates (to_layouts) into layouts validate_landmark and check_site take, every site")
def _():
    for kind, bp in LIBRARY.items():
        S6._reset()
        w, h, levels, ground = blueprint.env_of(bp)
        if ground == "surface":
            S6.field(20, 20, 110, 110)
        r = B.landmark_sites(lt({"w": w, "h": h, "levels": levels, "ground": ground}), kind, 4)
        assert r.ok and len(lua_list(r.sites)) >= 2, (kind, py(r))
        qs = set()
        for s in lua_list(r.sites):
            site = B.offered_site(s.id)
            tl = bpm().to_layouts(lt(bp), site.q)
            assert tl is not None and len(lua_list(tl.levels)) == levels, kind
            res = B.validate_landmark(lt(bp), site, 2500)
            ok, reasons, placed = res[0], res[1], res[2]
            assert ok, (kind, s.id, [x.words for x in lua_list(reasons)])
            qs.add(int(site.q))
            if ground == "rock":
                extra = LUA.table()
                for c in lua_list(site.corridor):
                    extra[c.x] = extra[c.x] or LUA.table()
                    extra[c.x][c.y] = True
                for k, lv in enumerate(lua_list(placed.levels), 1):
                    okc, why = B.check_site(lv.L, extra if k == 1 else LUA.table(), site.anchor.x, site.anchor.y,
                                            lv.z, LUA.table(), None, exempt_for(site) if k == 1 else None)[:2]
                    assert okc, (kind, s.id, k, why)
        assert len(qs) >= 2, (kind, qs)


def run_surface(lid, max_steps=20):
    """landmark_step to done, the fake game building each construction a step after it's planned."""
    stages = []
    for _ in range(max_steps):
        s = B.landmark_step(lid, False)
        stages.append(s.stage)
        if s.done:
            break
        for c in lua_list(W.placed):
            if c.mode == "build" and c.z is not None:
                shape = {"Cw": "WALL", "Cf": "FLOOR", "Cr": "RAMP", "Cu": "STAIR_UP", "Cd": "STAIR_DOWN",
                         "Cx": "STAIR_UPDOWN"}.get(c.text)
                W.set(c.x, c.y, c.z, S6.T({"shape": shape or "FLOOR", "building": False}))
    return stages


@test("the library built for real on the fake fort: designated = cost.dug (+ the corridor), the ziggurat to done")
def _():
    for kind, bp in LIBRARY.items():
        S6._reset()
        w, h, levels, ground = blueprint.env_of(bp)
        if ground == "surface":
            S6.field(20, 20, 110, 110)
        assert B.landmark_sites(lt({"w": w, "h": h, "levels": levels, "ground": ground}), kind, 4).ok, kind
        site = B.offered_site("S1")
        c = blueprint.cost(bp)
        dry = B.build_landmark(lt(bp), "S1", S6.meta(name="The Library Piece", purpose=kind), lt(NOW), True)
        assert dry.ok and dry.dry_run and S6.designated_count() == 0, (kind, py(dry))
        r = B.build_landmark(lt(bp), "S1", S6.meta(name="The Library Piece", purpose=kind), lt(NOW), False)
        assert r.ok, (kind, py(r))
        if ground == "rock":
            assert not site.extend, kind            # the fake fort's stair reaches every library level
            n, corridor = S6.designated_count(), len(lua_list(site.corridor))
            assert n == c["dug"] + corridor, (kind, n, c["dug"], corridor)
            assert len(lua_list(r.project_ids)) == levels, kind
        else:
            assert len(lua_list(r.project_ids)) == 0
            stages = run_surface(r.landmark_id)
            assert stages[-1] == "zone" or B.landmarks_data().list[1].status == "built", (kind, stages)
            assert B.landmarks_data().list[1].status == "built", (kind, stages)


# --- 3. Scripts is main, byte for byte; Guided carries the new keys ----------------------

PROBE = r'''
import copy, json, sys
from pathlib import Path
brain = Path(sys.argv[1]); sys.path.insert(0, str(brain))
fixtures = Path(sys.argv[2]); design = sys.argv[3]; presets = json.loads(sys.argv[4])
from digest import normalize
from planner import Memory, plan, record, select, TICKS_PER_DAY
out = {}
for path in [fixtures / "test_fort.json"] + sorted((fixtures / "real").glob("*.json")):
    base = normalize(json.loads(path.read_text(encoding="utf-8")))
    for tname, traits in [("own", None)] + sorted(presets.items()):
        s = copy.deepcopy(base)
        s.setdefault("settings", {})
        if traits is not None:
            s["settings"] = dict(s["settings"], traits=traits)
        if design != "none":
            s["settings"] = dict(s["settings"], design=design)
        m = Memory()
        cycles = []
        for _ in range(3):
            props, notes = plan(copy.deepcopy(s), m)
            cycles.append({"props": [[p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason,
                                      p.priority] for p in props], "notes": notes})
            allowed, _ = select(props, s, m)
            record([(p, {"ok": False, "error": "refused (test)"}) for p in allowed], s, m)
            s["date"]["tick"] = s["date"].get("tick", 0) + TICKS_PER_DAY
        out[f"{path.name}:{tname}"] = cycles
print(json.dumps(out, sort_keys=True))
'''

_MAIN = {}


def main_tree() -> Path | None:
    """main's brain/ and lua/ (git archive), once."""
    if "dir" not in _MAIN:
        tmp = tempfile.mkdtemp(prefix="d0-merge-main-")
        arch = subprocess.run(["git", "-C", str(ROOT), "archive", "main", "brain", "lua"], capture_output=True)
        if arch.returncode != 0:
            _MAIN["dir"] = None
        else:
            subprocess.run(["tar", "-x", "-C", tmp], input=arch.stdout, check=True)
            _MAIN["dir"] = Path(tmp)
            atexit.register(shutil.rmtree, tmp, True)
    return _MAIN["dir"]


def probe(brain: Path, design_: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "probe.py"
        p.write_text(PROBE, encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(p), str(brain), str(FIXTURES), design_,
                            json.dumps(design_rules.PRESET_SLIDERS)],
                           capture_output=True, text=True, env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=tmp)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout.strip().splitlines()[-1]


_RUNS = {}


def runs():
    if not _RUNS:
        main = main_tree()
        assert main is not None, "no main branch to compare with"
        _RUNS["main"] = probe(main / "brain", "none")
        _RUNS["none"] = probe(ROOT / "brain", "none")
        _RUNS["scripts"] = probe(ROOT / "brain", "scripts")
        _RUNS["guided"] = probe(ROOT / "brain", "guided")
    return _RUNS


@plain("Scripts: plan()'s proposals and notes are main's, byte for byte (7 fixtures x 7 slider sets x 3 cycles)")
def _():
    r = runs()
    assert r["none"] == r["main"], "no design key: the plan differs from main's"
    assert r["scripts"] == r["main"], "design scripts: the plan differs from main's"
    cases = json.loads(r["main"])
    assert len(cases) == 7 * 7
    starts = sum(1 for cs in cases.values() for c in cs for p in c["props"] if '"start_project"' in p[1])
    assert starts > 100, starts


def layouts_env(lua_dir: Path):
    """ai-layouts and the bridge's parse_style of one tree, in their own Lua."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lay = (lua_dir / "ai-layouts.lua").read_text(encoding="utf-8")
    src = (lua_dir / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    fn = re.search(r"\nlocal function parse_style\(st\)\n.*?\nend\n", src, re.S).group(0)
    env = lua.execute("""
        local lay_src = ...
        LAY = setmetatable({}, {__index = _G})
        assert(load(lay_src, 'ai-layouts', 't', LAY))()
        function reqscript(name) if name == 'ai-layouts' then return LAY end error('no ' .. name) end
        function int_in(v, lo, hi)
            v = math.tointeger(tonumber(v)); if v == nil or v < lo or v > hi then return nil end; return v
        end
    """ + fn + "\nreturn {parse = parse_style, layouts = LAY}", lay)
    return lua, env


SER = r"""function(L)
  local function sorted_set(set)
    local out = {}
    for x, col in pairs(set or {}) do for y in pairs(col) do table.insert(out, x .. ',' .. y) end end
    table.sort(out); return table.concat(out, ' ')
  end
  local function cells(list)
    local out = {}
    for _, c in ipairs(list or {}) do table.insert(out, c.x .. ',' .. c.y .. '=' .. tostring(c.text)) end
    return table.concat(out, ' ')
  end
  local function kv(t)
    local out = {}
    for k, v in pairs(t or {}) do
      if type(v) == 'table' then
        local parts = {}
        for _, e in ipairs(v) do table.insert(parts, tostring(e)) end
        v = '[' .. table.concat(parts, ',') .. ']'
      end
      table.insert(out, tostring(k) .. '=' .. tostring(v))
    end
    table.sort(out); return table.concat(out, ' ')
  end
  local halls = {}
  for _, h in ipairs(L.halls or {}) do table.insert(halls, ('%d,%d,%d,%d'):format(h.x, h.y, h.w, h.h)) end
  local b = L.bounds
  return table.concat({'kind ' .. tostring(L.kind), 'orient ' .. tostring(L.orient),
    'dig ' .. cells(L.dig), 'build ' .. cells(L.build), 'place ' .. cells(L.place), 'zone ' .. cells(L.zone),
    'smooth ' .. cells(L.smooth), 'engrave ' .. cells(L.engrave), 'tiles ' .. sorted_set(L.tiles),
    'soil ' .. sorted_set(L.soil), 'bounds ' .. ('%d,%d,%d,%d'):format(b.x1, b.y1, b.x2, b.y2),
    'furniture ' .. kv(L.furniture), 'summary ' .. kv(L.summary), 'halls ' .. table.concat(halls, ' ')}, '\n')
end"""

NOT_PARAMS = {"type", "plan", "urgent", "max_elev", "dry_run", "style"}


def make_layout(lua, env, action):
    """The level act_start_project would make of an action: parse_style, then ai-layouts.make."""
    def to(v):
        if isinstance(v, dict):
            t = lua.table()
            for k, x in v.items():
                t[k] = to(x)
            return t
        if isinstance(v, list):
            return lua.table_from([to(x) for x in v])
        return v
    res = env.parse(to(action.get("style")))
    style, err = res if isinstance(res, tuple) else (res, None)
    assert err is None, (action, err)
    p = to({k: v for k, v in action.items() if k not in NOT_PARAMS})
    p.style = style
    res = env.layouts.make(action["kind"], p)
    L, err = res if isinstance(res, tuple) else (res, None)
    assert L is not None, (action, err)
    return lua.eval(SER)(L), style


def start_actions(run: str) -> list[dict]:
    seen, out = set(), []
    for cs in json.loads(run).values():
        for c in cs:
            for p in c["props"]:
                a = json.loads(p[1])
                if a.get("type") == "start_project" and p[1] not in seen:
                    seen.add(p[1])
                    out.append(a)
    return out


@plain("Scripts: every level plan() asks for is laid out byte-identically by main's and the merged Lua")
def _():
    main = main_tree()
    ml, me = layouts_env(main / "lua")
    nl, ne = layouts_env(LUA_DIR)
    acts = start_actions(runs()["scripts"])
    assert len(acts) >= 20, len(acts)
    for a in acts:
        assert make_layout(ml, me, a)[0] == make_layout(nl, ne, a)[0], a


@plain("the layouts snapshot is main's (made again from main's ai-layouts.lua), and the merged Lua matches it")
def _():
    main = main_tree()
    fixture = json.loads((FIXTURES / "d0_layouts_snapshot.json").read_text(encoding="utf-8"))["cases"]
    real_root = SNAP.ROOT
    try:
        SNAP.ROOT = main
        from_main = SNAP.snapshot()
    finally:
        SNAP.ROOT = real_root
    assert from_main == fixture, "the snapshot fixture is not main's"
    assert SNAP.snapshot() == fixture


@plain("Guided: a level carries the language's new style keys, and G4's parse_style takes them")
def _():
    acts = start_actions(runs()["guided"])
    nl, ne = layouts_env(LUA_DIR)
    new_keys = {"scale", "aspect", "arms", "motif", "grand"}
    carrying = [a for a in acts if new_keys & set(a.get("style") or {})
                or (a.get("style") or {}).get("hall") in ("octagonal", "round", "cruciform", "nave")]
    assert len(carrying) >= 5, (len(carrying), len(acts))
    seen = set()
    for a in acts:
        _, style = make_layout(nl, ne, a)
        st = a.get("style") or {}
        for k in new_keys & set(st):
            assert style[k] == st[k], (k, st, style[k])
            seen.add(k)
        assert (style.hall if style is not None else "plain") == st.get("hall", "plain"), st
    assert {"scale", "arms", "motif"} <= seen, seen
    # and never a key at its default (old journals read the same)
    for a in carrying:
        st = a["style"]
        assert st.get("scale") != 100 and st.get("arms") != "corridor" and st.get("motif") != "rows", st


# --- 4. G7's loop end to end on the real bridge part -----------------------------------

BRIDGE_PART = LUA.execute("""
  local src, B, BPM, now = ...
  local env = setmetatable({}, {__index = _G})
  env.BRIDGE_VERSION = 'test'
  env.qerror = error
  env.reject = function(why) return {ok = false, rejected = true, error = why} end
  env.int_in = function(v, lo, hi)
    v = math.tointeger(tonumber(v)); if v == nil or v < lo or v > hi then return nil end; return v
  end
  env.whole_number = function(v) return math.tointeger(tonumber(v)) end
  env.sorted_keys = function(t) local o = {}; for k in pairs(t) do o[#o + 1] = k end; table.sort(o); return o end
  env.get_date = function() return now end
  env.reqscript = function(name)
    if name == 'ai-builder' then return B end
    if name == 'ai-blueprints' then return BPM end
    error('no ' .. name)
  end
  env.df = setmetatable({historical_figure = {find = function(id) return {id = id} end}}, {__index = df})
  assert(load(src, 'ai-bridge-design', 't', env))()
  return env
""", (LUA_DIR / "ai-bridge-design.lua").read_text(encoding="utf-8"), B, S6.LUA.globals().BPM, lt(NOW))

ACTS = {"blueprint_sites": "act_blueprint_sites", "build_blueprint": "act_build_blueprint",
        "landmark_step": "act_landmark_step"}
COORDS = re.compile(r'"(x|y|z|anchor|stair|corridor|q|x1|y1|z1|bounds)"\s*:')
BASE = json.loads((FIXTURES / "test_fort.json").read_text(encoding="utf-8"))


def fort(design_, traits):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"] = dict(s["settings"], ai_frequency=0, ai_effort=0, traits=traits, design=design_)
    s["needs"] = {"deity_ids": {"Ral": 11}, "deities": {"Ral": 5}}
    s["stone_types"] = [{"token": "GRANITE", "name": "granite", "boulders": 80}]
    return s


def game_cycle(s, m, seen):
    """plan; the design actions run by ai-bridge-design on the fake fort; record; the report read back."""
    s["landmarks"] = py(B.landmarks_report()) or {"list": []}
    if isinstance(s["landmarks"], list):
        s["landmarks"] = {"list": s["landmarks"]}
    rep = py(B.projects_report())
    s["projects"] = dict(s["projects"], open=rep.get("open") or [] if isinstance(rep, dict) else [])
    ps, notes = plan(copy.deepcopy(s), m)
    mine = [p for p in ps if p.action.get("type") in ACTS]
    results = []
    for p in mine:
        a = json.loads(json.dumps(p.action))
        r = py(BRIDGE_PART[ACTS[a["type"]]](lt(a)))
        seen.append((a, r))
        results.append((p, r))
    record(results, s, m)
    s["date"]["tick"] += TICKS_PER_DAY
    return mine, notes


def reset_pd():
    PD._AI_ALLOWED = None
    PD.AI_ON = False
    PD._LIBRARY = None


@test("G7 at Guided, design_ai off: a rule language, and the next level built in it on the fake fort")
def _():
    reset_pd()
    assert PD.ai_allowed() is False
    s, m, seen = fort("guided", {"grandeur": 40, "militarism": 20}), Memory(), []
    mine, notes = game_cycle(s, m, seen)
    assert not mine and not seen, "Guided starts no landmark"
    rec = m.culture["design"]
    assert rec["by"] == "rules" and rec["lang"] and any("written by rules" in n for n in notes), notes
    ps, _ = plan(copy.deepcopy(s), m)
    starts = [p.action for p in ps if p.action.get("type") == "start_project"]
    assert starts, [p.action for p in ps][:5]
    lang = rec["lang"]
    a = starts[0]
    assert a["style"].get("hall") == lang.get("hall"), (a["style"], lang.get("hall"))
    nl, ne = layouts_env(LUA_DIR)
    _, style = make_layout(nl, ne, a)          # parse_style takes it
    params = {k: v for k, v in a.items() if k not in NOT_PARAMS}
    p = lt(params)
    p.style = lt({k: style[k] for k in style.keys()})
    r = B.start_project(p, lt(NOW), False)
    assert r.ok, (a, py(r))


@test("G7 at Architect, design_ai off: a god's hall from the library, sites -> build -> dug -> built, on the real bridge part")
def _():
    reset_pd()
    s, m, seen = fort("architect", {"grandeur": 40, "militarism": 20}), Memory(), []
    p1, _ = game_cycle(s, m, seen)
    assert [p.action["type"] for p in p1] == ["blueprint_sites"], [p.action for p in p1]
    assert seen[-1][1]["ok"] and seen[-1][1]["sites"], seen[-1][1]
    p2, _ = game_cycle(s, m, seen)
    assert [p.action["type"] for p in p2] == ["build_blueprint"], [p.action for p in p2]
    a, r = seen[-1]
    assert a["by"] == "library" and a["purpose"] == "god_hall" and a["bp"] == LIBRARY["god_hall"], a["purpose"]
    assert r["ok"] and r["project_ids"], r
    for a, r in seen:
        assert not COORDS.search(json.dumps({k: v for k, v in a.items() if k != "bp"})), a
        assert not COORDS.search(json.dumps(r.get("sites") or [])), r
    e = PD.active_landmark(m) or m.atlas["landmarks"]["list"][-1]
    assert e["status"] == "building" and e["landmark_id"] == r["landmark_id"], e
    # the game digs it; the levels are furnished and finished
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False
    for pid in r["project_ids"]:
        assert B.furnish_project(pid, True).ok
        assert B.finish_project(pid).ok
    game_cycle(s, m, seen)
    assert m.atlas["landmarks"]["list"][-1]["status"] == "built", m.atlas["landmarks"]["list"][-1]
    # the pace: nothing more this season
    p3, _ = game_cycle(s, m, seen)
    assert not [p for p in p3 if p.action["type"] in ("blueprint_sites", "build_blueprint")]


@test("G7 at Architect, design_ai off: the Garden fort's ziggurat, sites -> build -> landmark_step to built")
def _():
    reset_pd()
    S6.field(20, 20, 110, 110)
    garden = design_rules.PRESET_SLIDERS["Garden fort"]
    s, m, seen = fort("architect", dict(garden)), Memory(), []
    game_cycle(s, m, seen)
    game_cycle(s, m, seen)
    a, r = seen[-1]
    assert a["type"] == "build_blueprint" and a["purpose"] == "ziggurat" and r["ok"], (a.get("purpose"), r)
    steps = 0
    for _ in range(30):
        mine, _ = game_cycle(s, m, seen)
        steps += sum(1 for p in mine if p.action["type"] == "landmark_step")
        for c in lua_list(W.placed):
            if c.mode == "build":
                shape = {"Cw": "WALL", "Cf": "FLOOR", "Cr": "RAMP", "Cu": "STAIR_UP", "Cd": "STAIR_DOWN",
                         "Cx": "STAIR_UPDOWN"}.get(c.text)
                W.set(c.x, c.y, c.z, S6.T({"shape": shape or "FLOOR", "building": False}))
        if m.atlas["landmarks"]["list"][-1]["status"] == "built":
            break
    assert steps >= 3 and m.atlas["landmarks"]["list"][-1]["status"] == "built", \
        (steps, m.atlas["landmarks"]["list"][-1], [r.get("stage") for a, r in seen if a["type"] == "landmark_step"])


# --- 5. no skips -----------------------------------------------------------------------

@plain("G2's two guarded checks and G5's library test run now (no SKIPPED in any test_d0_*)")
def _():
    for name, must in (("test_d0_rules.py", ["the library passes G5's check_format",
                                             "every language from rules passes the checker"]),
                       ("test_d0_blueprints.py", ["Lua and Python agree on the library landmarks"])):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(ROOT / "tests" / name)], capture_output=True, text=True,
                               env=dict(os.environ, DFAI_LOG_DIR=tmp), cwd=str(ROOT))
        lines = r.stdout.splitlines()
        assert r.returncode == 0 and not any("SKIPPED" in x for x in lines), (name, [x for x in lines if "SKIP" in x])
        for m in must:
            assert any(x.startswith("[PASS] " + m) for x in lines), (name, m)
    # and no test_d0_* skips for want of another group's file
    for p in sorted((ROOT / "tests").glob("test_d0_*.py")):
        src = p.read_text(encoding="utf-8")
        for g in re.findall(r'print\("SKIPPED[^"]*"\)', src):
            assert "lupa" in g or p.name == "test_d0_rules.py", (p.name, g)
    assert design.check_language and blueprint.check_format     # the guarded imports resolve


# --- 6. G3's choice: new forts Guided, old saves Scripts --------------------------------

def brain_mode(settings_for_ai) -> str:
    s = fort(None, {})
    s["settings"] = dict(s["settings"], **{k: v for k, v in settings_for_ai.items() if k != "traits"})
    if s["settings"].get("design") is None:
        s["settings"].pop("design", None)
    m = Memory()
    plan(copy.deepcopy(s), m)
    return design.mode(s), m


def for_ai():
    S = TP.H.settings()
    return py(S.for_ai(S.load_settings()))


@plain("no settings saved at all: the fort reads Guided, and the brain writes it a rule language")
def _():
    TP.reset()
    a = for_ai()
    assert a["design"] == "guided" and TP.saved() is None
    mode, m = brain_mode(a)
    assert mode == "guided" and m.culture["design"]["by"] == "rules"


@plain("settings saved before this round (no design key) read Scripts: the real forts', and every saving path keeps it")
def _():
    olds = [{"version": 2, "mode": "autopilot"}]
    for p in sorted((FIXTURES / "real").glob("*.json")):
        st = json.loads(p.read_text(encoding="utf-8")).get("settings") or {}
        old = {k: v for k, v in st.items() if k not in ("traits", "design", "landmark_pace")}
        assert "design" not in st
        olds.append(dict(old, version=2))
    for old in olds:
        TP.reset()
        TP.H.persist["ai-overseer/settings"] = TP.t(old)
        a = for_ai()
        assert a["design"] == "scripts" and a["landmark_pace"] == "season", old
        mode, m = brain_mode(a)
        assert mode == "scripts" and "design" not in (m.culture or {}), old
        # the window's save, set_rules of another switch, the keeper's --preset: still Scripts
        S = TP.H.settings()
        S.save_settings(S.load_settings())
        assert TP.saved().design == "scripts"
        r = TP.act({"type": "set_rules", "rules": {"construct": False}})
        assert r.ok and TP.saved().design == "scripts", py(r)
        for name in TP.PRESETS:
            r = TP.act({"type": "apply_preset", "name": name})
            assert r.ok and TP.saved().design == "scripts" and r.settings.design == "scripts", (name, py(r))
        assert for_ai()["design"] == "scripts"


@plain("the keeper's --preset on a fort with nothing saved writes Guided down; a dry run writes nothing")
def _():
    TP.reset()
    r = TP.act({"type": "apply_preset", "name": "War-hold", "dry_run": True})
    assert r.ok and TP.saved() is None
    r = TP.act({"type": "apply_preset", "name": "War-hold"})
    assert r.ok and TP.saved().design == "guided" and TP.saved().landmark_pace == "season"
    assert for_ai()["design"] == "guided"


# --- 7. Lua 5.3 ------------------------------------------------------------------------

@plain("every lua/*.lua and lua/gui/*.lua compiles under Lua 5.3 (load, text, empty env)")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    assert L.eval("_VERSION") == "Lua 5.3"
    comp = L.eval("function(s, n) local f, e = load(s, n, 't', {}); return f ~= nil, e end")
    files = sorted(LUA_DIR.glob("*.lua")) + sorted((LUA_DIR / "gui").glob("*.lua"))
    assert len(files) > 40
    for p in files:
        ok, err = comp(p.read_text(encoding="utf-8"), p.name)
        assert ok, (p.name, err)


if __name__ == "__main__":
    finish()
