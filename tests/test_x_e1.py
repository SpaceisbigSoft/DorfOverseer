"""(E1) Multi-storey openings: '*' open to the level below (cut as a channel
once the level below is dug) and 'O' a rail (a fortification: dug, the
openings cut from it, then built), in lua/ai-blueprints.lua and its mirror
brain/blueprint.py (OPEN, RAIL and the rock SUPPORT check, the waves of the
translation), the map check and the cutting stages in
lua/ai-builder-landmarks.lua (validate_landmark, start_landmark,
landmark_step, the report), the library's chronicle hall, and the brain's
proposal. Needs lupa.

    python tests/test_x_e1.py
"""

from __future__ import annotations

import ast
import copy
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import blueprint  # noqa: E402

LUA_DIR = ROOT / "lua"
FIXTURES = ROOT / "tests" / "fixtures" / "blueprints"
LIBRARY = ROOT / "brain" / "landmarks"
FIX = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))}
LIB = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(LIBRARY.glob("*.json"))}
E1_FIX = {k: v for k, v in FIX.items() if any(ch in r for lv in v.get("levels", []) if isinstance(lv, dict)
                                               for r in lv.get("grid", []) if isinstance(r, str) for ch in "*O")
          and v.get("ground") == "rock"}

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    layouts = (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")
    builder = (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8")
    B, W = lua.execute(HARNESS, layouts, builder)
    load = lua.eval("""function(src, lay)
        local env = setmetatable({reqscript = function(n)
            if n == 'ai-layouts' then return lay end
            error('reqscript ' .. tostring(n)) end}, {__index = _G})
        assert(load(src, 'ai-blueprints', 't', env))()
        return env end""")
    lay = lua.eval("function() return reqscript('ai-layouts') end")()
    BPM = load((LUA_DIR / "ai-blueprints.lua").read_text(encoding="utf-8"), lay)
    lua.globals().BPM = BPM
    lua.execute("""
      local old = _G.reqscript
      _G.reqscript = function(name) if name == 'ai-blueprints' then return BPM end return old(name) end
      df = df or {}
      df.global = df.global or {}
      df.global.world = df.global.world or {}
      df.global.world.buildings = {other = {TRADE_DEPOT = {}}, all = {}}
    """)
    # merged0's ai-blueprints.lua, for the byte-identity proof
    try:
        old_src = subprocess.run(["git", "-C", str(ROOT), "show", "4b0de9a:lua/ai-blueprints.lua"],
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        old_src = None
    OLD = load(old_src, lay) if old_src else None
    return lua, B, W, BPM, OLD, lay


LUA, B, W, BP, OLD, LAY = boot()
T = LUA.table_from
REAL = {k: B[k] for k in ("landmark_stock", "landmark_times", "furnish_progress", "stone_at", "hall_planned_at")}


def lt(d):
    if isinstance(d, dict):
        return LUA.table_from({k: lt(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([lt(v) for v in d])
    return d


def py(v):
    """A Lua value as plain Python (lists for 1..n tables)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    keys = list(v.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[i]) for i in range(1, len(keys) + 1)]
    return {k: py(v[k]) for k in keys}


def lua_list(v) -> list:
    return [] if v is None else [v[i] for i in range(1, len(v) + 1)]


def lua_check(bp):
    ok, reasons = BP.check_format(lt(bp))
    return bool(ok), [{"code": r.code, "level": r.level, "x": r.x, "y": r.y, "words": r.words}
                      for r in lua_list(reasons)]


def both(bp):
    ok, r = blueprint.check_format(copy.deepcopy(bp))
    lok, lr = lua_check(bp)
    assert ok == lok and r == lr, (r[:3], lr[:3])
    return ok, r


def rock(*levels, **kw):
    return {"v": 1, "ground": "rock", "levels": [{"grid": list(g)} for g in levels], **kw}


def _reset():
    W.reset()
    for k, v in REAL.items():
        B[k] = v
    B.landmark_stock = LUA.eval("function() return 1000 end")
    B.landmark_times = LUA.eval("function() return nil end")
    B.stone_at = LUA.eval("function() return 'GRANITE' end")
    B.furnish_progress = LUA.eval("function(p) return {placed = 0, done = 0, waiting = {}} end")
    B.hall_planned_at = LUA.eval("function(x, y, z) return false end")
    B.TRY_BESIDE = True


test = make_test(before=_reset)
NOW = {"year": 150, "tick": 100}


def rock_site(w, h, levels):
    r = B.landmark_sites(lt({"w": w, "h": h, "levels": levels, "ground": "rock"}), "great_hall", 4)
    assert r.ok, dict(r)
    s = B.offered_site("S1")
    return s[0] if isinstance(s, tuple) else s


def map_xy(site, bp, gx, gy, k=1):
    row0 = bp["levels"][0]["grid"][0]
    x, y = B.turn_xy(gx - row0.index("@"), gy, site.q)
    return site.anchor.x + x, site.anchor.y + y, site.z - (k - 1)


def meta(**kw):
    m = {"name": "The Little Atrium", "purpose": "great_hall", "by": "library", "cap": 2500}
    m.update(kw)
    return lt(m)


def dig_all():
    """The dwarves dig every designated tile (a channel opens it)."""
    for t in W.tiles.values():
        if t.designated:
            text = t.dig_text or "d"
            t.shape = "EMPTY" if text.startswith("h") else "FLOOR"
            t.designated = False


def furnish_levels(r):
    for pid in lua_list(r.project_ids):
        f = B.furnish_project(pid, True)
        assert f.ok, dict(f)


def report():
    return lua_list(B.landmarks_report().list)[0]


# --- the format ------------------------------------------------------------------------

@test("the alphabet and codes: '*' and 'O' in the rock; OPEN and RAIL between REACH and SUPPORT, both sides")
def _():
    assert BP.ALPHABET.rock == blueprint.ALPHABET["rock"] == "_#.,@<>X^+*O"
    assert BP.ALPHABET.surface == blueprint.ALPHABET["surface"] == "_.@WFRUDIO+"      # the surface unchanged
    c = blueprint.CODES
    assert c.index("REACH") < c.index("OPEN") < c.index("RAIL") < c.index("SUPPORT") < c.index("LIMIT")
    assert BP.OPEN_KEY == "h" and BP.RAIL_KEY == "CF"
    expects = {bp["_expect"] for bp in E1_FIX.values() if "_expect" in bp}
    assert {"OPEN", "RAIL", "SUPPORT"} <= expects, expects


@test("every opening fixture and the chronicle hall: the same verdict, codes, positions and words in Lua and Python")
def _():
    assert len(E1_FIX) >= 8, sorted(E1_FIX)
    for name, bp in list(E1_FIX.items()) + [("chronicle_hall", LIB["chronicle_hall"])]:
        ok, r = both(bp)
        if name.startswith("bad_"):
            assert not ok and r[0]["code"] == bp["_expect"], (name, r[:2])
        else:
            assert ok, (name, r[:3])


@test("each refusal: an opening on the lowest level, over rock, with no rail to cut it from, unrailed, a post left hanging")
def _():
    gal = ["###@###", "#,,,,,#", "#,OOO,#", "#,O*O,#", "#,OOO,#", "#,,>,,#", "#######"]
    low = ["#######", "#.....#", "#.....#", "#.....#", "#.....#", "#..<..#", "#######"]
    assert both(rock(gal, low))[0]
    # the level below: rock, a stair up (STAIRS first), a rail
    for sym, code in (("#", "OPEN"), ("O", "OPEN"), ("<", "STAIRS"), ("^", "STAIRS"), ("s", None), ("+", None)):
        lo = list(low)
        lo[3] = "#.." + sym + "..#"
        ok, r = both(rock(gal, lo, legend={"s": "Statue"}))
        assert (r[0]["code"] if r else None) == code, (sym, r[:2])
    # stacked: '*' over '*' over floor is good; the chain ending on rock is not
    mid = ["#######", "#.....#", "#.OOO.#", "#.O*O.#", "#.OOO.#", "#..X..#", "#######"]
    assert both(rock(gal, mid, low))[0]
    lo = list(low)
    lo[3] = "#..#..#"
    ok, r = both(rock(gal, mid, lo))
    assert r[0]["code"] == "OPEN" and (r[0]["level"], r[0]["x"], r[0]["y"]) == (2, 3, 3), r[:2]
    # every tile beside it: a floor, a door, a stair, a statue are not rails (one reason a tile)
    for sym in (",", "+", "s"):
        g = list(gal)
        g[3] = "#,O*" + sym + ",#"
        ok, r = both(rock(g, low, legend={"s": "Statue"}))
        assert r[0]["code"] == "RAIL" and (r[0]["x"], r[0]["y"]) == (4, 3), (sym, r[:2])
    g = list(gal)
    g[2] = "#,,,O,#"                  # a diagonal floor counts too
    ok, r = both(rock(g, low))
    assert [x["code"] for x in r] == ["RAIL", "RAIL"] and {(x["x"], x["y"]) for x in r} == {(2, 2), (3, 2)}, r
    # two openings with no 'O': one reason each (not one a tile)
    g = ["####@####", "#,,,,,,,#", "#,#####,#", "#,#**#*#,#"[:9], "#,#####,#", "#,,,>,,,#", "#########"]
    g[3] = "#,#*#*#,#"
    lo = ["#########", "#.......#", "#.......#", "#.......#", "#.......#", "#...<...#", "#########"]
    ok, r = both(rock(g, lo))
    assert [(x["code"], x["x"]) for x in r] == [("OPEN", 3), ("OPEN", 5)], r
    # the cave-in: a floor tile ringed by openings; the same held by rock below passes
    g = ["####@####", "#,,,,,,,#", "#,OOOOO,#", "#,O***O,#", "#,O*,*O,#", "#,O***O,#", "#,OOOOO,#", "#,,,>,,,#",
         "#########"]
    lo = ["#########", "#.......#", "#.......#", "#.......#", "#.......#", "#.......#", "#.......#", "#...<...#",
          "#########"]
    ok, r = both(rock(g, lo))
    assert r and r[0]["code"] in ("REACH", "SUPPORT"), r[:2]          # unreached too: it's an island
    g[4] = "#,O*#*O,#"
    ok, r = both(rock(g, lo))
    assert [x["code"] for x in r] == ["SUPPORT"] and (r[0]["x"], r[0]["y"]) == (4, 4), r
    lo2 = list(lo)
    lo2[4] = "#...#...#"              # a column: rock under the post holds it
    assert both(rock(g, lo2))[0]


@test("Lua and Python agree on 300 random drawings with openings and rails")
def _():
    rnd = random.Random(11)
    base = sorted(E1_FIX.items()) + [("chronicle_hall", LIB["chronicle_hall"])]
    symbols = "_#.,@<>X^+*O*O*Os"
    codes = set()
    for _ in range(300):
        bp = json.loads(json.dumps(rnd.choice(base)[1]))
        for _ in range(rnd.randint(1, 5)):
            lv = rnd.choice(bp["levels"])
            y = rnd.randrange(len(lv["grid"]))
            row = lv["grid"][y]
            x = rnd.randrange(len(row))
            lv["grid"][y] = row[:x] + rnd.choice(symbols) + row[x + 1:]
        ok, r = both(bp)
        py_c = blueprint.cost(bp)
        lu_c = {k: int(v) for k, v in BP.cost(lt(bp)).items()}
        assert py_c == lu_c, (py_c, lu_c)
        codes.add(r[0]["code"] if r else None)
    assert {"OPEN", "RAIL", "SUPPORT", None} <= codes, codes


@test("cost: '*' and 'O' are dug, 'O' also built, '*' one more job (its cut)")
def _():
    c = blueprint.cost(FIX["good_atrium"])
    assert c["dug"] == 26 + 25 and c["built"] == 8 and c["open"] == 1, c
    assert c["jobs"] == c["dug"] + c["open"] + 4 * c["built"] + 10 * c["items"], c
    ch = blueprint.cost(LIB["chronicle_hall"])
    assert ch["open"] == 135 and ch["built"] == 26 and ch["jobs"] <= 900, ch


# --- the translation -------------------------------------------------------------------

def tiles(t) -> set:
    return {(int(x), int(y)) for x, col in (t.items() if t is not None else []) for y in col.keys()}


def cells(t) -> list:
    return [(int(c.x), int(c.y), c.text) for c in lua_list(t)]


@test("to_layouts: openings and rails are dug; one 'h' cell an opening, the farthest from the rails cut first; "
      "the rails 'CF'; no zone, smoothing or engraving on either")
def _():
    for name in ("good_atrium", "good_atrium_deep", "good_rail_window", "chronicle_hall"):
        bp = LIB.get(name) or FIX[name]
        c = blueprint.cost(bp)
        for q in range(4):
            out = BP.to_layouts(lt(bp), q)
            n_open = n_rail = 0
            for L in lua_list(out.levels):
                op = [(int(x.x), int(x.y), x.text, int(x.wave)) for x in lua_list(L.open)]
                rails = {(x, y) for x, y, t in cells(L.construct)}
                assert all(t == "CF" for _, _, t in cells(L.construct))
                assert rails == tiles(L.built), name
                holes = {(x, y) for x, y, _, _ in op}
                assert holes | rails <= tiles(L.tiles), name               # dug first
                assert all(t == "h" for _, _, t, _ in op)
                waves = [w for _, _, _, w in op]
                assert waves == sorted(waves) and (not waves or (min(waves) == 1 and set(waves) == set(range(1, max(waves) + 1))))
                # wave w's tiles: cut from a tile beside it (4 ways) still floor then: a later wave, or a rail
                wave_of = {(x, y): w for x, y, _, w in op}
                for (x, y), w in wave_of.items():
                    nb = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
                    assert any(p in rails or wave_of.get(p, 0) == w + 1 for p in nb), (name, q, x, y, w)
                for x, y, _ in cells(L.zone) + cells(L.smooth) + cells(L.engrave) + cells(L.build):
                    assert (x, y) not in holes and (x, y) not in rails, (name, x, y)
                n_open += len(op)
                n_rail += len(rails)
                if op or rails:
                    assert L.summary.built == len(rails) and (L.summary.opened or 0) == len(op)
            assert n_open == c["open"] and n_rail == c["built"], (name, n_open, n_rail, c)
    # the deep well: its middle first, then the ring by the rails
    L1 = lua_list(BP.to_layouts(lt(FIX["good_atrium_deep"]), 0).levels)[0]
    op = [(int(x.x), int(x.y), int(x.wave)) for x in lua_list(L1.open)]
    assert [w for _, _, w in op] == [1] + [2] * 8 and op[0][:2] == (0, 4), op
    # a wall touching only openings (the post in a cave-in drawing aside) isn't smoothed: it can't be reached
    bp = FIX["good_atrium"]
    L = lua_list(BP.to_layouts(lt(dict(bp, finish={"smooth": 3})), 0).levels)[0]
    sm = {(x, y) for x, y, _ in cells(L.smooth)}
    assert (0, 3) not in sm and (-3, 1) in sm, sorted(sm)


def strip(v):
    """A layout as plain data, without E1's own keys (open: empty when nothing opens; cost.open 0)."""
    out = py(v)
    if isinstance(out, dict):
        assert out["cost"].pop("open") == 0
        for L in out.get("levels", []) or []:
            if isinstance(L, dict):
                assert L.pop("open", []) in ([], {}), "an old drawing has openings"
    return out


@test("no openings, no change: every older fixture and library drawing checks, costs and translates as merged0's "
      "ai-blueprints.lua does (byte for byte, but the empty 'open' list and the 'open' count 0)")
def _():
    assert OLD is not None, "git show merged0:lua/ai-blueprints.lua failed"
    old_ones = {k: v for k, v in FIX.items() if k not in E1_FIX}
    old_ones.update({"lib_" + k: v for k, v in LIB.items() if k != "chronicle_hall"})
    assert len(old_ones) >= 60, len(old_ones)
    for name, bp in old_ones.items():
        a, b = BP.check_format(lt(bp)), OLD.check_format(lt(bp))
        assert py(a[1]) == py(b[1]) and bool(a[0]) == bool(b[0]), name
        ca, cb = py(BP.cost(lt(bp))), py(OLD.cost(lt(bp)))
        assert ca.pop("open") == 0 and ca == cb, (name, ca, cb)
        if a[0]:
            for q in range(4):
                assert strip(BP.to_layouts(lt(bp), q)) == py(OLD.to_layouts(lt(bp), q)), (name, q)
    # and the old checker refused every drawing with '*' or 'O' in the rock (nothing it took reads otherwise)
    for name, bp in E1_FIX.items():
        ok, r = OLD.check_format(lt(bp))
        assert not ok and r[1].code == "SYMBOL", name


# --- the bridge: the map, the stages ----------------------------------------------------

@test("checks, rock: the atrium passes on the fake fort; an opening dropping onto a floor over a cavern or water is "
      "refused with its position on the drawing")
def _():
    bp = FIX["good_atrium"]
    site = rock_site(7, 7, 2)
    ok, reasons = B.validate_landmark(lt(bp), site, 2500)[:2]
    assert ok, [r.words for r in lua_list(reasons)]
    for field, code in (("feature", "CAVERN"), ("liquid", "LIQUID"), ("aquifer", "AQUIFER")):
        W.reset()
        site = rock_site(7, 7, 2)
        x, y, z = map_xy(site, bp, 3, 3, k=2)
        W.set(x, y, z - 1, T({field: True}))
        ok, reasons = B.validate_landmark(lt(bp), site, 2500)[:2]
        rs = lua_list(reasons)
        mine = [r for r in rs if r.code == code and "opening drops to" in r.words]
        assert not ok and mine and (mine[0].level, mine[0].x, mine[0].y) == (1, 3, 3), (code, [r.words for r in rs])
    # a cavern beside the opening on its own level: the dug tiles' own check
    W.reset()
    site = rock_site(7, 7, 2)
    x, y, z = map_xy(site, bp, 3, 3)
    W.set(x, y, z, T({"feature": True}))
    rs = lua_list(B.validate_landmark(lt(bp), site, 2500)[1])
    assert any(r.code == "CAVERN" for r in rs), [r.words for r in rs]


@test("start: the openings and rails are dug with the rest; nothing is cut or built at the start")
def _():
    bp = FIX["good_atrium"]
    site = rock_site(7, 7, 2)
    r = B.build_landmark(lt(bp), "S1", meta(), lt(NOW), False)
    assert r.ok, dict(r)
    texts = [t.dig_text for t in W.tiles.values() if t.designated]
    assert texts and not any(str(t).startswith("h") for t in texts), texts
    assert not [c for c in lua_list(W.placed) if c.mode == "build" and c.text == "CF"]
    x, y, z = map_xy(site, bp, 3, 3)
    assert W.peek(x, y, z).designated                                   # the opening: dug floor first
    rec = B.landmarks_data().list[1]
    assert len(lua_list(rec.open)) == 1 and rec.open[1].level == 1 and len(lua_list(rec.open[1].rails)) == 8
    assert report().stage == "dig"


@test("landmark_step: the atrium dug -> 'open' -> the cut designated -> 'opening' -> cut -> rails built -> built")
def _():
    bp = FIX["good_atrium"]
    site = rock_site(7, 7, 2)
    r = B.build_landmark(lt(bp), "S1", meta(), lt(NOW), False)
    s = B.landmark_step(1, False)
    assert not s.ok and s.rejected, dict(s)                             # still digging
    dig_all()
    assert report().stage == "dig"                                      # dug, but the levels not moved on yet
    furnish_levels(r)
    assert report().stage == "open" and report().status == "building"
    # a dry run designates nothing
    before = sum(1 for t in W.tiles.values() if t.designated)
    d = B.landmark_step(1, True)
    assert d.ok and d.dry_run and d.stage == "open", dict(d)
    assert sum(1 for t in W.tiles.values() if t.designated) == before and report().stage == "open"
    s = B.landmark_step(1, False)
    assert s.ok and s.stage == "open" and s.cut == 1, dict(s)
    x, y, z = map_xy(site, bp, 3, 3)
    assert W.peek(x, y, z).designated and W.peek(x, y, z).dig_text == "h"
    assert report().stage == "opening"
    w = B.landmark_step(1, False)
    assert not w.ok and w.waiting and w.stage == "opening", dict(w)
    dig_all()                                                           # the channel is cut
    assert W.peek(x, y, z).shape == "EMPTY" and report().stage == "open"
    s = B.landmark_step(1, False)
    assert s.ok and s.railed == 8 and s.cut == 0, dict(s)
    rails = [(c.x, c.y, c.z) for c in lua_list(W.placed) if c.mode == "build" and c.text == "CF"]
    assert len(rails) == 8 and all(z == site.z for _, _, z in rails)
    # the rails being built: the landmark waits
    for (rx, ry, rz) in rails:
        W.set(rx, ry, rz, T({"building": True}))
    assert report().stage == "opening" and report().status == "building"
    for (rx, ry, rz) in rails:
        W.set(rx, ry, rz, T({"building": False, "shape": "FORTIFICATION"}))
    for pid in lua_list(r.project_ids):
        d = B.finish_project(pid)
        assert d.ok, dict(d)
    assert report().status == "built", dict(report())
    s = B.landmark_step(1, False)
    assert s.ok and s.done, dict(s)


@test("landmark_step: the deep well cuts in waves (the middle first), each level once the one below is dug; "
      "a lost cut is designated again")
def _():
    bp = FIX["good_atrium_deep"]
    site = rock_site(9, 9, 3)
    r = B.build_landmark(lt(bp), "S1", meta(name="The Deep Well Hall"), lt(NOW), False)
    assert r.ok, dict(r)
    dig_all()
    pids = lua_list(r.project_ids)
    # levels 1 and 2 moved on, level 3 (under level 2's opening) not: only level 1 may cut
    for pid in pids[:2]:
        assert B.furnish_project(pid, True).ok
    s = B.landmark_step(1, False)
    assert s.ok and [(lv.level, lv.wave) for lv in lua_list(s.levels)] == [(1, 1)], dict(s)
    mid = map_xy(site, bp, 4, 4, k=1)
    assert W.peek(*mid).dig_text == "h"
    assert B.furnish_project(pids[2], True).ok
    s = B.landmark_step(1, False)                                       # level 2's first wave; level 1 waits
    assert [(lv.level, lv.wave) for lv in lua_list(s.levels)] == [(2, 1)], dict(s)
    # the game drops level 1's cut (no job, no designation): designated again
    W.set(*mid, T({"designated": False}))
    s = B.landmark_step(1, False)
    assert s.ok and [(lv.level, lv.wave) for lv in lua_list(s.levels)] == [(1, 1)] and s.cut == 1, dict(s)
    dig_all()
    s = B.landmark_step(1, False)
    assert sorted((lv.level, lv.wave) for lv in lua_list(s.levels)) == [(1, 2), (2, 2)] and s.cut == 16, dict(s)
    ring = [map_xy(site, bp, gx, gy, k=1) for gx, gy in ((3, 3), (5, 5))]
    assert all(W.peek(*p).dig_text == "h" for p in ring)
    dig_all()
    s = B.landmark_step(1, False)
    assert sorted(lv.rails for lv in lua_list(s.levels)) == [16, 16] and s.railed == 32, dict(s)


@test("the report and the brain: a rock landmark's step is proposed when its openings can move ('open'), "
      "not while it digs or waits; a surface one as before")
def _():
    import planner_design as PD
    from types import SimpleNamespace

    def run(stage, ground="rock"):
        e = {"landmark_id": 1, "status": "building", "name": "The Little Atrium", "env": [7, 7, 2, ground],
             "kind": "great_hall"}
        mem = SimpleNamespace(atlas={"landmarks": {"next": 2, "last_started": 0, "list": [e]}}, culture={})
        s = {"landmarks": {"list": [{"id": 1, "status": "building", "stage": stage}]}, "settings": {}}
        props, notes = [], []
        PD.run_landmarks(s, {}, {}, props, notes, mem, "architect", 100)
        return [p.action.get("type") if hasattr(p, "action") else p for p in props]

    assert len(run("open")) == 1
    assert run("dig") == [] and run("opening") == [] and run(None) == []
    assert len(run("walls", "surface")) == 1 and run("done", "surface") == []


@test("the chronicle hall: in the library (kind chronicle_hall), 21x15x2, its gallery railed, and built on the fake fort "
      "to its openings")
def _():
    bp = LIB["chronicle_hall"]
    assert blueprint.load_library()["chronicle_hall"]["name"] == bp["name"]
    assert blueprint.env_of(bp) == (21, 15, 2, "rock")
    site = rock_site(21, 15, 2)
    ok, reasons = B.validate_landmark(lt(bp), site, 2500)[:2]
    assert ok, [x.words for x in lua_list(reasons)]
    r = B.build_landmark(lt(bp), "S1", meta(name=bp["name"], purpose="chronicle_hall"), lt(NOW), False)
    assert r.ok, dict(r)
    dig_all()
    furnish_levels(r)
    waves = 0
    while report().stage == "open":
        s = B.landmark_step(1, False)
        assert s.ok, dict(s)
        if s.railed:
            break
        waves += 1
        dig_all()
    assert waves >= 3 and s.railed == 26, (waves, dict(s))
    holes = [t for t in W.tiles.values() if t.shape == "EMPTY" and t.dig_text and str(t.dig_text).startswith("h")]
    assert len(holes) == 135, len(holes)


@test("the strategist's alphabet names '*' and 'O' (shown only when a drawing is asked for)")
def _():
    import strategist
    text = strategist.DESIGN_INSTRUCTIONS["blueprint"]
    assert "* open to the level below" in text and "O a fortification" in text
    assert "* open" not in strategist.DESIGN_INSTRUCTIONS["language"]


@test("the changed Lua compiles under 5.3")
def _():
    check = LUA.eval("function(src, name) local f, err = load(src, name, 't', {}); return f ~= nil, err end")
    for f in ("ai-blueprints.lua", "ai-builder-landmarks.lua"):
        ok, err = check((LUA_DIR / f).read_text(encoding="utf-8"), f)
        assert ok, (f, err)


if __name__ == "__main__":
    finish()
