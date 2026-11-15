"""(0.105.54, layout option A part 1) Smaller, plainer levels and wider
connectors: the player saw "pillars" (a ring workshop level: one shop in a
17x17 loop) and connectors leaving from the back of rooms.

  1. lua/ai-layouts.lua ring_rooms: no ring under RING_MIN_ROOMS rooms (the
     corridor layout instead); the loop sized from the room count, rooms
     spread one a side first.
  2. lua/ai-builder-sites.lua plan_grammar: an avenue of 2 without a plan's
     avenue (3 when the style is spread out or large); offset_sites' walk
     through the fort stops at the AI's rooms (room_tiles).
  3. workshops: square rooms opening 3 wide; rounded corners only on a big
     level with a hall style.

    python tests/test_k54_layout_a.py            run the tests
    python tests/test_k54_layout_a.py --show     also draw the workshop levels
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, have_lua, make_test, need_lua  # noqa: E402

SHOPS = ["Still", "Kitchen", "Masons", "Carpenters", "Craftsdwarfs", "Loom", "Smelter", "Tanners", "Bowyers"]
RING_STYLE = {"arms": "ring", "hall": "rounded"}      # the B/D/F presets: Monastery, Hermit hold, Garden fort

if have_lua():
    import d0_layout_snapshot as snap  # noqa: E402
    import test_builder as TB          # noqa: E402  (its fake fort; its own tests don't run here)
    LUA, M, SER = snap.lua_runtime()
    FLAT = LUA.eval(r"""function(L)
      local out = {tiles = {}, build = {}, place = {}}
      for x, col in pairs(L.tiles) do for y in pairs(col) do table.insert(out.tiles, {x, y}) end end
      for _, phase in ipairs({'build', 'place'}) do
        for _, c in ipairs(L[phase]) do table.insert(out[phase], {c.x, c.y, c.text}) end
      end
      out.ring = L.corridor and L.corridor.ring or false
      return out
    end""")
    test = make_test()
    btest = TB.test
else:
    def test(name):
        def wrap(fn):
            return make_test()(name)(lambda: need_lua())
        return wrap
    btest = lambda name, beside=False: test(name)  # noqa: E731


def make(kind, params, style=None):
    p = dict(params)
    if style is not None:
        p["style"] = style
    res = M.make(kind, snap.to_lua(LUA, p))
    L = res[0] if isinstance(res, tuple) else res
    assert L is not None, res
    return L


def flat(L):
    f = FLAT(L)
    return {"tiles": {(int(t[1]), int(t[2])) for t in f.tiles.values()},
            "build": [(int(c[1]), int(c[2]), c[3]) for c in f.build.values()],
            "place": [(int(c[1]), int(c[2]), c[3]) for c in f.place.values()],
            "ring": f.ring}


def shops(n, style=None):
    return flat(make("workshops", {"shops": SHOPS[:n]}, style))


def span(f):
    xs = [x for x, _ in f["tiles"]]
    ys = [y for _, y in f["tiles"]]
    return max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


@test("ring: workshop levels never ring (0.105.54 merge: rooms along a corridor at any count); other levels ring only from 4 rooms")
def _():
    for n in (1, 2, 3, 4, 8, 9):
        ring = make("workshops", {"shops": SHOPS[:n]}, {"arms": "ring"})
        plain = make("workshops", {"shops": SHOPS[:n]}, {})
        assert SER(ring) == SER(plain), n                     # byte-identical to the plain style
        assert not flat(ring)["ring"], n
    # the old shape: one shop in a 15x15 loop plus its alcove, ~250 tiles
    one = shops(1, RING_STYLE)
    assert len(one["tiles"]) <= 100 and max(span(one)) <= 17, (len(one["tiles"]), span(one))
    # bedrooms on a ring stay a ring (a home with many rooms)
    assert flat(make("bedrooms", {"rooms": 16, "room_size": 3}, {"arms": "ring"}))["ring"]


@test("workshops: square 5x5 rooms opening 3 wide onto the corridor; rounded only on a big level with a hall style")
def _():
    def corners_dug(f):
        out = []
        for x, y, t in f["build"]:
            out.append(all((x + dx, y + dy) in f["tiles"] for dx in (-2, 2) for dy in (-2, 2)))
        return out
    for n in (1, 2, 3):
        for style in ({}, RING_STYLE, {"hall": "rounded"}, {"hall": "pillared"}, {"hall": "round"}):
            f = shops(n, style)
            assert len(f["build"]) == n and all(corners_dug(f)), (n, style)
    for n in (4, 8):
        assert not any(corners_dug(shops(n, {"hall": "rounded"}))), n       # the hall style asks, a big level
        assert all(corners_dug(shops(n, {}))), n                              # plain: square
    # each room opens 3 wide: the row between the room and the corridor has the
    # three middle tiles dug and its two outer tiles rock
    for n, style in ((1, {}), (3, {"hall": "rounded"}), (4, RING_STYLE), (8, RING_STYLE), (8, {"arms": "cross"})):
        f = shops(n, style)
        for x, y, t in f["build"]:
            opened = 0
            for dx, dy in ((0, 3), (0, -3), (3, 0), (-3, 0)):
                ox, oy = x + dx, y + dy
                across = [(ox + k, oy) for k in (-2, -1, 0, 1, 2)] if dx == 0 else [(ox, oy + k) for k in (-2, -1, 0, 1, 2)]
                dug = [c in f["tiles"] for c in across]
                if dug == [False, True, True, True, False]:
                    opened += 1
            assert opened >= 1, (n, style, (x, y))


@test("grammar: no plan or no avenue -> an avenue of 2; 3 when spread out or large; a plan's own 1 kept")
def _():
    B = TB.B

    def lay(style):
        res = TB.LUA.globals().LAYOUTS.make("bedrooms", TB.LUA.table_from({"rooms": 4, "room_size": 3,
                                                                            "style": TB.LUA.table_from(style)}))
        return res[0] if isinstance(res, tuple) else res
    plain = lay({})
    assert B.plan_grammar(None, plain).avenue == 2
    assert B.plan_grammar(TB.LUA.table_from({"elev_lo": 1, "elev_hi": 2}), plain).avenue == 2   # a hint, no avenue
    assert B.plan_grammar(None, None).avenue == 2
    assert B.plan_grammar(None, lay({"spacing": 60})).avenue == 3
    assert B.plan_grammar(None, lay({"scale": 140})).avenue == 3
    assert B.plan_grammar(None, lay({"spacing": 40, "scale": 120})).avenue == 2
    assert B.plan_grammar(TB.LUA.table_from({"avenue": 3}), plain).avenue == 3
    assert B.plan_grammar(TB.LUA.table_from({"avenue": 1}), plain) is None        # winding ways: 1 wide


@btest("connector: a level beside the stairs without any plan gets a corridor 2 wide", beside=True)
def _():
    r = TB.start(kind="bedrooms", rooms=4, room_size=3)
    assert r.ok and r.z == 72, r.error
    corr = TB.corridor_tiles()
    xs = {x for x, _ in corr}
    ys = {y for _, y in corr}
    assert len(xs) == 2 or len(ys) == 2, sorted(corr)          # 2 wide (its doorways 1 wide)


ROOMS_SET = r"""function(list)
  local s = {}
  for _, p in ipairs(list) do s[p[1]] = s[p[1]] or {}; s[p[1]][p[2]] = true end
  return s
end"""


@btest("offset_sites: the walk through the fort stops at a room; the new corridor never leaves through it", beside=True)
def _():
    B, W, LUA = TB.B, TB.W, TB.LUA
    res = LUA.globals().LAYOUTS.make("bedrooms", LUA.table_from({"rooms": 4, "room_size": 3}))
    L = res[0] if isinstance(res, tuple) else res
    stair = LUA.table_from({"x": 60, "y": 60, "z_top": 80, "z_bottom": 60})
    south = LUA.table_from([LUA.table_from({"x": 0, "y": 1})])
    try_ = LUA.eval("function(ok, why, s) if ok then return s end end")
    # the fort's open floor runs to y 65 south of the stair on z 72
    site = B.offset_sites(L, stair, 72, LUA.table(), try_, south, None)
    assert site and site.corridor - site.new_corridor == 5, (site and site.corridor, site and site.new_corridor)
    # a room (a workshop's alcove) across y 63..65: the walk stops at y 62 and the
    # corridor would leave through the room: refused that way
    rooms = LUA.eval(ROOMS_SET)(LUA.table_from([LUA.table_from([x, y]) for x in range(58, 63) for y in range(63, 66)]))
    B.CACHE = LUA.table()
    assert B.offset_sites(L, stair, 72, LUA.table(), try_, south, None, rooms) is None
    # a room off the walk's line changes nothing
    beside = LUA.eval(ROOMS_SET)(LUA.table_from([LUA.table_from([x, y]) for x in range(64, 69) for y in range(61, 66)]))
    again = B.offset_sites(L, stair, 72, LUA.table(), try_, south, None, beside)
    assert again and (again.anchor.x, again.anchor.y) == (site.anchor.x, site.anchor.y)


@btest("room_tiles: the rooms of the AI's levels on a z, from their saved cells (workshops, bedrooms, piles)", beside=True)
def _():
    B, W, LUA = TB.B, TB.W, TB.LUA
    r = TB.start(kind="workshops", shops=["Still", "Kitchen"])
    assert r.ok, r.error
    p = W.persist["ai-overseer/projects"].list[1]
    ax, ay, z = p.anchor.x, p.anchor.y, p.z
    tiles = B.room_tiles(z)
    got = {(x, y) for x, col in tiles.items() for y in col.keys()}
    shops_at = [(ax + c.x, ay + c.y) for c in p.cells.build.values() if c.text in ("wl", "wz")]
    assert len(shops_at) == 2
    want = {(x + dx, y + dy) for x, y in shops_at for dx in range(-2, 3) for dy in range(-2, 3)}
    assert got == want, sorted(got ^ want)
    assert not ((ax, ay) in got or (ax + 1, ay) in got)                   # the hub and corridor are not rooms
    assert len(B.room_tiles(z + 1)) == 0                                   # other levels: none
    data = LUA.eval("""function() return {list = {
      {kind = 'bedrooms', z = 5, anchor = {x = 10, y = 10}, cells = {zone = {{x = 3, y = -4, text = 'b(3x3)'}}}},
      {kind = 'storage', z = 5, anchor = {x = 10, y = 10}, cells = {place = {{x = -9, y = 2, text = 'f(5x5)'}}}},
      {kind = 'dining', z = 5, anchor = {x = 40, y = 40}, cells = {zone = {{x = 2, y = -5, text = 'h(20x11)'}}}},
      {kind = 'bedrooms', z = 6, anchor = {x = 10, y = 10}, cells = {zone = {{x = 3, y = -4, text = 'b(3x3)'}}}},
    }} end""")()
    t = B.room_tiles(5, data)
    got = {(x, y) for x, col in t.items() for y in col.keys()}
    assert got == ({(13 + dx, 6 + dy) for dx in range(3) for dy in range(3)}
                   | {(1 + dx, 12 + dy) for dx in range(5) for dy in range(5)}), sorted(got)


def draw(f) -> str:
    xs = [x for x, _ in f["tiles"]] + [0]
    ys = [y for _, y in f["tiles"]] + [0]
    marks = {(x, y): "W" for x, y, _ in f["build"]}
    return "\n".join("".join("X" if (x, y) == (0, 0) else marks.get((x, y), "." if (x, y) in f["tiles"] else "#")
                             for x in range(min(xs) - 1, max(xs) + 2)) for y in range(min(ys) - 1, max(ys) + 2))


if __name__ == "__main__":
    if "--show" in sys.argv and have_lua():
        for n in (1, 2, 4, 8):
            for style in ({}, RING_STYLE):
                f = shops(n, style)
                print(f"\n{n} workshops {style or 'plain'}: {len(f['tiles'])} tiles, {span(f)}\n" + draw(f))
    finish()
