"""Tests for lua/ai-floorplace.lua (layout B: where halls and rooms go on a
floor), run in a real Lua engine (pip install lupa).

    python tests/test_b2_floorplace.py

The module sees the map only through `env`; here that is a small fake grid
written in Lua (rock everywhere, with open tiles, bad tiles, other projects'
boxes and tiles the probe refuses where a test needs them). ai-floorplan's
`commit` is another group's: a test "commits" a placement by appending its
runs and slots to the floor table by hand.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402

try:
    import lupa  # noqa: F401
    from lupa.lua53 import LuaRuntime, lua_type
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

try:                                     # a drawing for a failure's output, when the helper is there
    sys.path.insert(0, str(ROOT / "brain" / "tools"))
    from draw_level import render as _render
except Exception:  # noqa: BLE001
    _render = None

SRC = (ROOT / "lua" / "ai-floorplace.lua").read_text(encoding="utf-8")
LUA = LuaRuntime(unpack_returned_tuples=True)
M = LUA.eval("function(src) local env = setmetatable({}, {__index=_G}); "
             "assert(load(src, 'ai-floorplace', 't', env))(); return env end")(SRC)

# The fake map, the hand-made commit and a few helpers, in Lua (as the real env is).
H = LUA.eval(r"""
(function()
  local H = {}
  local function get(t, x, y) local c = t[x]; return c and c[y] end
  local function set(t, x, y, v) local c = t[x]; if not c then c = {}; t[x] = c end; c[y] = v end
  H.get, H.set = get, set

  -- world: cells[x][y] = 'open' | 'bad' (else rock); boxes: other projects' tiles; refuse[x][y]: the probe says no
  function H.world() return {cells = {}, boxes = {}, refuse = {}, nboxes = 0} end
  function H.cell(w, x, y, v) set(w.cells, x, y, v) end
  function H.box(w, x1, y1, x2, y2) w.nboxes = w.nboxes + 1; w.boxes[w.nboxes] = {x1, y1, x2, y2} end
  function H.refuse(w, x, y) set(w.refuse, x, y, true) end

  -- opts: seed, bounds = {x1, y1, x2, y2}, late_after (calls of late() answered false), strict (the probe checks borders)
  function H.env(w, opts)
    opts = opts or {}
    local env = {seed = opts.seed or 0, n_probe = 0, n_late = 0, log = {}}
    if opts.bounds then
      env.bounds = {x1 = opts.bounds[1], y1 = opts.bounds[2], x2 = opts.bounds[3], y2 = opts.bounds[4]}
    end
    local cells, boxes, refuse = w.cells, w.boxes, w.refuse
    env.open = function(x, y) return get(cells, x, y) or 'rock' end
    env.blocked = function(x1, y1, x2, y2)
      for i = 1, w.nboxes do
        local b = boxes[i]
        if b[1] <= x2 and b[3] >= x1 and b[2] <= y2 and b[4] >= y1 then return true end
      end
      return false
    end
    env.late = function()
      env.n_late = env.n_late + 1
      return opts.late_after ~= nil and env.n_late > opts.late_after
    end
    env.probe = function(tiles, known, role)
      env.n_probe = env.n_probe + 1
      assert(type(tiles) == 'table' and #tiles > 0, 'probe: no tiles')
      assert(type(known) == 'table', 'probe: known is not a table')
      assert(role == 'hall' or role == 'room', 'probe: role ' .. tostring(role))
      env.log[#env.log + 1] = {role = role, n = #tiles}
      local mine = {}
      for _, t in ipairs(tiles) do
        assert(not (t.x == 0 and t.y == 0), 'probe: the stair tile')
        assert(not get(mine, t.x, t.y), 'probe: a tile twice')
        set(mine, t.x, t.y, true)
      end
      for _, t in ipairs(tiles) do
        if get(refuse, t.x, t.y) then return false, 'damp stone' end
        if opts.strict then
          if (get(cells, t.x, t.y) or 'rock') ~= 'rock' then return false, 'not rock' end
          for dx = -1, 1 do
            for dy = -1, 1 do
              local x, y = t.x + dx, t.y + dy
              if not get(mine, x, y) and not (x == 0 and y == 0) then
                local c = get(cells, x, y) or 'rock'
                local fine = c == 'rock' or get(known, x, y) or (role == 'hall' and c == 'open')
                if not fine then return false, 'border ' .. x .. ',' .. y end
              end
            end
          end
        end
      end
      return true
    end
    return env
  end

  function H.floor(id) return {id = id or 1, z = 100, stair = {x = 50, y = 50}, made = 0, runs = {}, slots = {}} end

  -- ai-floorplan.commit, by hand: the placement's runs and slots into the floor table
  function H.commit(floor, P, pid)
    floor.hub = floor.hub or 'dug'
    for _, r in ipairs(P.runs) do
      if r.new then
        table.insert(floor.runs, {id = r.id, parent = r.parent, ox = r.ox, oy = r.oy, dx = r.dx, dy = r.dy,
                                  len = r.len, walked = r.walked, tag = r.tag, node = r.node, neck = r.neck,
                                  closed = r.closed})
      else
        for _, fr in ipairs(floor.runs) do
          if fr.id == r.id then fr.len = r.len; fr.closed = r.closed end
        end
      end
    end
    for _, p in ipairs(P.puts) do
      table.insert(floor.slots, {run = p.run, side = p.side, u = p.u, w = p.w, d = p.d, pid = pid,
                                 kind = P.req.kind, tag = P.req.tag, group = P.req.group, role = p.role,
                                 flag = p.flag})
    end
  end

  -- a canonical text of any table (sorted keys): for "nothing was changed"
  local function dump(v, seen)
    if type(v) ~= 'table' then return type(v) == 'string' and string.format('%q', v) or tostring(v) end
    seen = seen or {}
    assert(not seen[v], 'a cycle')
    seen[v] = true
    local keys = {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys, function(a, b)
      if type(a) == type(b) then return a < b end
      return type(a) < type(b)
    end)
    local out = {}
    for _, k in ipairs(keys) do out[#out + 1] = '[' .. dump(k) .. ']=' .. dump(v[k], seen) end
    seen[v] = nil
    return '{' .. table.concat(out, ',') .. '}'
  end
  H.dump = dump

  function H.to_json_like(v) return dump(v) end

  function H.globals()
    local out = {}
    for k in pairs(_G) do out[#out + 1] = tostring(k) end
    table.sort(out)
    return table.concat(out, ' ')
  end

  function H.keys(t)
    local out = {}
    for k in pairs(t) do out[#out + 1] = tostring(k) end
    table.sort(out)
    return table.concat(out, ' ')
  end

  -- place() n times, for the clock
  function H.many(M, floor, req, G, env, n)
    local ok = 0
    for _ = 1, n do
      if M.place(floor, req, G, env) then ok = ok + 1 end
    end
    return ok
  end
  return H
end)()
""")


# ------------------------------------------------------------------ helpers

def lt(v):
    """A Python value as a Lua value (lists and dicts as tables)."""
    if isinstance(v, dict):
        t = LUA.table()
        for k, x in v.items():
            t[k] = lt(x)
        return t
    if isinstance(v, (list, tuple)):
        t = LUA.table()
        for i, x in enumerate(v):
            t[i + 1] = lt(x)
        return t
    return v


def py(v):
    """A Lua value as a Python one (a table with keys 1..n as a list)."""
    if lua_type(v) != "table":
        return v
    keys = list(v.keys())
    n = len(keys)
    if n == 0:
        return []
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, n + 1)):
        return [py(v[i]) for i in range(1, n + 1)]
    return {k: py(v[k]) for k in keys}


G_DEFAULT = dict(gap=1, kind_gap=1, lead=2, ahead=1, run_max=30, run_min=10, arms_max=2, dirs=[], sides="both",
                 stagger=0, bay=0, node=3, grow=["arm", "turn"], turns="alternate", balance=False, axial=False,
                 neck=False, tries=24, full_retry_days=28)


def grammar(**over):
    g = dict(G_DEFAULT)
    g.update(over)
    return lt(g)


def unit(w=3, d=3, role="room", flag=None, open_=None):
    if open_ is None:
        open_ = ((w - 1) // 2, (w - 1) // 2)
    u = {"w": w, "d": d, "role": role, "open": {"x0": open_[0], "x1": open_[1]}}
    if flag:
        u["flag"] = flag
    return u


def request(units, kind="bedrooms", tag="homes", **kw):
    r = {"kind": kind, "tag": tag, "units": units}
    r.update(kw)
    return lt(r)


def rooms(n, w=3, d=3):
    return [unit(w, d) for _ in range(n)]


def place(floor, req, G, env):
    res = M.place(floor, req, G, env)
    if isinstance(res, tuple):
        P, why = res
    else:
        P, why = res, None
    return (py(P) if P is not None else None), why, P


def placed(floor, req, G, env, pid=1):
    """place and commit; the placement as Python, asserting it worked."""
    P, why, raw = place(floor, req, G, env)
    assert P is not None, f"place refused: {why}"
    H.commit(floor, raw, pid)
    return P


def spots(P):
    return [(p["side"], p["u"]) for p in P["puts"]]


def tiles(lst):
    return [(t["x"], t["y"]) for t in lst]


def run_of(P, i=0):
    return P["runs"][i]


def fresh(**env_opts):
    w = H.world()
    return w, H.env(w, lt(env_opts) if env_opts else None), H.floor()


EAST = dict(dirs=["east"])
HUB8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


# ------------------------------------------------------------------ an independent check of a floor
# The geometry again, in Python, from the contract's words: used by the
# obstacle, growth and property tests to check whatever place() answered.

def r_tile(r, u, v):
    px, py_ = -r["dy"], r["dx"]
    return (r["ox"] + u * r["dx"] + v * px, r["oy"] + u * r["dy"] + v * py_)


def r_u0(r):
    return 3 if (r["node"] == 5 and r["parent"] != 0) else 2


def r_hall(r):
    out = set()
    u0 = r_u0(r)
    for u in range(u0, u0 + r["len"]):
        for v in (-1, 0, 1):
            if r.get("neck") and u == u0 and v != 0:
                continue
            out.add(r_tile(r, u, v))
    return out


def r_node(r):
    n = 2 if (r["node"] == 5 and r["parent"] != 0) else 1
    return {(r["ox"] + a, r["oy"] + b) for a in range(-n, n + 1) for b in range(-n, n + 1)}


def r_core(r):
    return {(r["ox"] + a, r["oy"] + b) for a in (-1, 0, 1) for b in (-1, 0, 1)}


def rect_tiles(rc):
    return {(x, y) for x in range(rc["x1"], rc["x2"] + 1) for y in range(rc["y1"], rc["y2"] + 1)}


def xf(T, bx, by):
    return (T["a"] * bx + T["b"] * by + T["tx"], T["c"] * bx + T["d"] * by + T["ty"])


class Checker:
    """Follows one floor through its placements and checks each against the rules."""

    def __init__(self, world=None):
        self.cells = {}            # (x, y) -> 'open' | 'bad', as the test set them
        self.boxes = []
        self.runs = {}             # id -> run row (as committed)
        self.puts = []             # every put so far, with its request's opening
        self.listed = set()        # every tile ever in a placement's hall
        self.hub_done = False

    def state(self, x, y):
        return self.cells.get((x, y), "rock")

    def hall_all(self):
        out = set(HUB8) | {(0, 0)}
        for r in self.runs.values():
            out |= r_hall(r)
            if r["parent"] != 0:
                out |= r_node(r)
        return out

    def draw(self, P=None):
        if not _render:
            return ""
        cells = set(self.hall_all())
        for p in self.puts:
            cells |= p["room"]
        try:
            return "\n" + _render(sorted(cells))
        except Exception:  # noqa: BLE001
            return ""

    def add(self, P, units):
        before = self.hall_all() if self.runs else set()
        # the runs
        for r in P["runs"]:
            if r["new"]:
                assert r["id"] not in self.runs, f"run id {r['id']} used twice"
                assert r["len_before"] == 0
                assert r["id"] == max(list(self.runs) + [0]) + 1, "a new run takes the next free id"
                self.runs[r["id"]] = dict(r)
            else:
                old = self.runs[r["id"]]
                assert r["len_before"] == old["len"], (r, old)
                assert r["len"] >= old["len"]
                old["len"] = r["len"]
                old["closed"] = r.get("closed")
            if r["parent"] != 0 and r["new"]:
                par = self.runs[r["parent"]]
                e = r_u0(par) + par["len"] - 1
                assert (r["ox"], r["oy"]) == r_tile(par, e - 1, 0), "a turn leaves one column in from the end"
                assert r["dx"] * par["dx"] + r["dy"] * par["dy"] == 0, "a turn is a right angle"
        after = self.hall_all()
        hall = tiles(P["hall"])
        # the hall list
        assert len(hall) == len(set(hall)), "a hall tile listed twice"
        assert (0, 0) not in hall, "the stair tile in hall"
        assert not (set(hall) & self.listed), "a hall tile listed by an earlier placement too"
        for t in hall:
            assert self.state(*t) == "rock", f"hall tile {t} was {self.state(*t)}"
        new = after - before - {(0, 0)}
        assert set(hall) == {t for t in new if self.state(*t) == "rock"}, \
            ("hall is not exactly the new rock tiles", sorted(set(hall) ^ {t for t in new if self.state(*t) == 'rock'}))
        for t in new:
            assert self.state(*t) != "bad", f"a bad tile {t} taken as hall"
        assert P["hall_new"] == len(hall)
        self.listed |= set(hall)
        # every hall tile walks to the stair through hall tiles
        seen, todo = {(0, 0)}, [(0, 0)]
        while todo:
            x, y = todo.pop()
            for n in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if n in after and n not in seen:
                    seen.add(n)
                    todo.append(n)
        assert seen == after, ("hall tiles cut off from the stair", sorted(after - seen)[:6])
        # the puts
        assert sorted(p["unit"] for p in P["puts"]) == list(range(1, len(units) + 1)), "every unit once"
        room_n = 0
        for p in P["puts"]:
            un = units[p["unit"] - 1]
            r = self.runs[p["run"]]
            assert (p["w"], p["d"]) == (un["w"], un["d"])
            assert p.get("role") == un.get("role") and p.get("flag") == un.get("flag")
            box = rect_tiles(p["rect"])
            # T takes the bay box onto the rect
            img = {xf(p["T"], bx, by) for bx in range(un["w"]) for by in range(un["d"] + 1)}
            assert img == box, ("T and rect disagree", p)
            assert (0, 0) not in box
            wall = {xf(p["T"], bx, 0) for bx in range(un["w"])}
            room = box - wall
            x0, x1 = un["open"]["x0"], un["open"]["x1"]
            own_hall = r_hall(r)
            for bx in range(x0, x1 + 1):
                assert xf(p["T"], bx, -1) in own_hall, ("an opening not beside its run's hall", p, bx)
            if not p["axial"]:
                e = r_u0(r) + r["len"] - 1
                assert p["u"] + p["w"] - 1 <= e, "a slot past its hall's end"
                assert box == {r_tile(r, u, v * p["side"]) for u in range(p["u"], p["u"] + p["w"])
                               for v in range(2, 3 + p["d"])}, "the rect is not the slot's columns and rows"
            else:
                assert r.get("closed") == "terminus"
            for t in box:
                assert self.state(*t) == "rock", f"slot tile {t} was {self.state(*t)}"
                for b in self.boxes:
                    assert not (b[0] <= t[0] <= b[2] and b[1] <= t[1] <= b[3]), f"slot tile {t} in a box"
            room_n += un["w"] * un["d"] + (x1 - x0 + 1)
            self.puts.append({"p": p, "box": box, "wall": wall, "room": room, "run": p["run"]})
        assert P["tiles"] == P["hall_new"] + room_n
        # slots apart from one another, and from every hall but their own
        near = lambda a, b: any(abs(x - p_) <= 1 and abs(y - q) <= 1 for (x, y) in a for (p_, q) in b)  # noqa: E731
        k = len(P["puts"])
        for i, a in enumerate(self.puts):
            for j in range(max(i + 1, len(self.puts) - k), len(self.puts)):
                b = self.puts[j]
                ax = [t[0] for t in a["box"]]
                bx_ = [t[0] for t in b["box"]]
                ay = [t[1] for t in a["box"]]
                by_ = [t[1] for t in b["box"]]
                apart = (min(ax) > max(bx_) + 1 or min(bx_) > max(ax) + 1
                         or min(ay) > max(by_) + 1 or min(by_) > max(ay) + 1)
                assert apart, ("two slots meet or touch", a["p"], b["p"])
        for a in self.puts:
            r = self.runs[a["run"]]
            own = r_hall(r) | r_core(r)
            for (x, y) in a["box"]:
                assert (x, y) not in after, ("a slot on a hall tile", a["p"])
            for (x, y) in a["room"]:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        assert (x + dx, y + dy) not in after, ("a room touches a hall", a["p"], (x + dx, y + dy))
            for (x, y) in a["wall"]:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (x + dx, y + dy)
                        assert n not in after or n in own, ("a wall row beside another run's hall", a["p"], n)
        del near
        # statues: the corners of a new 5x5 node
        for s in tiles(P["statues"]):
            assert s in after
        if P.get("neck"):
            assert (P["neck"]["x"], P["neck"]["y"]) in after

    def dig(self, world, P, units):
        """The placement dug: hall tiles become the fort's open floor, rooms taken ground."""
        for t in tiles(P["hall"]):
            self.cells[t] = "open"
            H.cell(world, t[0], t[1], "open")
        for p in P["puts"]:
            un = units[p["unit"] - 1]
            for by in range(0, un["d"] + 1):
                for bx in range(un["w"]):
                    if by == 0 and not (un["open"]["x0"] <= bx <= un["open"]["x1"]):
                        continue
                    t = xf(p["T"], bx, by)
                    self.cells[t] = "bad"
                    H.cell(world, t[0], t[1], "bad")


def setcell(world, ck, x, y, v):
    H.cell(world, x, y, v)
    if ck is not None:
        ck.cells[(x, y)] = v


def units_py(req):
    return [py(req.units[i]) for i in range(1, len(req.units) + 1)]


def go(ck, floor, req, G, env, world=None, pid=1):
    """place, check against the rules, commit (and dig, with a world)."""
    P, why, raw = place(floor, req, G, env)
    if P is None:
        return None, why
    us = units_py(req)
    try:
        ck.add(P, us)
    except AssertionError as e:
        raise AssertionError(f"{e}{ck.draw(P)}") from None
    H.commit(floor, raw, pid)
    if world is not None:
        ck.dig(world, P, us)
    return P, None


# ------------------------------------------------------------------ 1. the worked example

@test("the worked example, tile for tile: four bedrooms, then a mason's pile and shop")
def _():
    w, env, floor = fresh()
    G = grammar(**EAST)
    P1, why, raw = place(floor, request(rooms(4)), G, env)
    assert P1 is not None, why
    assert spots(P1) == [(-1, 4), (1, 4), (-1, 8), (1, 8)], spots(P1)
    hall = tiles(P1["hall"])
    assert len(hall) == 38 and hall[:8] == HUB8, hall[:8]
    for i, col in enumerate(range(2, 12)):
        assert set(hall[8 + 3 * i: 11 + 3 * i]) == {(col, -1), (col, 0), (col, 1)}, (col, hall[8 + 3 * i: 11 + 3 * i])
    r = run_of(P1)
    assert (r["id"], r["new"], r["parent"], r["len_before"], r["len"]) == (1, True, 0, 0, 10), r
    assert (r["ox"], r["oy"], r["dx"], r["dy"], r["node"], r["neck"], r["walked"]) == (0, 0, 1, 0, 3, False, 0), r
    assert r["tag"] == "homes" and r.get("closed") is None
    assert P1["req"] == {"kind": "bedrooms", "tag": "homes"}, P1["req"]
    assert P1["new_floor"] is True and P1["floor_id"] == 1
    assert P1["hall_new"] == 38 and P1["tiles"] == 38 + 4 * 10, (P1["hall_new"], P1["tiles"])
    p = P1["puts"][0]
    assert p["rect"] == {"x1": 4, "y1": -5, "x2": 6, "y2": -2}, p["rect"]
    assert p["T"] == {"a": 1, "b": 0, "c": 0, "d": -1, "tx": 4, "ty": -2}, p["T"]
    assert xf(p["T"], 1, 0) == (5, -2), "the first north door"
    assert xf(P1["puts"][1]["T"], 1, 0) == (5, 2) and xf(P1["puts"][3]["T"], 1, 0) == (9, 2)
    assert all(q["axial"] is False and q["role"] == "room" for q in P1["puts"])
    assert P1["hall_rects"] == [{"x": 2, "y": -1, "w": 10, "h": 3}], P1["hall_rects"]
    assert P1["statues"] == [] and P1.get("neck") is None
    H.commit(floor, raw, 41)

    req2 = request([unit(5, 5, "pile", "stone", (1, 3)), unit(5, 5, "shop", None, (1, 3))],
                   kind="workshops", tag="homes", group="crafts", together=True)
    P2, why, raw2 = place(floor, req2, G, env)
    assert P2 is not None, why
    assert spots(P2) == [(-1, 13), (-1, 19)], spots(P2)
    assert [(q["role"], q.get("flag")) for q in P2["puts"]] == [("pile", "stone"), ("shop", None)]
    hall2 = tiles(P2["hall"])
    assert len(hall2) == 39 and set(hall2) == {(x, y) for x in range(12, 25) for y in (-1, 0, 1)}
    assert hall2[0][0] == 12 and hall2[-1][0] == 24, "nearest the stair first"
    r2 = run_of(P2)
    assert (r2["id"], r2["new"], r2["len_before"], r2["len"]) == (1, False, 10, 23), r2
    assert len(P2["runs"]) == 1 and P2["new_floor"] is False
    assert P2["req"] == {"kind": "workshops", "tag": "homes", "group": "crafts"}
    assert P2["puts"][0]["rect"] == {"x1": 13, "y1": -7, "x2": 17, "y2": -2}
    assert P2["puts"][1]["rect"] == {"x1": 19, "y1": -7, "x2": 23, "y2": -2}
    assert {xf(P2["puts"][0]["T"], bx, 0) for bx in (1, 2, 3)} == {(14, -2), (15, -2), (16, -2)}, "the pile's opening"
    assert not (set(hall2) & set(hall)), "nothing of the first project is dug again"


@test("a floor record with no runs and no slots tables at all is a new floor too")
def _():
    w, env, _ = fresh()
    floor = lt({"id": 7, "z": 100, "stair": {"x": 1, "y": 1}})
    P, why, _ = place(floor, request(rooms(2)), grammar(**EAST), env)
    assert P is not None and P["floor_id"] == 7 and P["new_floor"] is True and len(P["hall"]) == 8 + 6 * 3, why


# ------------------------------------------------------------------ 2. Spacing shows

@test("spacing: lead 0, gap 1, kind_gap 0 packs the floor from the stair")
def _():
    w, env, floor = fresh()
    G = grammar(lead=0, gap=1, kind_gap=0, **EAST)
    P1 = placed(floor, request(rooms(4)), G, env)
    assert spots(P1) == [(-1, 2), (1, 2), (-1, 6), (1, 6)], spots(P1)
    assert run_of(P1)["len"] == 8
    P2 = placed(floor, request([unit(5, 5, "pile", "stone"), unit(5, 5, "shop")], kind="workshops", together=True),
                G, env)
    assert spots(P2) == [(-1, 10), (-1, 16)], spots(P2)
    assert run_of(P2)["len"] == 20 and run_of(P2)["len_before"] == 8


@test("spacing: lead 6, gap 3, kind_gap 5 spreads it into blocks along a long hall")
def _():
    w, env, floor = fresh()
    G = grammar(lead=6, gap=3, kind_gap=5, run_max=40, **EAST)
    P1 = placed(floor, request(rooms(4)), G, env)
    assert spots(P1) == [(-1, 8), (1, 8), (-1, 14), (1, 14)], spots(P1)
    assert run_of(P1)["len"] == 16
    P2 = placed(floor, request([unit(5, 5, "pile", "stone"), unit(5, 5, "shop")], kind="workshops", together=True),
                G, env)
    assert spots(P2) == [(-1, 25), (-1, 33)], spots(P2)       # 16 + 1 + gap 3 + kind_gap 5; then 29 + 1 + gap 3
    assert run_of(P2)["len"] == 37


@test("kind_gap: only beside another kind; workshops also beside another group")
def _():
    w, env, floor = fresh()
    G = grammar(sides="one", kind_gap=4, **EAST)
    placed(floor, request(rooms(1)), G, env)                                    # 4..6
    assert spots(placed(floor, request(rooms(1)), G, env)) == [(-1, 8)]         # the same kind: gap only
    P = placed(floor, request([unit(5, 5, "shop")], kind="workshops", group="smith"), G, env)
    assert spots(P) == [(-1, 16)], spots(P)                                     # 10 + 1 + 1 + 4
    P = placed(floor, request([unit(5, 5, "shop")], kind="workshops", group="smith"), G, env)
    assert spots(P) == [(-1, 22)], spots(P)                                     # the same group: gap only
    P = placed(floor, request([unit(5, 5, "shop")], kind="workshops", group="food"), grammar(
        sides="one", kind_gap=4, run_max=60, **EAST), env)
    assert spots(P) == [(-1, 32)], spots(P)                                     # another group: 26 + 1 + 1 + 4


# ------------------------------------------------------------------ 3. survey

@test("survey: rock all round is SURVEY_MAX each way")
def _():
    w, env, floor = fresh()
    assert M.SURVEY_MAX == 60
    assert py(M.survey(floor, grammar(), env)) == {"north": 60, "east": 60, "south": 60, "west": 60}


@test("survey: a box 13 columns east, a bad tile on one of the three rows, open tiles counted as free")
def _():
    w, env, floor = fresh()
    H.box(w, 15, 1, 20, 9)                    # meets the strip's south row only
    H.cell(w, -1, -9, "bad")                  # north: columns 2..8 free
    for y in (-1, 0, 1):
        for x in range(-30, -1):
            H.cell(w, x, y, "open")           # an old corridor west
    H.cell(w, 0, 20, "open")
    H.cell(w, 1, 31, "bad")
    f = py(M.survey(floor, grammar(), env))
    assert f == {"north": 7, "east": 13, "south": 29, "west": 60}, f


@test("survey: stops at the map's usable box")
def _():
    w = H.world()
    env = H.env(w, lt({"bounds": [-20, -5, 9, 40]}))
    f = py(M.survey(H.floor(), grammar(), env))
    assert f == {"north": 4, "east": 8, "south": 39, "west": 19}, f


# ------------------------------------------------------------------ 4. which way a hall starts

@test("direction: the hint's first direction with run_min free (east has 5: south)")
def _():
    w, env, floor = fresh()
    H.cell(w, 7, 0, "bad")
    P = placed(floor, request(rooms(4)), grammar(dirs=["east", "south"], run_min=10), env)
    r = run_of(P)
    assert (r["dx"], r["dy"]) == (0, 1), r
    # a run going south: side -1 is east, +1 west
    assert P["puts"][0]["rect"] == {"x1": 2, "y1": 4, "x2": 5, "y2": 6}, P["puts"][0]["rect"]
    assert P["puts"][1]["rect"] == {"x1": -5, "y1": 4, "x2": -2, "y2": 6}, P["puts"][1]["rect"]
    # with run_min 5 the east stub would do
    P, why, _ = place(H.floor(), request(rooms(1)), grammar(dirs=["east", "south"], run_min=5, ahead=0, lead=0), env)
    assert P is not None and (run_of(P)["dx"], run_of(P)["dy"]) == (1, 0), why


@test("direction: no hint direction free, the longest free of the others")
def _():
    w, env, floor = fresh()
    H.cell(w, 7, 1, "bad")            # east 5
    H.cell(w, -22, 0, "bad")          # west 20
    H.cell(w, 0, 14, "bad")           # south 12
    H.cell(w, 0, -32, "bad")          # north 30
    P = placed(floor, request(rooms(4)), grammar(dirs=["east"]), env)
    assert (run_of(P)["dx"], run_of(P)["dy"]) == (0, -1), run_of(P)
    # the next arm: west (20) before south (12)
    P = placed(floor, request(rooms(10, 3, 3), tag="other"), grammar(dirs=["east"], arms_max=4, grow=["arm"]), env)
    dirs = [(r["dx"], r["dy"]) for r in P["runs"]]
    assert dirs == [(-1, 0), (0, 1)], dirs


@test("direction: nothing free is 'no hall', naming the four runs")
def _():
    w, env, floor = fresh()
    H.cell(w, 5, 0, "bad")            # east 3
    H.cell(w, -9, -1, "bad")          # west 7
    H.box(w, -3, -6, 3, -2)           # north 0
    H.cell(w, 1, 2, "bad")            # south 0
    before = H.dump(floor)
    P, why, _ = place(floor, request(rooms(2)), grammar(), env)
    assert P is None and why == "no hall: north 0, east 3, south 0, west 7", why
    assert H.dump(floor) == before and env.n_probe == 0


@test("a bad tile in the stair's hub: refused")
def _():
    w, env, floor = fresh()
    H.cell(w, -1, 1, "bad")
    P, why, _ = place(floor, request(rooms(2)), grammar(), env)
    assert P is None and why.startswith("refused: the stair's hub"), why
    w, env, floor = fresh()
    H.refuse(w, 1, 1)
    P, why, _ = place(floor, request(rooms(2)), grammar(), env)
    assert P is None and why.startswith("refused: the stair's hub"), why


@test("a hub found open is kept: only its rock tiles are dug")
def _():
    w, env, floor = fresh()
    for t in HUB8[:5]:
        H.cell(w, t[0], t[1], "open")
    P = placed(floor, request(rooms(2)), grammar(**EAST), env)
    assert tiles(P["hall"])[:3] == HUB8[5:], tiles(P["hall"])[:4]
    assert len(P["hall"]) == 3 + 6 * 3


# ------------------------------------------------------------------ 5. the six running forts

FORTS = {}
for _f in "ABCDEF":
    _p = ROOT / "tests" / "fixtures" / "live" / f"{_f}-levels.json"
    if _p.exists():
        FORTS[_f] = json.loads(_p.read_text(encoding="utf-8"))


FORT_NOTES: list[str] = []


def fort_floor(fort, z, every=False):
    """The fake map of one z of a fort: its levels' boxes as blocked ground,
    stair-relative (the standing levels, as the fixture's `free` counts them;
    with `every` the cancelled ones and the zones, piles and shops of
    `other_boxes` too, as its `free_all`). A hub tile inside a box is that
    level's own open floor."""
    sx, sy = fort["stair"]["x"], fort["stair"]["y"]
    w = H.world()
    boxes = []
    for lv in fort["levels"]:
        if lv["z"] == int(z) and (every or lv["state"] != "cancelled"):
            b = lv["bounds"]
            boxes.append((b["x1"] - sx, b["y1"] - sy, b["x2"] - sx, b["y2"] - sy))
    if every:
        for o in fort["other_boxes"]:
            if o["z"] == int(z):
                b = o["box"]
                boxes.append((b[0] - sx, b[1] - sy, b[2] - sx, b[3] - sy))
    for box in boxes:
        H.box(w, *box)
    for (x, y) in HUB8:
        if any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in boxes):
            H.cell(w, x, y, "open")
    return w, boxes


@test("the six forts: survey gives the fixtures' free runs (standing levels; and with every other box)")
def _():
    assert len(FORTS) == 6, "tests/fixtures/live/<A-F>-levels.json"
    n = hits = 0
    for name, fort in FORTS.items():
        for z, hr in fort["hall_runs"].items():
            for every in (False, True):
                w, _ = fort_floor(fort, z, every)
                free = py(M.survey(H.floor(), grammar(), H.env(w)))
                for d, row in hr["dirs"].items():
                    want = row.get("free_all", row["free"]) if every else row["free"]
                    stopped = (row.get("hit_all", row["hit"]) if every else row["hit"]) is not None
                    n += 1
                    if stopped:
                        hits += 1
                        assert free[d] == want, (name, z, d, every, row, free[d])
                    else:
                        # nothing in the way: the fixture looked 59 columns out, survey looks SURVEY_MAX (60)
                        assert want == 59 and free[d] == 60, (name, z, d, every, row, free[d])
    assert n >= 400 and hits >= 150, (n, hits)


@test("the six forts: no free direction is 'no hall'; 10 free columns take four bedrooms clear of every box")
def _():
    halls = nohall = 0
    for name, fort in FORTS.items():
        for z, hr in fort["hall_runs"].items():
            for every in (False, True):
                w, boxes = fort_floor(fort, z, every)
                env = H.env(w)
                floor = H.floor()
                frees = {d: (row.get("free_all", row["free"]) if every else row["free"]) for d, row in hr["dirs"].items()}
                req = request(rooms(4))
                P, why, raw = place(floor, req, grammar(), env)
                if max(frees.values()) < 10:
                    assert P is None and why.startswith("no hall"), (name, z, every, why)
                    for d, f in frees.items():
                        assert f"{d} {f}" in why, (name, z, why)
                    nohall += 1
                    continue
                if P is None:
                    # a stub of hall between standing things: fewer rooms fit, and that is said as 'no room'
                    assert why == "no room", (name, z, every, why)
                    FORT_NOTES.append(f"{name} z{z} every={every}: {max(frees.values())} free")
                    P2, why2, _ = place(floor, request(rooms(2)), grammar(), env)
                    assert P2 is not None, (name, z, every, why2)
                    continue
                halls += 1
                ck = Checker()
                ck.boxes = boxes
                ck.cells = {t: "open" for t in HUB8 if H.get(w.cells, t[0], t[1]) == "open"}
                ck.add(P, units_py(req))
                for p in P["puts"]:
                    for b in boxes:
                        rc = p["rect"]
                        assert rc["x2"] < b[0] or rc["x1"] > b[2] or rc["y2"] < b[1] or rc["y1"] > b[3], (name, z, p, b)
                for (x, y) in tiles(P["hall"]):
                    for b in boxes:
                        assert not (b[0] <= x <= b[2] and b[1] <= y <= b[3]), (name, z, (x, y), b)
                # the hall went a way the fixture calls free
                for r in P["runs"]:
                    d = {(1, 0): "east", (0, 1): "south", (-1, 0): "west", (0, -1): "north"}[(r["dx"], r["dy"])]
                    assert frees[d] >= 10, (name, z, d)
                dug_hub = set(tiles(P["hall"])) & set(HUB8)
                assert dug_hub == {t for t in HUB8 if ck.state(*t) == "rock"}, "a standing level's hub is not dug again"
    # the one level where four rooms do not fit: E z161 with the zones counted has exactly 10 columns east,
    # between a bedrooms level and a workshops level, a meeting hall's zone along its south side: two rooms fit
    assert FORT_NOTES == ["E z161 every=True: 10 free"], FORT_NOTES
    assert halls >= 40 and nohall >= 20, (halls, nohall)


# ------------------------------------------------------------------ 6. run_max reached

def filled(G, n=4, **env_opts):
    """An east run filled to run_max 12 (two rooms a side)."""
    w, env, floor = fresh(**env_opts)
    ck = Checker()
    P, why = go(ck, floor, request(rooms(n)), G, env)
    assert P is not None, why
    return w, env, floor, ck


def turn_grammar(**kw):
    g = dict(run_max=12, grow=["turn"], dirs=["east"])
    g.update(kw)
    return grammar(**g)


@test("run_max reached, grow turn: left is side -1 of the parent, right side +1")
def _():
    for turns, want in (("left", (0, -1)), ("right", (0, 1))):
        G = turn_grammar(turns=turns)
        w, env, floor, ck = filled(G)
        P, why = go(ck, floor, request(rooms(2)), G, env)
        assert P is not None, why
        new = [r for r in P["runs"] if r["new"]]
        old = [r for r in P["runs"] if not r["new"]]
        assert len(new) == 1 and (new[0]["dx"], new[0]["dy"]) == want and new[0]["parent"] == 1, (turns, P["runs"])
        assert new[0]["id"] == 2 and new[0]["tag"] == "homes" and new[0]["node"] == 3
        # the parent is lengthened so the turn's hall clears its last room by a tile of rock
        assert len(old) == 1 and old[0]["len_before"] == 10 and old[0]["len"] == 13, old
        assert (new[0]["ox"], new[0]["oy"]) == (13, 0), new
        assert all(p["run"] == 2 for p in P["puts"])
        # a spiral: the next turn goes the same way
        P, why = go(ck, floor, request(rooms(6)), G, env)
        assert P is not None, why
        third = [r for r in P["runs"] if r["new"]]
        assert third and third[0]["parent"] == 2, P["runs"]
        left = (want[1], -want[0])            # (dx, dy) turned to side -1: -p = (dy, -dx)
        assert (third[0]["dx"], third[0]["dy"]) == (left if turns == "left" else (-want[1], want[0])), third


@test("run_max reached, grow turn: alternate goes left, then right; both forks both ways off one end")
def _():
    G = turn_grammar(turns="alternate")
    w, env, floor, ck = filled(G)
    P, why = go(ck, floor, request(rooms(10)), G, env)
    assert P is not None, why
    new = [r for r in P["runs"] if r["new"]]
    assert [(r["parent"], r["dx"], r["dy"]) for r in new[:2]] == [(1, 0, -1), (2, 1, 0)], new

    G = turn_grammar(turns="both")
    w, env, floor, ck = filled(G)
    P, why = go(ck, floor, request(rooms(10)), G, env)
    assert P is not None, why
    new = [r for r in P["runs"] if r["new"]]
    assert [(r["parent"], r["dx"], r["dy"]) for r in new[:2]] == [(1, 0, -1), (1, 0, 1)], new
    assert (new[0]["ox"], new[0]["oy"]) == (new[1]["ox"], new[1]["oy"]), "both leave the same node"


@test("grow arm stops at arms_max; then the floor has no room")
def _():
    G = grammar(run_max=12, grow=["arm"], arms_max=2, dirs=["east", "west"])
    w, env, floor, ck = filled(G, 8)
    assert sorted(r["parent"] for r in ck.runs.values()) == [0, 0]
    P, why = go(ck, floor, request(rooms(1)), G, env)
    assert P is None and why == "no room", why
    P, why, _ = place(H.floor(), request(rooms(9)), G, env)
    assert P is None and why == "no room", why
    G3 = grammar(run_max=12, grow=["arm"], arms_max=3, dirs=["east", "west"])
    P, why = go(ck, floor, request(rooms(1)), G3, env)
    assert P is not None and run_of(P)["new"] and run_of(P)["parent"] == 0 and len(ck.runs) == 3, why


@test("grow order: arm then turn opens a second arm; turn then arm turns")
def _():
    out = {}
    for grow in (("arm", "turn"), ("turn", "arm")):
        G = grammar(run_max=12, grow=list(grow), dirs=["east"])
        w, env, floor, ck = filled(G)
        P, why = go(ck, floor, request(rooms(1)), G, env)
        assert P is not None, why
        out[grow] = [r["parent"] for r in P["runs"] if r["new"]]
    assert out == {("arm", "turn"): [0], ("turn", "arm"): [1]}, out


@test("a turn needs run_min free columns: left is shut, so 'left' has no room and 'alternate' goes right")
def _():
    def world():
        w, env, floor, ck = filled(turn_grammar(), 4)
        for x in range(8, 30):
            setcell(w, ck, x, -10, "bad")            # north of the hall: 8 free columns for a turn (run_min 10)
        return w, env, floor, ck
    w, env, floor, ck = world()
    P, why = go(ck, floor, request(rooms(2)), turn_grammar(turns="left"), env)
    assert P is None and why == "no room", why
    P, why = go(ck, floor, request(rooms(1)), turn_grammar(turns="left", run_min=6), env)
    assert P is not None and [(r["dx"], r["dy"]) for r in P["runs"] if r["new"]] == [(0, -1)], why
    w, env, floor, ck = world()
    P, why = go(ck, floor, request(rooms(2)), turn_grammar(turns="alternate"), env)
    assert P is not None and [(r["dx"], r["dy"]) for r in P["runs"] if r["new"]] == [(0, 1)], why


# ------------------------------------------------------------------ 7. obstacles

@test("a bad tile in the hall's way: slots before it, the rest on another arm")
def _():
    w, env, floor = fresh()
    ck = Checker()
    setcell(w, ck, 9, 0, "bad")
    # east has 7 free columns: with run_min 7 the hall starts there
    G = grammar(dirs=["east"], run_min=7)
    P, why = go(ck, floor, request(rooms(3)), G, env)
    assert P is not None, why
    east = [p for p in P["puts"] if p["run"] == 1]
    assert [(p["side"], p["u"]) for p in east] == [(-1, 4), (1, 4)], spots(P)
    assert ck.runs[1]["len"] == 6 and len(P["runs"]) == 2 and ck.runs[2]["parent"] == 0


@test("a bad tile in the hall's way: the floor turns")
def _():
    w, env, floor = fresh()
    ck = Checker()
    setcell(w, ck, 9, 0, "bad")
    G = grammar(dirs=["east"], run_min=7, sides="one", grow=["turn"], turns="right")
    P, why = go(ck, floor, request(rooms(3)), G, env)
    assert P is not None, why
    assert [(p["run"], p["side"], p["u"]) for p in P["puts"]][:1] == [(1, -1, 4)]
    new = [r for r in P["runs"] if r["new"] and r["parent"] == 1]
    assert len(new) == 1 and (new[0]["dx"], new[0]["dy"]) == (0, 1) and (new[0]["ox"], new[0]["oy"]) == (6, 0), new
    assert ck.runs[1]["len"] == 6


@test("open tiles in the hall's way are kept: not in hall, counted in len; leading ones are walked")
def _():
    w, env, floor = fresh()
    ck = Checker()
    for x in (5, 6):
        for y in (-1, 0, 1):
            setcell(w, ck, x, y, "open")
    P, why = go(ck, floor, request(rooms(4)), grammar(**EAST), env)
    assert P is not None, why
    assert spots(P) == [(-1, 4), (1, 4), (-1, 8), (1, 8)]
    hall = set(tiles(P["hall"]))
    assert len(hall) == 38 - 6 and not any(x in (5, 6) for (x, y) in hall)
    assert run_of(P)["len"] == 10 and run_of(P)["walked"] == 0

    w, env, floor = fresh()
    ck = Checker()
    for x in range(2, 9):
        for y in (-1, 0, 1):
            setcell(w, ck, x, y, "open")              # an old 3-wide corridor, 7 long
    P, why = go(ck, floor, request(rooms(2)), grammar(**EAST), env)
    assert P is not None, why
    assert run_of(P)["walked"] == 6 and run_of(P)["len"] == 6 and len(P["hall"]) == 8, (run_of(P), len(P["hall"]))
    assert spots(P) == [(-1, 4), (1, 4)]


@test("a room never touches the fort's open floor: the slot moves along")
def _():
    w, env, floor = fresh()
    ck = Checker()
    setcell(w, ck, 7, -4, "open")          # just east of where the first north room would stand
    P, why = go(ck, floor, request(rooms(2)), grammar(**EAST), env)
    assert P is not None, why
    assert spots(P) == [(-1, 9), (1, 4)], spots(P)
    assert env.n_probe == 3, "the cheap check, not the probe, found it (the hub, the hall, the rooms)"


@test("a refusing probe moves on, inside G.tries")
def _():
    w, env, floor = fresh()
    ck = Checker()
    H.refuse(w, 5, -4)
    P, why = go(ck, floor, request(rooms(4)), grammar(**EAST), env)
    assert P is not None, why
    assert spots(P) == [(-1, 6), (1, 4), (-1, 10), (1, 8)], spots(P)
    assert env.n_probe <= 24, env.n_probe
    assert all((5, -4) not in rect_tiles(p["rect"]) or xf(p["T"], 1, 0) != (5, -2) for p in P["puts"])


@test("a probe that refuses a hall tile: the hall stops before it and the floor goes another way")
def _():
    w, env, floor = fresh()
    ck = Checker()
    H.refuse(w, 9, 1)
    P, why = go(ck, floor, request(rooms(4)), grammar(dirs=["east"], run_min=4), env)
    assert P is not None, why
    assert ck.runs[1]["len"] == 6 and len(ck.runs) == 2, ck.runs
    assert (9, 1) not in set(tiles(P["hall"])) and env.n_probe <= 24
    # and when every way is refused: 'refused', with the map's word
    w, env, floor = fresh()
    for (x, y) in ((3, 0), (-3, 0), (0, 3), (0, -3)):
        H.refuse(w, x, y)
    P, why, _ = place(floor, request(rooms(2)), grammar(arms_max=4), env)
    assert P is None and why.startswith("refused") and "damp stone" in why, why


@test("env.blocked: slots and hall keep off another project's box")
def _():
    w, env, floor = fresh()
    ck = Checker()
    ck.boxes = [(3, -6, 7, -3)]
    H.box(w, 3, -6, 7, -3)
    P, why = go(ck, floor, request(rooms(2)), grammar(**EAST), env)
    assert P is not None, why
    assert spots(P) == [(-1, 9), (1, 4)], spots(P)
    assert env.n_probe == 3


@test("env.bounds: nothing outside the map's usable box")
def _():
    w = H.world()
    env = H.env(w, lt({"bounds": [-40, -40, 12, 40]}))
    floor = H.floor()
    ck = Checker()
    G = grammar(dirs=["east"], run_min=6)
    P, why = go(ck, floor, request(rooms(6)), G, env)
    assert P is not None, why
    for t in tiles(P["hall"]):
        assert t[0] <= 12
    for p in P["puts"]:
        assert p["rect"]["x2"] <= 12
    assert ck.runs[1]["len"] == 10 and len(ck.runs) == 2
    env = H.env(w, lt({"bounds": [-40, -4, 40, 40]}))
    P, why, _ = place(H.floor(), request(rooms(2)), grammar(**EAST), env)
    assert P is not None and spots(P) == [(1, 4), (1, 8)], (why, P and spots(P))


@test("env.late() and G.tries: 'out of time', nothing kept")
def _():
    w = H.world()
    floor = H.floor()
    P, why, _ = place(floor, request(rooms(4)), grammar(**EAST), H.env(w, lt({"late_after": 0})))
    assert P is None and why == "out of time", why
    P, why, _ = place(floor, request(rooms(4)), grammar(**EAST), H.env(w, lt({"late_after": 3})))
    assert P is None and why == "out of time", why
    H.refuse(w, 5, -4)
    env = H.env(w)
    P, why, _ = place(floor, request(rooms(4)), grammar(tries=4, **EAST), env)
    assert P is None and why == "out of time" and env.n_probe == 4, (why, env.n_probe)
    env = H.env(w)
    P, why, _ = place(floor, request(rooms(4)), grammar(tries=24, **EAST), env)
    assert P is not None and env.n_probe <= 24
    assert H.dump(floor) == H.dump(H.floor())


@test("an easy request costs three probes on a new floor, two after, however many rooms; none for a full floor")
def _():
    w, env, floor = fresh()
    P = placed(floor, request(rooms(12)), grammar(**EAST), env)
    assert [(e["role"], e["n"]) for e in py(env.log)] == [("hall", 8), ("hall", 78), ("room", 120)], py(env.log)
    env = H.env(w)
    P = placed(floor, request(rooms(12), tag="x"), grammar(dirs=["east", "west"]), env)
    assert [e["role"] for e in py(env.log)] == ["hall", "room"], py(env.log)
    # a full floor: no probe at all
    G = grammar(run_max=12, grow=[], arms_max=1, dirs=["east"])
    w, env, floor = fresh()
    placed(floor, request(rooms(4)), G, env)
    n = env.n_probe
    P, why, _ = place(floor, request(rooms(1)), G, env)
    assert P is None and why == "no room" and env.n_probe == n, (why, env.n_probe)


@test("a full floor is 'no room'; a together row too long for any run is 'no room', a loose one spreads over runs")
def _():
    G = grammar(run_max=12, dirs=["east"], arms_max=2, grow=["arm", "turn"])
    w, env, floor = fresh()
    row = [unit(5, 5, "pile", "stone"), unit(5, 5, "shop"), unit(5, 5, "shop")]
    P, why, _ = place(floor, request(row, kind="workshops", together=True), G, env)
    assert P is None and why == "no room", why
    ck = Checker()
    P, why = go(ck, floor, request(row, kind="workshops"), G, env)
    assert P is not None and len({p["run"] for p in P["puts"]}) >= 1 and len(P["puts"]) == 3, why
    P, why = go(ck, floor, request(rooms(30)), G, env)
    assert P is not None and len({p["run"] for p in P["puts"]}) >= 3, why


@test("the record's limits: 160 slots and 24 runs a floor")
def _():
    w, env, floor = fresh()
    for i in range(158):
        floor.slots[i + 1] = lt({"run": 99, "side": -1, "u": 4, "w": 3, "d": 3})
    P, why, _ = place(floor, request(rooms(3)), grammar(), env)
    assert P is None and why == "floor record full", why
    P, why, _ = place(floor, request(rooms(2)), grammar(), env)
    assert P is not None, why


# ------------------------------------------------------------------ 8. zone, group, tag

def long_run(length=20, tag="homes"):
    w, env, floor = fresh()
    floor.hub = "dug"
    floor.runs[1] = lt({"id": 1, "parent": 0, "ox": 0, "oy": 0, "dx": 1, "dy": 0, "len": length, "walked": 0,
                        "tag": tag, "node": 3, "neck": False})
    return w, env, floor


def slot(run, side, u, w=3, d=3, kind="bedrooms", tag="homes", **kw):
    s = {"run": run, "side": side, "u": u, "w": w, "d": d, "pid": 1, "kind": kind, "tag": tag, "role": "room"}
    s.update(kw)
    return lt(s)


@test("zone: near starts at the lead, far at the hall's present end, mid a third of run_max along")
def _():
    for zone, want, length in (("near", 4, 20), ("any", 4, 20), ("far", 21, 23), ("mid", 12, 20)):
        w, env, floor = long_run()
        P, why, _ = place(floor, request(rooms(1), zone=zone), grammar(), env)
        assert P is not None and spots(P) == [(-1, want)], (zone, why, P and spots(P))
        assert run_of(P)["len"] == length if P["runs"] else length == 20, (zone, P["runs"])
        assert not any(t in HUB8 for t in tiles(P["hall"])), "a standing floor's hub is not dug again"
    # no room past the preferred start: the zone is a wish, the run is still used
    w, env, floor = long_run(29)
    P, why, _ = place(floor, request(rooms(1), zone="far"), grammar(), env)
    assert P is not None and spots(P) == [(-1, 4)], why


@test("zone: near takes the run nearest the stair, far the farthest; balance the shortest")
def _():
    def two():
        w, env, floor = long_run(12)
        floor.runs[2] = lt({"id": 2, "parent": 1, "ox": 12, "oy": 0, "dx": 0, "dy": 1, "len": 8, "walked": 0,
                            "tag": "homes", "node": 3, "neck": False})
        return w, env, floor
    got = {}
    for zone in ("near", "far", "any"):
        w, env, floor = two()
        P, why, _ = place(floor, request(rooms(1), zone=zone), grammar(), env)
        assert P is not None, why
        got[zone] = P["puts"][0]["run"]
    assert got == {"near": 1, "far": 2, "any": 1}, got
    w, env, floor = two()
    P, why, _ = place(floor, request(rooms(1), zone="near"), grammar(balance=True), env)
    assert P is not None and P["puts"][0]["run"] == 2, why


@test("a group goes right after its group's last slot, on that slot's run and side")
def _():
    def world():
        w, env, floor = long_run(24)
        floor.slots[1] = slot(1, -1, 4, 5, 5, "workshops", group="smith")
        floor.slots[2] = slot(1, -1, 20, 3, 3, "bedrooms")
        floor.slots[3] = slot(1, 1, 4, 5, 5, "workshops", group="food")
        return w, env, floor
    w, env, floor = world()
    one = [unit(5, 5, "shop")]
    P, why, _ = place(floor, request(one, kind="workshops", group="smith"), grammar(), env)
    assert P is not None and spots(P) == [(-1, 10)], (why, P and spots(P))
    # without the group: the side with fewer slots, kind_gap beside the other group
    w, env, floor = world()
    P, why, _ = place(floor, request(one, kind="workshops", group="cloth"), grammar(), env)
    assert P is not None and spots(P) == [(1, 11)], (why, P and spots(P))
    # the group's run before a nearer one
    w, env, floor = long_run(12)
    floor.runs[2] = lt({"id": 2, "parent": 1, "ox": 12, "oy": 0, "dx": 0, "dy": 1, "len": 12, "walked": 0,
                        "tag": "homes", "node": 3, "neck": False})
    floor.slots[1] = slot(2, -1, 4, 5, 5, "workshops", group="smith")
    P, why, _ = place(floor, request(one, kind="workshops", group="smith", zone="near"), grammar(), env)
    assert P is not None and [(p["run"], p["side"], p["u"]) for p in P["puts"]] == [(2, -1, 10)], (why, P)
    P, why, _ = place(floor, request(one, kind="workshops", group="food", zone="near"), grammar(), env)
    assert P is not None and P["puts"][0]["run"] == 1, why


@test("a tag fills its own runs first, then grows, then shares another tag's run")
def _():
    w, env, floor = long_run(10, "homes")
    ck = Checker()
    ck.runs[1] = py(floor.runs[1])
    ck.listed = r_hall(ck.runs[1]) | set(HUB8)
    G = grammar(dirs=["east", "south"])
    P, why = go(ck, floor, request(rooms(2), tag="industry"), G, env)
    assert P is not None, why
    assert [(r["new"], r["parent"], r["tag"], (r["dx"], r["dy"])) for r in P["runs"]] == [(True, 0, "industry", (0, 1))]
    # its own run first
    P, why = go(ck, floor, request(rooms(2), tag="industry"), G, env)
    assert P is not None and {p["run"] for p in P["puts"]} == {2} and not any(r["new"] for r in P["runs"]), why
    P, why = go(ck, floor, request(rooms(2), tag="homes"), G, env)
    assert P is not None and {p["run"] for p in P["puts"]} == {1}, why
    # no growth left: a third tag shares the oldest run
    G0 = grammar(dirs=["east", "south"], grow=[])
    P, why = go(ck, floor, request(rooms(2), tag="faith"), G0, env)
    assert P is not None and {p["run"] for p in P["puts"]} == {1} and not any(r["new"] for r in P["runs"]), why
    assert ck.runs[1]["tag"] == "homes"
    # with growth: a turning run off any run when the tag has none
    G1 = grammar(dirs=["east", "south"], grow=["turn"], run_max=12)
    P, why = go(ck, floor, request(rooms(8), tag="trade"), G1, env)
    assert P is not None, why
    new = [r for r in P["runs"] if r["new"]]
    assert new and new[0]["parent"] in (1, 2) and new[0]["tag"] == "trade", new


# ------------------------------------------------------------------ 9. sides, stagger, bay

@test("sides: both takes the side with fewer slots, one only side -1, alternate the side the last slot is not on")
def _():
    def world():
        w, env, floor = long_run(12)
        floor.slots[1] = slot(1, -1, 4)
        floor.slots[2] = slot(1, -1, 8)
        return w, env, floor
    w, env, floor = world()
    assert spots(place(floor, request(rooms(3)), grammar(sides="both"), env)[0]) == [(1, 4), (1, 8), (-1, 12)]
    w, env, floor = world()
    assert spots(place(floor, request(rooms(3)), grammar(sides="alternate"), env)[0]) == [(1, 4), (-1, 12), (1, 8)]
    w, env, floor = world()
    assert spots(place(floor, request(rooms(3)), grammar(sides="one"), env)[0]) == [(-1, 12), (-1, 16), (-1, 20)]
    w, env, floor = fresh()
    assert spots(place(floor, request(rooms(4)), grammar(sides="alternate", **EAST), env)[0]) == \
        [(-1, 4), (1, 4), (-1, 8), (1, 8)]


@test("stagger shifts side +1's first slot; the mirror comes from the seed, and never with facing rooms")
def _():
    w, env, floor = fresh()
    P, why, _ = place(floor, request(rooms(4)), grammar(stagger=2, **EAST), env)
    assert spots(P) == [(-1, 4), (1, 6), (-1, 8), (1, 10)], spots(P)
    mir = [p["mirror"] for p in P["puts"]]
    assert mir == [True, False, True, False], mir
    p = P["puts"][0]
    assert p["T"] == {"a": -1, "b": 0, "c": 0, "d": -1, "tx": 6, "ty": -2}, p["T"]       # x = u + w - 1 - bx
    env2 = H.env(w, lt({"seed": 1}))
    P2, _, _ = place(floor, request(rooms(4)), grammar(stagger=2, **EAST), env2)
    assert [p["mirror"] for p in P2["puts"]] == [False, True, False, True]
    assert P2["puts"][0]["T"] == {"a": 1, "b": 0, "c": 0, "d": -1, "tx": 4, "ty": -2}
    for seed in (0, 1, 7):
        P3, _, _ = place(floor, request(rooms(4)), grammar(stagger=0, sides="both", **EAST), H.env(w, lt({"seed": seed})))
        assert not any(p["mirror"] for p in P3["puts"])
    P4, _, _ = place(floor, request(rooms(4)), grammar(stagger=0, sides="one", **EAST), env)
    assert any(p["mirror"] for p in P4["puts"])


@test("bay: one more rock column after every `bay` slots on a side")
def _():
    w, env, floor = fresh()
    P, why, _ = place(floor, request(rooms(8)), grammar(bay=3, sides="one", run_max=60, **EAST), env)
    assert [u for _, u in spots(P)] == [4, 8, 12, 17, 21, 25, 30, 34], spots(P)
    P, why, _ = place(floor, request(rooms(8)), grammar(bay=3, run_max=60, **EAST), env)
    assert spots(P) == [(-1, 4), (1, 4), (-1, 8), (1, 8), (-1, 12), (1, 12), (-1, 17), (1, 17)], spots(P)
    # inside a together row too
    row = [unit(3, 3) for _ in range(4)]
    P, why, _ = place(floor, request(row, together=True), grammar(bay=3, run_max=60, **EAST), env)
    assert [u for _, u in spots(P)] == [4, 8, 12, 17], spots(P)


# ------------------------------------------------------------------ 10. axial, node, neck, min_u, dead slots

@test("axial: a hall unit closes the end of the tag's longest run; nothing is placed past it")
def _():
    w, env, floor = long_run(16)
    ck = Checker()
    ck.runs[1] = py(floor.runs[1])
    ck.listed = r_hall(ck.runs[1]) | set(HUB8)
    hall = [unit(9, 6, "hall", None, (3, 5))]
    G = grammar(axial=True, arms_max=1, grow=[])
    req = request(hall, kind="dining", axial=True)
    P, why = go(ck, floor, req, G, env)
    assert P is not None, why
    p = P["puts"][0]
    assert p["axial"] is True and p["side"] == 0 and p["u"] == 18 and p["run"] == 1, p
    assert p["rect"] == {"x1": 18, "y1": -4, "x2": 24, "y2": 4}, p["rect"]
    assert p["T"] == {"a": 0, "b": 1, "c": 1, "d": 0, "tx": 18, "ty": -4}, p["T"]
    assert [xf(p["T"], bx, 0) for bx in (3, 4, 5)] == [(18, -1), (18, 0), (18, 1)], "the opening centred on v = 0"
    assert P["hall"] == [] and P["runs"] == [{"id": 1, "new": False, "parent": 0, "ox": 0, "oy": 0, "dx": 1, "dy": 0,
                                              "len_before": 16, "len": 16, "walked": 0, "tag": "homes", "node": 3,
                                              "neck": False, "closed": "terminus"}], P["runs"]
    # the run is closed: with no growth, nothing more goes on this floor for the tag
    P, why = go(ck, floor, request(rooms(1)), G, env)
    assert P is None and why == "no room", why
    # with an arm to grow, the next level goes elsewhere, clear of the closing hall
    P, why = go(ck, floor, request(rooms(4)), grammar(arms_max=2), env)
    assert P is not None and run_of(P)["new"] and all(q["run"] == 2 for q in P["puts"]), why


@test("axial: only when asked by both, for one hall unit, on a run at least half of run_max, with no child")
def _():
    hall = [unit(9, 6, "hall", None, (3, 5))]
    for name, length, G, req in (
            ("the grammar says no", 16, grammar(axial=False), request(hall, kind="dining", axial=True)),
            ("the request says no", 16, grammar(axial=True), request(hall, kind="dining")),
            ("the run is short", 14, grammar(axial=True), request(hall, kind="dining", axial=True)),
            ("two units", 16, grammar(axial=True), request(hall + hall, kind="dining", axial=True)),
            ("a room, not a hall", 16, grammar(axial=True), request([unit(9, 6, "room", None, (3, 5))], axial=True))):
        w, env, floor = long_run(length)
        P, why, _ = place(floor, req, G, env)
        assert P is not None and not any(p["axial"] for p in P["puts"]), (name, why)
        assert all(r.get("closed") is None for r in P["runs"]), name
    # something in the way at the end: an ordinary slot instead
    w, env, floor = long_run(16)
    H.cell(w, 22, 3, "open")
    P, why, _ = place(floor, request(hall, kind="dining", axial=True), grammar(axial=True), env)
    assert P is not None and P["puts"][0]["axial"] is False, why
    # a refusing probe: the same
    w, env, floor = long_run(16)
    H.refuse(w, 22, 3)
    P, why, _ = place(floor, request(hall, kind="dining", axial=True), grammar(axial=True), env)
    assert P is not None and P["puts"][0]["axial"] is False, why


@test("node 5: a turning run leaves through a 5x5 square, statues on its corners, its hall from u = 3")
def _():
    G = turn_grammar(turns="right", node=5)
    w, env, floor, ck = filled(G)
    P, why = go(ck, floor, request(rooms(2)), G, env)
    assert P is not None, why
    new = [r for r in P["runs"] if r["new"]][0]
    assert new["node"] == 5 and new["parent"] == 1 and (new["dx"], new["dy"]) == (0, 1), new
    ox, oy = new["ox"], new["oy"]
    assert sorted(tiles(P["statues"])) == sorted([(ox - 2, oy - 2), (ox + 2, oy - 2), (ox - 2, oy + 2), (ox + 2, oy + 2)])
    hall = set(tiles(P["hall"]))
    assert {(ox + a, oy + b) for a in (-2, 2) for b in (-2, -1, 0, 1, 2)} <= hall | ck.listed
    assert (ox, oy + 2) in hall and (ox, oy + 3) in hall
    assert {"x": ox - 2, "y": oy - 2, "w": 5, "h": 5} in P["hall_rects"]
    assert all(p["u"] >= 5 for p in P["puts"]), spots(P)        # u0 3 + lead 2
    # the hub's own node is never 5x5
    w, env, floor = fresh()
    P, why, _ = place(floor, request(rooms(2)), grammar(node=5, **EAST), env)
    assert run_of(P)["node"] == 3 and P["statues"] == [] and len(P["hall"]) == 8 + 18


@test("neck: a new hub run starts 1 wide with a door tile; the 3-wide hall and the slots start a column on")
def _():
    w, env, floor = fresh()
    ck = Checker()
    G = grammar(neck=True, **EAST)
    P, why = go(ck, floor, request(rooms(2)), G, env)
    assert P is not None, why
    assert P["neck"] == {"x": 2, "y": 0} and run_of(P)["neck"] is True
    hall = set(tiles(P["hall"]))
    assert (2, 0) in hall and (2, -1) not in hall and (2, 1) not in hall
    assert spots(P) == [(-1, 5), (1, 5)] and run_of(P)["len"] == 7 and len(hall) == 8 + 1 + 6 * 3
    assert P["hall_rects"] == [{"x": 3, "y": -1, "w": 6, "h": 3}], P["hall_rects"]
    # lengthening it later: no second neck
    P, why = go(ck, floor, request(rooms(2)), G, env)
    assert P is not None and P.get("neck") is None and spots(P) == [(-1, 9), (1, 9)], why
    # a column that is already open takes no neck
    w, env, floor = fresh()
    H.cell(w, 2, 1, "open")
    P, why, _ = place(floor, request(rooms(2)), G, env)
    assert P is not None and P.get("neck") is None and run_of(P)["neck"] is False and spots(P) == [(-1, 4), (1, 4)]


@test("min_u: no slot nearer the stair than that many tiles")
def _():
    w, env, floor = fresh()
    P, why, _ = place(floor, request([unit(7, 9, "hall")], kind="hospital", min_u=7), grammar(**EAST), env)
    assert P is not None and spots(P) == [(-1, 7)], spots(P)
    P, why, _ = place(floor, request([unit(7, 9, "hall")], kind="hospital"), grammar(**EAST), env)
    assert spots(P) == [(-1, 4)]
    # on a run going north too: its tiles are 7 from the stair
    P, why, _ = place(floor, request([unit(7, 9, "hall")], kind="hospital", min_u=7), grammar(dirs=["north"]), env)
    r = P["puts"][0]["rect"]
    assert max(abs(r["y2"]), 0) >= 7 and r["y2"] == -7, r


@test("dead slots are as solid as live ones")
def _():
    w, env, floor = long_run(12)
    floor.slots[1] = slot(1, -1, 4, dead=True)
    P, why, _ = place(floor, request(rooms(3)), grammar(), env)
    assert spots(P) == [(1, 4), (-1, 8), (1, 8)], spots(P)


@test("a slot never stands on, or against, another run's hall or slots (hand-made floor)")
def _():
    # a north arm beside the east run: the east run's north rooms keep a tile of rock from it
    w, env, floor = long_run(12)
    floor.runs[2] = lt({"id": 2, "parent": 0, "ox": 0, "oy": 0, "dx": 0, "dy": -1, "len": 12, "walked": 0,
                        "tag": "other", "node": 3, "neck": False})
    floor.slots[1] = slot(2, 1, 6, 3, 3, tag="other")          # east side of the north arm: x 2..5, y -8..-6
    P, why, _ = place(floor, request(rooms(2), ), grammar(lead=0, sides="one"), env)
    assert P is not None, why
    # lead 0 would be u = 2 (x 2..4, y -5..-2): it touches the north arm's hall at x = 1; and the arm's room above
    assert spots(P)[0] == (-1, 7), spots(P)


@test("a floor whose first project was cancelled (its run rolled back to nothing): the hub and hall are dug by the next")
def _():
    w, env, floor = fresh()
    G = grammar(neck=True, **EAST)
    P = placed(floor, request(rooms(2)), G, env)
    floor.runs[1].len = 0                      # ai-floorplan.release: len back to len_before, the slots dead
    for i in (1, 2):
        floor.slots[i].dead = True
    ck = Checker()
    ck.runs[1] = py(floor.runs[1])
    for q in P["puts"]:
        ck.puts.append({"p": q, "box": rect_tiles(q["rect"]), "wall": set(), "room": rect_tiles(q["rect"]), "run": 1})
    req = request(rooms(2))
    P2, why, raw = place(floor, req, G, env)
    assert P2 is not None, why
    assert spots(P2) == [(-1, 9), (1, 9)], spots(P2)                 # past the dead slots
    hall = tiles(P2["hall"])
    assert hall[:8] == HUB8 and (2, 0) in hall and (2, -1) not in hall, hall[:10]
    r = run_of(P2)
    assert (r["id"], r["new"], r["len_before"], r["len"], r["neck"]) == (1, False, 0, 11, True), r
    assert P2["neck"] == {"x": 2, "y": 0} and P2["new_floor"] is False
    # once a hall stands, the hub is not looked at again
    H.commit(floor, raw, 2)
    H.cell(w, 1, 1, "bad")
    P3, why, _ = place(floor, request(rooms(2)), G, env)
    assert P3 is not None and not (set(tiles(P3["hall"])) & set(HUB8)), why


# ------------------------------------------------------------------ 11. nothing is changed

@test("place changes nothing it was given, on success and on failure; the same inputs give the same answer")
def _():
    w, env, floor = fresh()
    G = grammar(run_max=12, node=5, neck=True, stagger=2, bay=3, dirs=["east", "north"])
    placed(floor, request(rooms(4)), G, env)
    cases = [request(rooms(7), group="g", zone="far", min_u=3),
             request([unit(5, 5, "pile", "stone", (1, 3)), unit(5, 5, "shop", None, (1, 3))], kind="workshops",
                     together=True, group="crafts"),
             request([unit(9, 6, "hall", None, (3, 5))], kind="dining", axial=True),
             request(rooms(200)),                                    # floor record full
             request([unit(40, 5)], together=True)]                  # no room
    seen = set()
    for req in cases:
        f0, r0, g0 = H.dump(floor), H.dump(req), H.dump(G)
        res1 = M.place(floor, req, G, env)
        assert (H.dump(floor), H.dump(req), H.dump(G)) == (f0, r0, g0), "place wrote into its arguments"
        res2 = M.place(floor, req, G, env)
        a = res1 if isinstance(res1, tuple) else (res1, None)
        b = res2 if isinstance(res2, tuple) else (res2, None)
        assert (a[0] is None) == (b[0] is None) and a[1] == b[1]
        if a[0] is not None:
            assert H.dump(a[0]) == H.dump(b[0]), "two answers to one question"
        seen.add("ok" if a[0] is not None else a[1].split(":")[0])
    assert seen == {"ok", "floor record full", "no room"}, seen
    # survey too
    f0 = H.dump(floor)
    M.survey(floor, G, env)
    assert H.dump(floor) == f0


@test("a bad request is refused, not an error")
def _():
    w, env, floor = fresh()
    for req in (lt({"kind": "x", "tag": "t", "units": []}), lt({"kind": "x", "tag": "t"}),
                lt({"kind": "x", "tag": "t", "units": [{"w": 0, "d": 3}]}),
                lt({"kind": "x", "tag": "t", "units": [{"w": 3}]})):
        P, why, _ = place(floor, req, grammar(), env)
        assert P is None and why.startswith("bad request"), why
    # a unit with no opening given: its middle column
    P, why, _ = place(floor, lt({"kind": "x", "tag": "t", "units": [{"w": 5, "d": 2}]}), grammar(**EAST), env)
    assert P is not None and P["tiles"] == P["hall_new"] + 11, why


# ------------------------------------------------------------------ 12. the property test

def random_grammar(rng):
    return dict(
        gap=rng.choice([1, 1, 2, 3]), kind_gap=rng.choice([0, 1, 1, 3, 5]), lead=rng.choice([0, 2, 2, 4, 6]),
        ahead=rng.choice([0, 1, 1, 2, 3]), run_max=rng.choice([12, 16, 20, 30, 40]),
        run_min=rng.choice([4, 6, 10, 10, 14]), arms_max=rng.choice([1, 2, 2, 3, 4]),
        dirs=rng.sample(["east", "south", "west", "north"], rng.randint(0, 3)),
        sides=rng.choice(["both", "both", "one", "alternate"]), stagger=rng.choice([0, 0, 2, 3]),
        bay=rng.choice([0, 0, 3, 4, 6]), node=rng.choice([3, 3, 5]),
        grow=rng.choice([["arm", "turn"], ["turn", "arm"], ["turn"], ["arm"]]),
        turns=rng.choice(["left", "right", "alternate", "both"]), balance=rng.random() < 0.25,
        axial=rng.random() < 0.4, neck=rng.random() < 0.3, tries=rng.choice([8, 24, 24, 60]))


def random_request(rng):
    kind = rng.choice(["bedrooms", "bedrooms", "storage", "workshops", "dining", "hospital", "jail"])
    tag = rng.choice(["homes", "homes", "industry", "faith"])
    kw = {"zone": rng.choice(["near", "mid", "far", "any"])}
    if kind == "workshops":
        us = [unit(rng.choice([5, 7]), rng.choice([5, 7]), "pile", "stone", (1, 3)) for _ in range(rng.randint(0, 2))]
        us += [unit(5, 5, "shop", None, (1, 3)) for _ in range(rng.randint(1, 3))]
        kw["together"] = rng.random() < 0.8
        kw["group"] = rng.choice(["smith", "food", "crafts"])
    elif kind in ("dining", "hospital"):
        wd = rng.choice([5, 7, 9, 11])
        c = wd // 2
        us = [unit(wd, rng.randint(4, 12), "hall", None, (c - 1, c + 1) if kind == "dining" else (c, c))]
        kw["axial"] = rng.random() < 0.6
        if kind == "hospital":
            kw["min_u"] = 7
    else:
        s = rng.choice([2, 3, 3, 4, 5])
        us = [unit(s, rng.choice([s, s, s + 2]), "room", None, (rng.randint(0, s - 1),) * 2)
              for _ in range(rng.randint(1, 10))]
    return kind, tag, us, kw


def random_world(rng, ck):
    w = H.world()
    r = rng.random()
    n_bad = 0 if r < 0.3 else rng.randint(1, 5)
    for _ in range(n_bad):
        x0, y0 = rng.randint(-45, 45), rng.randint(-45, 45)
        if abs(x0) <= 3 and abs(y0) <= 3:
            continue
        for x in range(x0, x0 + rng.randint(1, 6)):
            for y in range(y0, y0 + rng.randint(1, 6)):
                if abs(x) > 1 or abs(y) > 1:
                    setcell(w, ck, x, y, "bad")
    for _ in range(rng.randint(0, 3)):                 # old corridors and halls
        x0, y0 = rng.randint(-40, 40), rng.randint(-40, 40)
        horiz = rng.random() < 0.5
        ln, wd = rng.randint(3, 20), rng.choice([1, 2, 3, 3])
        for a in range(ln):
            for b in range(wd):
                x, y = (x0 + a, y0 + b) if horiz else (x0 + b, y0 + a)
                if (x, y) != (0, 0):
                    setcell(w, ck, x, y, "open")
    if rng.random() < 0.3:                             # an old 3-wide corridor from the hub
        dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        for u in range(2, rng.randint(4, 16)):
            for v in (-1, 0, 1):
                setcell(w, ck, u * dx - v * dy, u * dy + v * dx, "open")
    if rng.random() < 0.3:
        for t in HUB8:
            if rng.random() < 0.7:
                setcell(w, ck, t[0], t[1], "open")
    for _ in range(rng.randint(0, 4)):                 # standing levels
        x0, y0 = rng.randint(-40, 30), rng.randint(-40, 30)
        box = (x0, y0, x0 + rng.randint(3, 14), y0 + rng.randint(3, 14))
        if box[0] <= 1 and box[2] >= -1 and box[1] <= 1 and box[3] >= -1:
            continue
        H.box(w, *box)
        ck.boxes.append(box)
    for _ in range(rng.randint(0, 6)):                 # damp stone and the like: only the probe knows
        H.refuse(w, rng.randint(-25, 25), rng.randint(-25, 25))
    return w


@test("property: a few hundred random requests on random maps keep every rule")
def _():
    rng = random.Random(20261115)
    placed_n = refused_n = floors = 0
    whys: dict[str, int] = {}
    turned = armed = axial = necks = nodes5 = 0
    for trial in range(70):
        ck = Checker()
        w = random_world(rng, ck)
        bounds = [-rng.randint(20, 60), -rng.randint(20, 60), rng.randint(20, 60), rng.randint(20, 60)]
        floor = H.floor(trial + 1)
        gd = random_grammar(rng)
        floors += 1
        for step in range(rng.randint(3, 9)):
            if rng.random() < 0.15:
                gd = random_grammar(rng)
            G = lt(gd)
            kind, tag, us, kw = random_request(rng)
            req = request(us, kind=kind, tag=tag, **kw)
            env = H.env(w, lt({"bounds": bounds, "seed": trial * 31 + step, "strict": True}))
            f0 = H.dump(floor)
            try:
                P, why = go(ck, floor, req, G, env, world=w, pid=step + 1)
            except AssertionError as e:
                raise AssertionError(f"trial {trial} step {step} {kind} {kw} G={gd}: {e}") from None
            assert env.n_probe <= gd["tries"], (env.n_probe, gd["tries"])
            if P is None:
                refused_n += 1
                assert H.dump(floor) == f0, "a failed place left something behind"
                key = why.split(":")[0].split(" (")[0]
                assert key in ("no hall", "no room", "refused", "out of time", "floor record full"), why
                whys[key] = whys.get(key, 0) + 1
                continue
            placed_n += 1
            for t in tiles(P["hall"]):
                assert bounds[0] <= t[0] <= bounds[2] and bounds[1] <= t[1] <= bounds[3]
            for p in P["puts"]:
                rc = p["rect"]
                assert bounds[0] <= rc["x1"] and rc["x2"] <= bounds[2] and bounds[1] <= rc["y1"] and rc["y2"] <= bounds[3]
                axial += p["axial"]
            for r in P["runs"]:
                if r["new"]:
                    turned += r["parent"] != 0
                    armed += r["parent"] == 0
                    nodes5 += r["node"] == 5
            necks += 1 if P.get("neck") else 0
            if kw.get("together"):
                assert len({(p["run"], p["side"]) for p in P["puts"]}) == 1, "a together row on one side of one run"
                us_ = sorted(P["puts"], key=lambda p: p["unit"])
                assert all(a["u"] < b["u"] for a, b in zip(us_, us_[1:])), "a together row in order"
            if kw.get("min_u"):
                for p in P["puts"]:
                    rc = p["rect"]
                    nx = max(rc["x1"], -rc["x2"], 0)
                    ny = max(rc["y1"], -rc["y2"], 0)
                    assert max(nx, ny) >= kw["min_u"], p
    assert placed_n >= 200 and refused_n >= 20, (placed_n, refused_n, whys)
    assert turned >= 10 and armed >= 60 and axial >= 3 and necks >= 5 and nodes5 >= 3, \
        (turned, armed, axial, necks, nodes5)
    assert whys.get("no room", 0) >= 5, whys
    if "--show" in sys.argv:
        print(f"property: placed {placed_n}, refused {refused_n} {whys}; turns {turned}, arms {armed}, "
              f"axial {axial}, necks {necks}, 5x5 nodes {nodes5}")


# ------------------------------------------------------------------ 13. speed

@test("speed: place on a floor of 150 slots and 20 runs, 100 times, well under a second")
def _():
    w, env, floor = fresh()
    cfg = dict(run_max=12, lead=1, ahead=0, arms_max=4, grow=["arm", "turn"], turns="alternate", tries=60)
    G = grammar(**cfg)
    while len(floor.slots) < 150 or len(floor.runs) < 20:
        P, why, raw = place(floor, request(rooms(1, 2, 2)), G, env)
        assert P is not None, (why, len(floor.slots), len(floor.runs))
        H.commit(floor, raw, 1)
    assert 150 <= len(floor.slots) <= 156 and 20 <= len(floor.runs) <= 24, (len(floor.slots), len(floor.runs))
    req = request(rooms(4, 2, 2))
    env = H.env(w)
    # the process's own time: the other test files run beside this one
    t0 = time.process_time()
    ok = H.many(M, floor, req, G, env, 100)
    dt = time.process_time() - t0
    assert ok == 100, ok
    print(f"    (100 places took {dt:.2f}s of CPU; not asserted: no clock bounds in the tests)")
    # and a request the full floor refuses (every run looked at, nothing grown)
    cfg["grow"] = []
    t0 = time.process_time()
    ok = H.many(M, floor, request([unit(9, 9)], zone="far"), grammar(**cfg), env, 100)
    dt2 = time.process_time() - t0
    assert ok == 0
    print(f"    (100 refused places took {dt2:.2f}s of CPU)")


# ------------------------------------------------------------------ 14. the module itself

@test("the module compiles under Lua 5.3, is a pure module and leaks no global")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    assert lua.eval("_VERSION") == "Lua 5.3"
    before = lua.eval("(function() local n = 0; for _ in pairs(_G) do n = n + 1 end; return n end)()")
    mod = lua.eval("function(src) local env = setmetatable({}, {__index=_G}); "
                   "assert(load(src, 'ai-floorplace', 't', env))(); return env end")(SRC)
    assert sorted(mod.keys()) == ["SURVEY_MAX", "place", "survey"], sorted(mod.keys())
    # run it once, every path's worth, and look again
    run = lua.eval("""function(M)
      local env = {probe = function() return true end, blocked = function() return false end,
                   open = function() return 'rock' end, late = function() return false end, seed = 3}
      local G = {gap=1, kind_gap=1, lead=2, ahead=1, run_max=12, run_min=10, arms_max=2, dirs={'east'}, sides='both',
                 stagger=2, bay=3, node=5, grow={'turn','arm'}, turns='both', balance=true, axial=true, neck=true, tries=24}
      local floor = {id = 1}
      local us = {}
      for i = 1, 14 do us[i] = {w = 3, d = 3, role = 'room', open = {x0 = 1, x1 = 1}} end
      local P = assert(M.place(floor, {kind = 'bedrooms', tag = 'homes', zone = 'far', group = 'g', units = us}, G, env))
      M.survey(floor, G, env)
      return #P.runs
    end""")
    assert run(mod) >= 2
    after = lua.eval("(function() local n = 0; for _ in pairs(_G) do n = n + 1 end; return n end)()")
    assert after == before, "a global leaked into _G"
    assert sorted(mod.keys()) == ["SURVEY_MAX", "place", "survey"], "a global leaked into the module"
    assert "--@ module = true" in SRC
    code = "\n".join(line.split("--")[0] for line in SRC.splitlines())
    for word in ("dfhack", "reqscript", "df.", "require", "os.", "io."):
        assert word not in code, f"{word} in a pure module"


@test("the bridge lists the module")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    a = src.index("'ai-welfare',   -- (0.105.47, I7b)")
    b = src.index("'ai-floorplace',   -- (layout B) where halls and rooms go on a floor")
    c = src.index("'ai-well-safety',")
    assert a < b < c


if __name__ == "__main__":
    finish()
