"""(E2) Temporary construction: a surface landmark's build order, with
scaffolding (lua/ai-blueprints.lua build_stages; lua/ai-builder-landmarks.lua
validate_landmark / start_landmark / landmark_step / landmarks_report;
brain/planner_design.py step_words). Needs lupa.

Every plan is replayed by a checker written here, apart from the Lua: each
tile of a step has a dwarf's place beside it (or, a stair, the up stair under
it) that a dwarf walks to from '@', whatever order the step's tiles go up in;
no step cuts a reachable walkable tile off; every tile once; the scaffolding
only on ground left walkable with open air over it, and all of it down at the
end, top first.

    python tests/test_x_e2.py
"""

from __future__ import annotations

import ast
import json
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

LUA_DIR = ROOT / "lua"
FIXTURES = ROOT / "tests" / "fixtures" / "blueprints"
LIBRARY = ROOT / "brain" / "landmarks"

# --- ai-blueprints alone --------------------------------------------------------

PL = LuaRuntime(unpack_returned_tuples=True)
_load = PL.eval("""function(lsrc, bsrc)
  local lay = setmetatable({}, {__index = _G})
  assert(load(lsrc, 'ai-layouts', 't', lay))()
  local env = setmetatable({reqscript = function(n) return lay end}, {__index = _G})
  assert(load(bsrc, 'ai-blueprints', 't', env))()
  return env
end""")
LAYOUTS_SRC = (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8")
BP = _load(LAYOUTS_SRC, (LUA_DIR / "ai-blueprints.lua").read_text(encoding="utf-8"))
DUMP = PL.eval("""function(fn, a, b)
  local v = table.pack(fn(a, b))
  local out = {}
  local function d(x)
    if type(x) ~= 'table' then out[#out + 1] = type(x) .. ':' .. tostring(x) return end
    local keys = {}
    for k in pairs(x) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
    out[#out + 1] = '{'
    for _, k in ipairs(keys) do out[#out + 1] = tostring(k) .. '=' d(x[k]) out[#out + 1] = ',' end
    out[#out + 1] = '}'
  end
  d(v)
  return table.concat(out)
end""")


def plt(v):
    if isinstance(v, dict):
        return PL.table_from({k: plt(x) for k, x in v.items()})
    if isinstance(v, list):
        return PL.table_from([plt(x) for x in v])
    return v


def ll(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def stages(bp, q=0):
    r = BP.build_stages(plt(bp), q)
    if isinstance(r, tuple):
        return r[0], [dict(x) for x in ll(r[1])]
    return r, []


def as_steps(r) -> list[dict]:
    out = []
    for s in ll(r.list):
        out.append({"kind": s.kind, "level": s.level, "dz": s.dz,
                    "cells": [(c.gx, c.gy, c.text, c.x, c.y) for c in ll(s.cells)],
                    "cut": [(c.x, c.y, c.dz) for c in ll(s.cut)] if s.cut else None})
    return out


# --- the checker (apart from the Lua) ---------------------------------------------

CONSTRUCT = {"W": "Cw", "F": "Cf", "R": "Cr", "U": "Cu", "D": "Cd", "I": "Cx", "O": "CF"}
SYM = {"Cw": "W", "CF": "O", "Cf": "F", "Cr": "R", "Cu": "U", "Cd": "D", "Cx": "I"}
N8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]


def jobs_of(bp) -> dict:
    """(level, x, y, kind) -> key: kind 'c' a construction, 'door' a door."""
    g = [lv["grid"] for lv in bp["levels"]]
    out = {}
    for i, rows in enumerate(g, 1):
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                below = g[i - 2][y][x] if i > 1 else None
                key = CONSTRUCT.get(ch)
                if key is None and i > 1 and (ch == "+" or ch.islower()) and below not in (None, "W", "_"):
                    key = "Cf"
                if key:
                    out[(i, x, y, "c")] = key
                if ch == "+":
                    out[(i, x, y, "door")] = "d"
    return out


class World:
    def __init__(self, bp):
        self.g = [lv["grid"] for lv in bp["levels"]]
        self.n, self.h, self.w = len(self.g), len(self.g[0]), len(self.g[0][0])
        self.join = next((x, 0) for x, ch in enumerate(self.g[0][0]) if ch == "@")
        self.built: dict = {}
        self.sc: dict = {}

    def ch(self, i, x, y):
        if 1 <= i <= self.n and 0 <= x < self.w and 0 <= y < self.h:
            return self.g[i - 1][y][x]
        return None

    def eff(self, i, x, y, extra=None):
        p = (i, x, y)
        if extra and p in extra:
            return extra[p]
        return self.sc.get(p) or self.built.get(p)

    def walk(self, i, x, y, extra=None):
        if self.ch(i, x, y) is None:
            return False
        b = self.eff(i, x, y, extra)
        if b in ("W", "O"):
            return False
        if b:
            return True
        if i == 1:
            return self.ch(1, x, y) != "_"
        return self.eff(i - 1, x, y, extra) == "W"

    def reach(self, extra=None) -> set:
        start = (1,) + self.join
        seen, todo = {start}, [start]
        while todo:
            i, x, y = todo.pop()
            b = self.eff(i, x, y, extra)
            nxt = [(i, x + dx, y + dy) for dx, dy in N8]
            if b in ("U", "I") and self.eff(i + 1, x, y, extra) in ("D", "I"):
                nxt.append((i + 1, x, y))
            if b in ("D", "I") and self.eff(i - 1, x, y, extra) in ("U", "I"):
                nxt.append((i - 1, x, y))
            if b == "R":
                nxt += [(i + 1, x + dx, y + dy) for dx, dy in N8]
            nxt += [(i - 1, x + dx, y + dy) for dx, dy in N8 if self.eff(i - 1, x + dx, y + dy, extra) == "R"]
            for p in nxt:
                if p not in seen and self.walk(*p, extra=extra):
                    seen.add(p)
                    todo.append(p)
        return seen

    def stand(self, seen, i, x, y, stair):
        if any((i, x + dx, y + dy) in seen for dx, dy in N8):
            return True
        return stair and (i - 1, x, y) in seen and self.eff(i - 1, x, y) in ("U", "I")


def replay(bp, steps) -> list[str]:
    """Problems found replaying the plan (empty: a safe plan)."""
    want = jobs_of(bp)
    W = World(bp)
    done: dict = {}
    bad = []
    for s_i, st in enumerate(steps, 1):
        i = st["level"]
        before = W.reach()
        if st["kind"] == "remove":
            (gx, gy, text, _, _), = st["cells"]
            if (i, gx, gy) not in W.sc or (i + 1, gx, gy) in W.sc:
                bad.append(f"step {s_i}: not the top of a standing scaffold")
                continue
            if not W.stand(before, i, gx, gy, False) and not ((i - 1, gx, gy) in before and (i - 1, gx, gy) in W.sc):
                bad.append(f"step {s_i}: no one can take it down")
            del W.sc[(i, gx, gy)]
            continue
        cells = st["cells"]
        kinds = set()
        for gx, gy, text, _, _ in cells:
            kind = "door" if text == "d" else "c"
            if st["kind"] == "build":
                if (i, gx, gy, kind) not in want or want[(i, gx, gy, kind)] != text:
                    bad.append(f"step {s_i}: {text} at L{i} x{gx} y{gy} is not in the drawing")
                if (i, gx, gy, kind) in done:
                    bad.append(f"step {s_i}: L{i} x{gx} y{gy} built twice")
                if i > 1 and (i - 1, gx, gy, "c") in want and (i - 1, gx, gy, "c") not in done:
                    bad.append(f"step {s_i}: L{i} x{gx} y{gy} before what it stands on")
                if kind == "door" and (i, gx, gy, "c") in want and (i, gx, gy, "c") not in done:
                    bad.append(f"step {s_i}: a door before its floor")
                kinds.add("solid" if text in ("Cw", "CF", "d") else "floor")
            else:
                if W.ch(i, gx, gy) != ("." if i == 1 else "_"):
                    bad.append(f"step {s_i}: scaffold inside the finished shape at L{i} x{gx} y{gy}")
        if len(kinds) > 1:
            bad.append(f"step {s_i}: floors and walls in one step")
        if st["kind"] == "scaffold":
            (gx, gy, text, _, _), = cells
            if not W.stand(before, i, gx, gy, True):
                bad.append(f"step {s_i}: the scaffold tile can't be reached")
            W.sc[(i, gx, gy)] = "U" if i == 1 else "I"
            continue
        if kinds == {"floor"}:
            left = {(gx, gy): text for gx, gy, text, _, _ in cells}
            extra: dict = {}
            grew = True
            while left and grew:
                grew = False
                seen = W.reach(extra)
                for (gx, gy), text in list(left.items()):
                    stair = text in ("Cu", "Cd", "Cx")
                    if any((i, gx + dx, gy + dy) in seen for dx, dy in N8) or (
                            stair and (i - 1, gx, gy) in seen and W.eff(i - 1, gx, gy, extra) in ("U", "I")):
                        extra[(i, gx, gy)] = SYM[text]
                        del left[(gx, gy)]
                        grew = True
            if left:
                bad.append(f"step {s_i}: {len(left)} floor tile(s) no one reaches")
        else:
            extra = {(i, gx, gy): SYM[text] for gx, gy, text, _, _ in cells if text != "d"}
            after = W.reach(extra)
            for gx, gy, text, _, _ in cells:
                if not W.stand(after, i, gx, gy, False):
                    bad.append(f"step {s_i}: L{i} x{gx} y{gy} may lose its builder's place")
            cut = [p for p in before if p not in after and W.walk(*p, extra=extra)]
            if cut:
                bad.append(f"step {s_i}: walls a dwarf in at {sorted(cut)[:3]}")
        for gx, gy, text, _, _ in cells:
            kind = "door" if text == "d" else "c"
            done[(i, gx, gy, kind)] = True
            if kind == "c":
                W.built[(i, gx, gy)] = SYM[text]
            else:
                W.built.setdefault((i, gx, gy), "d")
    missing = [k for k in want if k not in done]
    if missing:
        bad.append(f"{len(missing)} tile(s) never built, e.g. {missing[:2]}")
    if W.sc:
        bad.append(f"scaffolding left standing: {sorted(W.sc)}")
    return bad


def surface_drawings() -> dict:
    out = {}
    for f in sorted(list(FIXTURES.glob("good_*.json")) + list(LIBRARY.glob("*.json"))):
        bp = json.loads(f.read_text(encoding="utf-8"))
        if bp.get("ground") == "surface":
            out[f.name] = bp
    return out


def surface(levels, name="The Test"):
    return {"v": 1, "name": name, "purpose": "tower", "ground": "surface",
            "levels": [{"grid": g} for g in levels], "legend": {}}


# a needle of walls 4 levels high, nothing to climb: built from a scaffold stair
OBELISK = surface([["..@..", ".....", "..W..", ".....", "....."]]
                  + [["_____", "_____", "__W__", "_____", "_____"]] * 3, "The Needle")
# a ring of walls with no door: its inside is reached over the top, by the
# stairs inside and outside; the wall that closes it goes up last
RING = surface([["..@....", "U......", ".WWWWW.", ".W...W.", ".W.U.W.", ".W...W.", ".WWWWW."],
                ["_______", "D______", "_....._", "_.FFF._", "_.FDF._", "_.FFF._", "_....._"]], "The Closed Ring")
# nothing walkable beside it but the join: no scaffold can stand anywhere
SEALED = surface([["W@W", "WWW"], ["W_W", "WWW"]], "The Sealed")

test = make_test()


@test("every surface drawing (fixtures, library) gets a plan the checker replays as safe, in every turn")
def _():
    ds = surface_drawings()
    assert len(ds) >= 3, list(ds)
    for name, bp in ds.items():
        for q in range(4):
            r, why = stages(bp, q)
            assert r is not None, (name, q, why)
            bad = replay(bp, as_steps(r))
            assert not bad, (name, q, bad[:4])


@test("the plan is the same every time, and a turn only turns its cells (the grid positions stay)")
def _():
    for bp in list(surface_drawings().values()) + [OBELISK, RING]:
        a = as_steps(stages(bp, 0)[0])
        assert a == as_steps(stages(bp, 0)[0])
        for q in range(1, 4):
            b = as_steps(stages(bp, q)[0])
            strip = lambda s: [(x["kind"], x["level"], [c[:3] for c in x["cells"]]) for x in s]  # noqa: E731
            assert strip(a) == strip(b), (bp["name"], q)
            for sa, sb in zip(a, b):
                for ca, cb in zip(sa["cells"], sb["cells"]):
                    x, y = ca[3], ca[4]
                    for _ in range(q):
                        x, y = -y, x
                    assert (x, y) == (cb[3], cb[4]), (bp["name"], q, ca, cb)


@test("levels go up from the bottom; on each, floors and stairs before walls; the library ziggurat needs no scaffold")
def _():
    for name, bp in surface_drawings().items():
        r, _ = stages(bp)
        steps = [s for s in as_steps(r) if s["kind"] == "build"]
        levels = [s["level"] for s in steps]
        assert levels == sorted(levels) or name == "x", (name, levels)
        if name == "ziggurat.json":
            assert r.scaffold.columns == 0 and r.scaffold.tiles == 0
            assert steps[0]["cells"][0][2] == "Cu", steps[0]       # the stair up first, then the walls
            assert {c[2] for c in steps[1]["cells"]} <= {"Cw", "d"}


@test("a needle with nothing to climb: one scaffold column up beside it, then down top first after the last wall")
def _():
    r, why = stages(OBELISK)
    assert r is not None, why
    assert r.scaffold.columns == 1 and r.scaffold.tiles == 4, (r.scaffold.columns, r.scaffold.tiles)
    s = as_steps(r)
    kinds = [(x["kind"], x["level"]) for x in s]
    assert kinds == [("build", 1), ("scaffold", 1), ("scaffold", 2), ("build", 2), ("scaffold", 3), ("build", 3),
                     ("scaffold", 4), ("build", 4), ("remove", 4), ("remove", 3), ("remove", 2), ("remove", 1)], kinds
    col = {(c[0], c[1]) for x in s if x["kind"] != "build" for c in x["cells"]}
    assert len(col) == 1
    (cx, cy), = col
    assert OBELISK["levels"][0]["grid"][cy][cx] == "." and max(abs(cx - 2), abs(cy - 2)) == 1, col
    texts = [x["cells"][0][2] for x in s if x["kind"] == "scaffold"]
    assert texts == ["Cu", "Cx", "Cx", "Cx"], texts
    assert not replay(OBELISK, s)


@test("inside-out: the wall that closes a ring waits until the stairs over the top give the inside another way out")
def _():
    r, why = stages(RING)
    assert r is not None, why
    s = as_steps(r)
    assert r.scaffold.columns == 0
    last = s[-1]
    assert last["kind"] == "build" and last["level"] == 1 and [c[2] for c in last["cells"]] == ["Cw"], s[-1]
    up = next(k for k, x in enumerate(s) if x["level"] == 2)
    assert up < len(s) - 1
    assert not replay(RING, s)
    # the checker sees the danger the order avoids: every wall of level 1 at once
    walls = [(x, y, "Cw", 0, 0) for y, row in enumerate(RING["levels"][0]["grid"]) for x, ch in enumerate(row)
             if ch == "W"]
    naive = [{"kind": "build", "level": 1, "cells": [(0, 1, "Cu", 0, 0), (3, 4, "Cu", 0, 0)]},
             {"kind": "build", "level": 1, "cells": walls}]
    assert any("walls a dwarf in" in b for b in replay(RING, naive))


@test("no safe order: refused with ORDER and a position on the drawing; a rock drawing has no steps")
def _():
    r, why = stages(SEALED)
    assert r is None and why and why[0]["code"] == "ORDER" and why[0]["level"] == 2, why
    assert why[0]["words"].startswith("L2 x0 y0: "), why
    rock = json.loads((FIXTURES / "good_small_room.json").read_text(encoding="utf-8"))
    rr, _ = stages(rock)
    assert rr is not None and len(ll(rr.list)) == 0 and rr.scaffold.tiles == 0
    bad, why2 = stages({"v": 1, "ground": "surface", "levels": []})
    assert bad is None and why2[0]["code"] == "FORMAT"


@test("scaffolding has its limits (SCAFFOLD_MAX): over them the drawing is refused")
def _():
    old = BP.SCAFFOLD_MAX.tiles
    try:
        BP.SCAFFOLD_MAX.tiles = 3
        r, why = stages(OBELISK)
        assert r is None and why[0]["code"] == "ORDER" and "scaffolding" in why[0]["words"], why
    finally:
        BP.SCAFFOLD_MAX.tiles = old


@test("Scripts identity: to_layouts, check_format and cost give byte-identical results to merged0's")
def _():
    try:
        old_src = subprocess.run(["git", "-C", str(ROOT), "show", "merged0:lua/ai-blueprints.lua"],
                                 capture_output=True, text=True, check=True).stdout
    except Exception as e:  # noqa: BLE001
        print(f"SKIPPED part: no merged0 to compare with ({e})")
        return
    OLD = _load(LAYOUTS_SRC, old_src)
    files = sorted(FIXTURES.glob("*.json")) + sorted(LIBRARY.glob("*.json"))
    for f in files:
        bp = plt(json.loads(f.read_text(encoding="utf-8")))
        for q in range(4):
            assert DUMP(BP.to_layouts, bp, q) == DUMP(OLD.to_layouts, bp, q), (f.name, q)
        assert DUMP(BP.check_format, bp) == DUMP(OLD.check_format, bp), f.name
        assert DUMP(BP.cost, bp) == DUMP(OLD.cost, bp), f.name


@test("random drawings that pass the format: every plan made replays as safe (the rest refused with ORDER)")
def _():
    import random
    rnd = random.Random(5)
    made = refused = 0
    for _ in range(8000):
        w, h, n = rnd.randint(3, 8), rnd.randint(3, 8), rnd.randint(2, 4)
        g1 = [[rnd.choice("..WWWF+U") for _x in range(w)] for _y in range(h)]
        g1[0][rnd.randrange(w)] = "@"
        lv = [g1]
        for _i in range(1, n):
            nxt = {"_": "_", "W": "..WWU_", "U": "DI", "I": "DI"}
            lv.append([[rnd.choice(nxt.get(b, "_FFW")) for b in row] for row in lv[-1]])
        bp = surface([["".join(r) for r in g] for g in lv])
        if not BP.check_format(plt(bp))[0]:
            continue
        r, why = stages(bp, rnd.randrange(4))
        if r is None:
            assert why and why[0]["code"] == "ORDER", why
            refused += 1
            continue
        made += 1
        bad = replay(bp, as_steps(r))
        assert not bad, (json.dumps(bp), bad[:3])
    assert made >= 50 and refused < made, (made, refused)


@test("a big drawing (a 13x13 block of walls under an 11x11 one, 290 built tiles) plans quickly and safely")
def _():
    import time
    l1 = ["." * 7 + "@" + "." * 7, "U" + "W" * 13 + "."] + ["." + "W" * 13 + "." for _ in range(12)] + ["." * 15]
    l2 = ["_" * 15, "D" + "." * 13 + "_"] + ["_." + "W" * 11 + "._" for _ in range(11)] + ["_" + "." * 13 + "_", "_" * 15]
    big = surface([l1, l2], "The Block")
    t = time.perf_counter()
    r, why = stages(big)
    dt = time.perf_counter() - t
    assert r is not None, why
    assert not replay(big, as_steps(r))
    assert dt < 2.0, dt


# --- the builder on the fake fort ------------------------------------------------

_tree = ast.parse((ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"))
HARNESS = next(n.value.value for n in _tree.body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def boot():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    B, W = lua.execute(HARNESS, LAYOUTS_SRC, (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    src = (LUA_DIR / "ai-blueprints.lua").read_text(encoding="utf-8")
    lua.globals().BPM = lua.eval("""function(src)
        local env = setmetatable({}, {__index = _G})
        assert(load(src, 'ai-blueprints', 't', env))()
        return env end""")(src)
    lua.execute("""
      local old = _G.reqscript
      _G.reqscript = function(name) if name == 'ai-blueprints' then return BPM end return old(name) end
      df = df or {}
      df.global = df.global or {}
      df.global.world = df.global.world or {}
      df.global.world.buildings = {other = {TRADE_DEPOT = {}}, all = {}}
    """)
    return lua, B, W


LUA, B, W = boot()
T = LUA.table_from
REAL = {k: B[k] for k in ("landmark_stock", "landmark_times", "hall_planned_at", "units_on", "remove_construction")}
LUA.globals().W_PEEK = W.peek


def lt(d):
    if isinstance(d, dict):
        return LUA.table_from({k: lt(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([lt(v) for v in d])
    return d


def _reset():
    W.reset()
    for k, v in REAL.items():
        B[k] = v
    B.landmark_stock = LUA.eval("function() return 1000 end")
    B.landmark_times = LUA.eval("function() return nil end")
    B.hall_planned_at = LUA.eval("function(x, y, z) local t = W_PEEK(x, y, z); return t ~= nil and t.planned == true end")
    LUA.execute("UNITS_ON = 0; REMOVED = {}")
    B.units_on = LUA.eval("function(tiles) return UNITS_ON end")
    B.remove_construction = LUA.eval("""function(x, y, z, dry)
        if not dry then table.insert(REMOVED, {x = x, y = y, z = z}) end return true end""")


btest = make_test(before=_reset)
NOW = {"year": 150, "tick": 100}


def field(x1, y1, x2, y2, z=80, up=4):
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            W.set(x, y, z, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            for k in range(1, up + 1):
                W.set(x, y, z + k, T({"shape": "EMPTY", "outside": True}))


def offer(ax=80, ay=50):
    W.persist["ai-overseer/bp-sites"] = lt({"asked": 0, "list": [{"id": "S1", "ground": "surface", "z": 80,
                                                                   "anchor": {"x": ax, "y": ay}, "q": 0}]})


def meta(**kw):
    m = {"name": "The Needle", "purpose": "tower", "by": "library", "cap": 2500}
    m.update(kw)
    return lt(m)


SHAPE = {"Cw": "WALL", "Cf": "FLOOR", "Cu": "STAIR_UP", "Cd": "STAIR_DOWN", "Cx": "STAIR_UPDOWN", "CF": "FORTIFICATION"}


def build_all():
    gone = {(c.x, c.y, c.z) for c in ll(LUA.eval("REMOVED"))}
    for c in ll(W.placed):
        if c.mode == "build" and c.text in SHAPE and (c.x, c.y, c.z) not in gone:
            W.set(c.x, c.y, c.z, T({"shape": SHAPE[c.text], "building": False}))


def take_down():
    for c in ll(LUA.eval("REMOVED")):
        W.set(c.x, c.y, c.z, T({"shape": "FLOOR" if c.z == 80 else "EMPTY", "building": False}))


def report():
    return ll(B.landmarks_report().list)[0]


@btest("the needle on the fake fort: scaffold up, walls, scaffold down (waiting while a dwarf is on it), then done")
def _():
    field(70, 45, 90, 60)
    offer()
    r = B.build_landmark(lt(OBELISK), "S1", meta(), lt(NOW), False)
    assert r.ok, dict(r)
    rec = ll(B.landmarks_data().list)[0]
    assert len(ll(rec.steps)) == 12 and rec.scaffold.tiles == 4 and rec.step == 0
    seen, removed_at = [], None
    for _ in range(40):
        s = B.landmark_step(1, False)
        if not s.ok and not s.waiting:
            raise AssertionError(dict(s))
        if s.ok:
            seen.append((s.stage, s.level))
        if s.done:
            break
        rep = report()
        if s.ok and s.stage == "build" and s.level == 4:
            # the last wall up: the report says the scaffolding may come down, and the brain says so
            build_all()
            rep = report()
            assert rep.scaffold.ready and rep.scaffold.next == "remove" and rep.scaffold.up == 4, dict(rep.scaffold)
            import planner_design
            words = planner_design.step_words({"stage": rep.stage, "scaffold": dict(rep.scaffold)})
            assert words.startswith("take down the scaffolding"), words
            LUA.execute("UNITS_ON = 1")
            w = B.landmark_step(1, False)
            assert not w.ok and w.waiting and "on or above the scaffolding" in w.error, dict(w)
            assert len(ll(LUA.eval("REMOVED"))) == 0
            LUA.execute("UNITS_ON = 0")
            continue
        if s.ok and s.stage == "remove":
            if removed_at is None:
                removed_at = len(seen)
                w = B.landmark_step(1, False)
                assert not w.ok and w.waiting and w.stage == "remove", dict(w)
                assert report().scaffold.up == 4
            take_down()
        build_all()
    assert seen[-1][0] == "zone" or seen[-1][0] == "furnish" or s.done, seen
    assert s.done, (seen, dict(s))
    removed = ll(LUA.eval("REMOVED"))
    zs = [c.z for c in removed]
    zs = [z for k, z in enumerate(zs) if k == 0 or zs[k - 1] != z]     # (a wait marks it again)
    assert zs == [83, 82, 81, 80], zs                                   # top first
    assert len({(c.x, c.y) for c in removed}) == 1
    placed = [c for c in ll(W.placed) if c.mode == "build"]
    assert sorted(c.z for c in placed if c.text == "Cw") == [80, 81, 82, 83]
    assert [c.text for c in placed if c.text in ("Cu", "Cx")] == ["Cu", "Cx", "Cx", "Cx"]
    assert ll(B.landmarks_data().list)[0].status == "built"


@btest("a scaffold stair's tiles are checked in the air: not open air there -> refused (SURFACE), on the drawing's grid")
def _():
    field(70, 45, 90, 60)
    offer()
    s = BP.build_stages(plt(OBELISK), 0)
    col = next(c for st in ll(s.list) if st.kind == "scaffold" and st.level == 3 for c in ll(st.cells))
    W.set(80 + col.x, 50 + col.y, 82, T({"shape": "WALL", "outside": False}))
    r = B.build_landmark(lt(OBELISK), "S1", meta(), lt(NOW), True)
    assert not r.ok and r.rejected, dict(r)
    rs = ll(r.reasons)
    assert rs[0].code == "SURFACE" and "scaffold" in rs[0].words and rs[0].level == 3, [dict(x) for x in rs]
    assert (rs[0].x, rs[0].y) == (col.gx, col.gy)


@btest("no safe order on the map: build_blueprint's refusal carries ORDER; the scaffolding counts against the stock")
def _():
    field(70, 45, 90, 60)
    offer()
    r = B.build_landmark(lt(SEALED), "S1", meta(name="The Sealed"), lt(NOW), True)
    assert not r.ok and ll(r.reasons)[0].code == "ORDER", [dict(x) for x in ll(r.reasons)]
    assert "L2 x0 y0: " in ll(r.reasons)[0].words
    # 4 walls + 4 scaffold tiles against 60% of the stock: 12 on hand gives 7.2
    B.landmark_stock = LUA.eval("function() return 12 end")
    r = B.build_landmark(lt(OBELISK), "S1", meta(), lt(NOW), True)
    assert not r.ok and any(x.code == "STOCK" and x.words.startswith("8 built") for x in ll(r.reasons)), \
        [dict(x) for x in ll(r.reasons)]
    B.landmark_stock = LUA.eval("function() return 14 end")
    assert B.build_landmark(lt(OBELISK), "S1", meta(), lt(NOW), True).ok


@btest("an old record (no steps, from before E2) still walks its old stages")
def _():
    field(70, 45, 90, 60)
    offer()
    tower = surface([["WW@WW", "W...W", "W.U.W", "W...W", "WWWWW"],
                     ["..F..", ".FFF.", ".FDF.", ".FFF.", "....."]], "The Tower")
    saved = LUA.eval("BPM.build_stages")
    LUA.execute("BPM.build_stages = nil")
    try:
        r = B.build_landmark(lt(tower), "S1", meta(name="The Tower"), lt(NOW), False)
    finally:
        LUA.globals().BPM.build_stages = saved
    assert r.ok
    rec = ll(B.landmarks_data().list)[0]
    assert rec.steps is None and len(ll(rec.surface[1].walls)) > 0
    names = []
    for _ in range(12):
        s = B.landmark_step(1, False)
        if s.ok:
            names.append(s.stage)
        if s.done:
            break
        build_all()
    assert names == ["walls", "floor", "next level", "floor", "furnish", "zone"], names
    assert report().scaffold is None and report().steps is None


@btest("a dry step changes nothing; the report reads step, steps and the scaffolding")
def _():
    field(70, 45, 90, 60)
    offer()
    assert B.build_landmark(lt(OBELISK), "S1", meta(), lt(NOW), False).ok
    n = len(ll(W.placed))
    s = B.landmark_step(1, True)
    assert s.ok and s.dry_run and s.stage == "build" and s.step == 1, dict(s)
    assert len(ll(W.placed)) == n and ll(B.landmarks_data().list)[0].stage == "clearing"
    rep = report()
    assert rep.step == 0 and rep.steps == 12 and rep.scaffold.tiles == 4 and rep.scaffold.up == 0, dict(rep)


@test("brain: the step's words, unchanged for a report without scaffolding")
def _():
    import planner_design as pd
    assert pd.step_words({"stage": "walls"}) == "the next step (walls)"
    assert pd.step_words({"stage": "build", "scaffold": {"ready": True, "next": "scaffold", "up": 0}}).startswith(
        "put up a scaffold stair")
    assert pd.step_words({"stage": "remove", "scaffold": {"ready": None, "next": "remove", "up": 2}}).startswith(
        "the scaffolding coming down (2")
    assert pd.step_words({"stage": "build", "scaffold": "junk"}) == "the next step (build)"


@test("the changed Lua compiles under 5.3")
def _():
    c = LuaRuntime(unpack_returned_tuples=True)
    chk = c.eval("function(src, name) local f, e = load(src, name, 't', {}) return f ~= nil, e end")
    for f in ("ai-blueprints.lua", "ai-builder-landmarks.lua"):
        ok, err = chk((LUA_DIR / f).read_text(encoding="utf-8"), f)
        assert ok, (f, err)


if __name__ == "__main__":
    finish()
