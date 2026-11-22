"""(0.105.54, layout option A part 2) Workshops grouped onto shared levels.

Fort B (R3 live run, region4-1430): 20 of 25 workshop levels held one shop,
each ~250 dug tiles, ~18 tiles apart; its projects 71 and 72 were two
single-Millstone levels on one z (states/255-autumn.json, their styles kept
here as fixtures). Now every start_project of kind workshops goes into a
standing AI workshops level first (a free room, else the level extended),
and a new level is planned for several shops (lua/ai-builder-projects.lua
join_workshop_level, workshop_spares; lua/ai-layouts.lua workshops spare;
brain/planner_shopslots.py shop_level_action), on test_builder's fake fort
in a real Lua engine.

    python tests/test_k54_shop_levels.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import finish, have_lua, make_test, skip  # noqa: E402
from lua_modules_util import bridge_part_src  # noqa: E402  (r6) the bridge parts split

import planner_shopslots as PS  # noqa: E402

LUA = B = W = TB = None
if have_lua():
    import test_builder as TB  # noqa: E402  (its fake fort; its tests run only when it is run itself)
    LUA, B, W = TB.LUA, TB.B, TB.W


def _reset():
    if TB is not None:
        TB._reset(False)


test = make_test(before=_reset)
plain_test = make_test()

# fort B's project 71 and 72 (both shops: ['Millstone']), registry style as reported
STYLE_B71 = {"arms": "ring", "aspect": "long", "entry_door": False, "grand": True, "hall": "nave",
             "motif": "star", "orient": 3, "rhythm": 3, "scale": 136, "smooth": 3, "spacing": 0, "statues": 3}
STYLE_B72 = dict(STYLE_B71, rhythm=4)
# fort B's project 1, a corridor-free ring too; a plain corridor level for the corridor arms
STYLE_CORRIDOR = {"hall": "plain", "smooth": 0, "statues": 0}


def need():
    if TB is None:
        skip("needs the lupa package (pip install lupa)")


def tbl(v):
    if isinstance(v, dict):
        return LUA.table_from({k: tbl(x) for k, x in v.items()})
    if isinstance(v, list):
        return LUA.table_from([tbl(x) for x in v])
    return v


def start(dry=False, **kw):
    return B.start_project(tbl(dict(kw)), LUA.table_from({"year": 255, "tick": 100}), dry)


def dig_all():
    for t in W.tiles.values():
        if t.designated:
            t.shape, t.designated = "FLOOR", False


def projects():
    d = W.persist["ai-overseer/projects"]
    return [d.list[i] for i in range(1, len(d.list) + 1)]


def project(pid):
    return next(p for p in projects() if p.id == pid)


def lua_list(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def set_phase(pid, phase):
    project(pid).phase = phase


def builds(p):
    return [(c.x, c.y, c.text) for c in lua_list(p.cells.build)]


# --- B's duplicate Millstone levels --------------------------------------------------

@test("B's second single-Millstone level (projects 71/72): the standing level is extended, not a new one (0.105.54 merge: one shop is a 72-tile corridor level now, not a 250-tile ring)")
def _():
    need()
    r1 = start(kind="workshops", shops=["Millstone"], spare=0, style=STYLE_B71)     # as B's old level was planned
    assert r1.ok and r1.project_id == 1 and r1.tiles >= 60, dict(r1)
    dig_all()
    set_phase(1, "done")
    r2 = start(kind="workshops", shops=["Millstone"], spare=0, style=STYLE_B72)    # (B's 72: the rule's style)
    assert r2.ok and r2.joined == 1 and r2.how == "extension", dict(r2)
    assert r2.tiles < r1.tiles, (r2.tiles, r1.tiles)
    p2, p1 = project(2), project(1)
    assert p2.parent == 1 and p2.kind == "workshops" and p2.phase == "dig" and p2.z == p1.z, dict(p2)
    assert (p2.anchor.x, p2.anchor.y) == (p1.anchor.x, p1.anchor.y)
    assert [b[2] for b in builds(p2)] == ["wM"], builds(p2)
    # the level knows its new room is taken, and the new tiles are its own now
    assert len(list(p1.taken.values())) == 1 and len(lua_list(p1.ext_tiles)) == r2.tiles
    # the annex goes through the ordinary lifecycle: dug -> furnish
    dig_all()
    o = [x for x in lua_list(B.projects_report().open) if x.id == 2][0]
    assert o.dig.dug == o.dig.total == r2.tiles and o.next == "furnish", (dict(o.dig), o.next)


@test("an extension with no word from the brain adds WORKSHOP_EXTEND_SPARE empty rooms too; the next shop takes one, no digging")
def _():
    need()
    r1 = start(kind="workshops", shops=["Millstone"], spare=0, style=STYLE_B71)
    dig_all()
    set_phase(1, "done")
    r2 = start(kind="workshops", shops=["Millstone"], style=STYLE_B71)
    assert r2.ok and r2.how == "extension" and r2.tiles < 100 and r2.tiles * 2 < r1.tiles, dict(r2)
    p1 = project(1)
    # (0.105.54 merge) as many spares as fit without moving a dug room
    assert 1 <= p1.params.spare <= 1 + int(B.WORKSHOP_EXTEND_SPARE) and p1.free_left == p1.params.spare - 1
    dig_all()
    set_phase(2, "done")
    r3 = start(kind="workshops", shops=["Quern"], style=STYLE_B71)
    # (0.105.54 merge) a free room when the extension could hold spares, else
    # another small extension of the same level: never a new level
    assert r3.ok and r3.joined == 1 and (r3.how == "free_room" and r3.tiles == 0
                                         or r3.how == "extension" and r3.tiles < 40), dict(r3)


@test("join = false (the old way, every shop its own level): B's second Millstone digs a whole new level")
def _():
    need()
    assert start(kind="workshops", shops=["Millstone"], spare=0, style=STYLE_B71).ok
    dig_all()
    set_phase(1, "done")
    r = start(kind="workshops", shops=["Millstone"], spare=0, style=STYLE_B72, join=False)
    assert r.ok and r.joined is None and r.project_id == 2 and r.tiles >= 60, dict(r)


@test("8 shops on one level (a corridor now, never a ring): a 9th extends it along its corridor")
def _():
    need()
    r1 = start(kind="workshops", shops=["Kitchen", "Still", "Butchers", "Tanners", "Farmers", "Fishery",
                                         "Quern", "Millstone"], spare=0, style=STYLE_B71)
    assert r1.ok, dict(r1)
    dig_all()
    set_phase(1, "done")
    r2 = start(kind="workshops", shops=["Still"], spare=0, style=STYLE_B71)
    assert r2.ok and r2.joined == 1 and r2.how == "extension", (dict(r2), r2.not_joined)


@test("a corridor level grows along its corridor: the new rooms and the corridor's next stretch only")
def _():
    need()
    r1 = start(kind="workshops", shops=["Kitchen", "Still", "Butchers", "Tanners"], spare=0, style=STYLE_CORRIDOR)
    assert r1.ok, dict(r1)
    dig_all()
    set_phase(1, "done")
    r2 = start(kind="workshops", shops=["Farmers"], spare=0, style=STYLE_CORRIDOR)
    assert r2.ok and r2.joined == 1 and r2.how == "extension", dict(r2)
    old = B.layouts.tiles_from_dig(project(1).cells.dig)
    new = [(c.x, c.y) for c in lua_list(project(2).cells.dig)]
    assert new and not any(old[x] is not None and old[x][y] for x, y in new), "an extension re-digs nothing"
    assert r2.tiles < 80 and r2.tiles * 2 < r1.tiles, (r2.tiles, r1.tiles)


# --- new levels: planned for several shops -------------------------------------------

@test("a new level is planned for several shops: 4 rooms for one shop, the spares planned for its industry-mates")
def _():
    need()
    r = start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR)
    assert r.ok and r.joined is None, dict(r)
    p = project(1)
    assert p.params.spare == 3 and lua_list(p.params.spare_for) == ["MetalsmithsForge", "WoodFurnace", "Kiln"]
    assert p.summary.free_rooms == 3 and p.free_left == 3 and builds(p)[0][2] == "es", dict(p.summary)
    # the free rooms' middles are left unsmoothed (a workshop goes there later)
    L = B.layouts.make("workshops", tbl({"shops": ["Smelter"], "spare": 3, "style": {"smooth": 3}}))
    free = [(c.x, c.y) for c in lua_list(L.rooms_at) if str(c.text).startswith("free")]
    assert len(free) == 3
    r2 = start(kind="workshops", shops=["Kitchen"], spare=3, style={"smooth": 3, "hall": "plain"}, join=False)
    assert r2.ok
    sm = {(c.x, c.y) for c in lua_list(project(2).cells.smooth)}
    assert sm and not any((x + dx, y + dy) in sm for x, y in free for dx in (-1, 0, 1) for dy in (-1, 0, 1)), \
        "free middles smoothed"


@test("the next shop goes into its planned free room, no digging; still digging: the level's own furnishing places it")
def _():
    need()
    assert start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR).ok
    n_before = sum(1 for t in W.tiles.values() if t.designated)
    r = start(kind="workshops", shops=["MetalsmithsForge"], style=STYLE_CORRIDOR)
    assert r.ok and r.joined == 1 and r.how == "free_room" and r.project_id == 1, dict(r)
    assert sum(1 for t in W.tiles.values() if t.designated) == n_before          # nothing dug
    p = project(1)
    L = B.layouts.make("workshops", tbl({"shops": ["Smelter"], "spare": 3,
                                         "spare_for": ["MetalsmithsForge", "WoodFurnace", "Kiln"], "style": STYLE_CORRIDOR}))
    planned = [(c.x, c.y) for c in lua_list(L.rooms_at) if c.text == "free:MetalsmithsForge"][0]
    assert (planned[0], planned[1], "wf") in builds(p), builds(p)
    assert lua_list(p.summary.workshops) == ["Smelter", "MetalsmithsForge"] and p.furniture.MetalsmithsForge == 1
    assert p.free_left == 2 and len(projects()) == 1


@test("a finished level's free room: a small annex project (already dug), furnished next")
def _():
    need()
    assert start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR).ok
    dig_all()
    set_phase(1, "done")
    r = start(kind="workshops", shops=["WoodFurnace"], style=STYLE_CORRIDOR)
    assert r.ok and r.joined == 1 and r.how == "free_room" and r.project_id == 2 and r.tiles == 0, dict(r)
    p2 = project(2)
    assert p2.parent == 1 and builds(p2)[0][2] == "ew", builds(p2)
    o = [x for x in lua_list(B.projects_report().open) if x.id == 2][0]
    assert o.dig.total == 9 and o.dig.dug == 9 and o.next == "furnish", (dict(o.dig), o.next)
    # its area holds only its own room (its furnishing counts its own workshop)
    a = p2.area
    assert a.x2 - a.x1 == 6 and a.y2 - a.y1 == 6, dict(a)
    # a room someone built in is not used
    assert project(1).free_left == 2


@test("grouped by industry: a Still goes to the food level's free room, not the smithing level's")
def _():
    need()
    assert start(kind="workshops", shops=["Kitchen"], style=STYLE_CORRIDOR).ok
    dig_all()
    set_phase(1, "done")
    assert start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR, join=False).ok
    dig_all()
    set_phase(2, "done")
    r = start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR)
    assert r.ok and r.joined == 1, dict(r)          # the older level, but the food one
    r = start(kind="workshops", shops=["Kiln"], style=STYLE_CORRIDOR)
    assert r.ok and r.joined == 2, dict(r)


@test("another industry's free room before a new level; a room built in by someone else is skipped")
def _():
    need()
    assert start(kind="workshops", shops=["Kitchen"], spare=1, spare_for=[], style=STYLE_CORRIDOR).ok
    dig_all()
    set_phase(1, "done")
    L = B.layouts.make("workshops", tbl({"shops": ["Kitchen"], "spare": 1, "style": STYLE_CORRIDOR}))
    free = [(c.x, c.y) for c in lua_list(L.rooms_at) if str(c.text).startswith("free")][0]
    a = project(1).anchor
    W.set(a.x + free[0], a.y + free[1], project(1).z, LUA.table_from({"building": True}))
    r = start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR, dry=True)
    assert r.ok and r.joined == 1 and r.how == "extension", dict(r)     # the free room is taken: extended
    W.set(a.x + free[0], a.y + free[1], project(1).z, LUA.table_from({"building": False}))
    r = start(kind="workshops", shops=["Smelter"], style=STYLE_CORRIDOR, dry=True)
    assert r.ok and r.joined == 1 and r.how == "free_room" and r.dry_run, dict(r)
    assert len(projects()) == 1                                       # a dry run records nothing


@test("a stone user (Masons) takes the free room nearest the level's ore pile")
def _():
    need()
    style = dict(STYLE_CORRIDOR, customs=["ore_piles"])
    assert start(kind="workshops", shops=["Craftsdwarfs"], spare=4, spare_for=[], style=style).ok
    L = B.layouts.make("workshops", tbl({"shops": ["Craftsdwarfs"], "spare": 4, "style": style}))
    rooms = lua_list(L.rooms_at)
    pile = [(c.x, c.y) for c in rooms if c.text == "pile"][0]
    free = [(c.x, c.y) for c in rooms if str(c.text).startswith("free")]
    near = min(free, key=lambda f: abs(f[0] - pile[0]) + abs(f[1] - pile[1]))
    r = start(kind="workshops", shops=["Masons"], style=style)
    assert r.ok and r.how == "free_room", dict(r)
    got = [b for b in builds(project(1)) if b[2] == "wm"][0]
    assert (got[0], got[1]) == near, (got, near, free)


@test("join = false, join = 'band' outside the band, and the Deep mine's ceiling keep a new level")
def _():
    need()
    assert start(kind="workshops", shops=["Kitchen"], style=STYLE_CORRIDOR).ok
    dig_all()
    set_phase(1, "done")
    z = project(1).z
    r = start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR, dry=True, join=False)
    assert r.ok and r.joined is None, dict(r)
    off = B.elevation_offset()
    band = {"elev_lo": z + off - 10, "elev_hi": z + off - 5}
    r = start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR, dry=True, join="band", plan=band)
    assert r.ok and r.joined is None, dict(r)
    band = {"elev_lo": z + off - 1, "elev_hi": z + off + 1}
    r = start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR, dry=True, join="band", plan=band)
    assert r.ok and r.joined == 1, dict(r)
    r = start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR, dry=True, max_elev=z + off - 1)
    assert r.joined is None, dict(r)


@test("a finished level with free rooms stays on the list past KEEP_CLOSED_PROJECTS (others are dropped)")
def _():
    need()
    assert start(kind="workshops", shops=["Kitchen"], style=STYLE_CORRIDOR).ok
    set_phase(1, "done")
    d = W.persist["ai-overseer/projects"]
    for i in range(2, 2 + int(B.KEEP_CLOSED_PROJECTS) + 3):
        d.list[len(d.list) + 1] = LUA.table_from({"id": i, "kind": "bedrooms", "phase": "done",
                                                  "area": LUA.table_from({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "z": 1})})
    B.save_projects(d)
    ids = [p.id for p in projects()]
    assert 1 in ids and 2 not in ids and len(ids) == int(B.KEEP_CLOSED_PROJECTS) + 1, ids
    project(1).free_left = 0
    B.save_projects(W.persist["ai-overseer/projects"])
    assert 1 not in [p.id for p in projects()]


@test("the registry marks an annex with the level it joins")
def _():
    need()
    assert start(kind="workshops", shops=["Kitchen"], style=STYLE_CORRIDOR).ok
    dig_all()
    set_phase(1, "done")
    assert start(kind="workshops", shops=["Still"], style=STYLE_CORRIDOR).project_id == 2
    reg = lua_list(B.registry_report())
    assert reg[0].joins is None and reg[1].joins == 1


# --- the layout ------------------------------------------------------------------------

@plain_test("layout: spare rooms come after the shops and the ore pile; without spare the layout is as before")
def _():
    need()
    mk = lambda **kw: B.layouts.make("workshops", tbl(kw))      # noqa: E731
    a = mk(shops=["Still"], style={"customs": ["ore_piles"]})
    b = mk(shops=["Still"], style={"customs": ["ore_piles"]}, spare=2, spare_for=["Kitchen"])
    assert [str(c.text) for c in lua_list(a.rooms_at)] == ["shop:Still", "pile"]
    assert [str(c.text) for c in lua_list(b.rooms_at)] == ["shop:Still", "pile", "free:Kitchen", "free"]
    assert a.summary.free_rooms is None and b.summary.free_rooms == 2
    ta = {(x, y) for x in a.tiles for y in a.tiles[x]}
    tb = {(x, y) for x in b.tiles for y in b.tiles[x]}
    assert ta < tb
    assert [(c.x, c.y, c.text) for c in lua_list(a.build)] == [(c.x, c.y, c.text) for c in lua_list(b.build)]
    # turned levels turn their room list too (ring, orient 3)
    c = mk(shops=["Still"], style=STYLE_B71, spare=1)
    shop = [x for x in lua_list(c.rooms_at) if x.text == "shop:Still"][0]
    bld = lua_list(c.build)[0]
    assert (shop.x, shop.y) == (bld.x, bld.y)


# --- the bridge -------------------------------------------------------------------------

@plain_test("bridge: start_project passes spare, spare_for and join to the builder; bad values refused")
def _():
    need()
    src = bridge_part_src("ai-bridge-actions")
    i = src.index("elseif a.kind == 'workshops' then")
    part = src[i:i + 1800]
    assert "p.spare = int_in(a.spare, 0, 8)" in part
    assert "string_list(a.spare_for, layouts.WORKSHOPS, 8)" in part
    assert "a.join ~= false and a.join ~= true and a.join ~= 'band'" in part
    # the builder stores them with the level (made again from its params later)
    bsrc = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert "spare = params.spare, spare_for = params.spare_for" in bsrc


# --- the brain --------------------------------------------------------------------------

@plain_test("brain: a new level's plan: the shops' industry-mates the fort lacks, 4-6 rooms; urgent 4 at most")
def _():
    s = {"buildings": {"workshops": {"Kitchen": 1, "MetalsmithsForge": 1}, "furnaces": {"Smelter": 0}},
         "projects": {"open": [{"kind": "workshops", "summary": {"workshops": ["WoodFurnace"]}}]}}
    a = {"type": "start_project", "kind": "workshops", "shops": ["Smelter"]}
    b = PS.shop_level_action(a, s)
    assert b is not a and a == {"type": "start_project", "kind": "workshops", "shops": ["Smelter"]}
    assert b["spare_for"][:2] == ["Kiln", "GlassFurnace"] and len(b["spare_for"]) == b["spare"] == 5, b
    u = PS.shop_level_action(dict(a, urgent=True), s)
    assert u["spare"] == 3, u
    many = PS.shop_level_action({"type": "start_project", "kind": "workshops",
                                 "shops": ["Kitchen", "Still", "Butchers", "Tanners", "Farmers", "Fishery", "Quern"]}, s)
    assert many["spare"] == 0, many
    # the rule's own say stands; other actions untouched
    own = dict(a, spare=0)
    assert PS.shop_level_action(own, s) == own
    other = {"type": "start_project", "kind": "bedrooms", "rooms": 4}
    assert PS.shop_level_action(other, s) is other
    # field kitchens: joins only a level in its band
    fk = PS.shop_level_action(dict(a, plan={"elev_lo": 1, "elev_hi": 3}, customs=["field_kitchens"]), s)
    assert fk["join"] == "band"
    assert "join" not in b
    assert PS.shop_level_action({"type": "start_project", "kind": "workshops", "shops": None}, None) is not None


@plain_test("brain and builder name the same industries")
def _():
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    block = src[src.index("WORKSHOP_GROUP_ORDER = {"):src.index("WORKSHOP_PILE_USERS")]
    lua = {g: re.findall(r"'(\w+)'", body) for g, body in re.findall(r"(\w+) = \{([^{}]*)\}", block)}
    assert lua == PS.WORKSHOP_GROUP_ORDER, (lua, PS.WORKSHOP_GROUP_ORDER)
    gblock = src[src.index("WORKSHOP_GROUPS = {"):src.index("WORKSHOP_GROUP_ORDER = {")]
    groups = dict(re.findall(r"(\w+) = '(\w+)'", gblock))
    assert groups == PS.WORKSHOP_GROUPS, set(groups.items()) ^ set(PS.WORKSHOP_GROUPS.items())


@plain_test("brain: the overseer sends the workshops level through shop_level_action (plan() itself unchanged)")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert "r = bridge.act(shop_level_action(p.action, state))" in src
    assert "from planner_shopslots import shop_level_action" in src
    psrc = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "shop_level_action" not in psrc and "planner_shopslots" not in psrc


@plain_test("brain: a join is no new level for the master plan's districts nor the scorecard's levels")
def _():
    from harness import code_has
    m = (ROOT / "brain" / "masterplan.py").read_text(encoding="utf-8")
    i = m.index("def note_result(")
    assert code_has(m[i:i + 1200], 'if result.get("joined") is not None: return None')
    sc = (ROOT / "brain" / "scorecard.py").read_text(encoding="utf-8")
    assert code_has(sc, 'elif t == "start_project" and r.get("joined") is None:')


if __name__ == "__main__":
    finish()
