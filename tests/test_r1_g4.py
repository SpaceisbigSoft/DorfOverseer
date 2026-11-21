"""(R1 g4) The civilians' shelter: never past an intruder, never dry, never flipping.

Evidence (run2/A2.md finding 1, R-B.md finding 2, R-CE.md):
  * A2 (B, 0.105.54 replay): the flee step (`_shelter_pick_rule` rule 3)
    took `choose_shelter(..., exclude=cur)` without its livable/drink tests:
    "the civilians move at once to level 152 ... holds only 39 drink and no
    well (needs 194), 0 food" for 97 civilians; the next cycle the ordinary
    branch put the whole fort back, and the flee fired again ("0 steps from
    the shelter (the whole fort)"): 18 moves in two minutes;
  * R-CE (E): civilians sent to [153] with 0 drink 22 times under an
    812-day alarm;
  * R-B (B, y262): a lone invader inside (Len, x113 y116 z162); the pick
    was measured "from the surface at x108 y149 z170", rule 3 applied to
    great dangers only, and level 163 was taken although marked "none the
    civilians surely reach first" (safe False): they walked down the one
    central stair x108 y149, and 14 of 26 dead lay within a tile of it.

Here: the bridge's walk measures each danger inside from its own tile and
marks the civilians whose way to a level passes it (`civ_exposed`); the
brain never takes such a level nor one it marks unsafe (the civilians stay
where they are), the flee step takes only a level that holds them, and a
move is held for `g4_shelter_hold_ticks` for the same dangers.

    python tests/test_r1_g4.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_shelter as PS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
YEAR = 403200


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if not keys:
        return {}
    if all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


# --- the brain -------------------------------------------------------------------------

def cand(z, d, p90=5, drink=0, wells=0, tiles=400, food=400, reached=20, **kw):
    c = {"z": z, "d_threat": d, "civ_p90": p90, "civ_med": p90 // 2, "civ_reached": reached, "civ_late": 0,
         "drink": drink, "wells": wells, "tiles": tiles, "food": food, "chokes": [],
         "way_in": {"id": 1, "kind": "surface", "x": 108, "y": 149, "z": 170}}
    c.update(kw)
    return c


def splan(cands, dangers, current=None, tick=None, civs=20, current_walk=None):
    p = {"danger": True, "candidates": cands, "dangers": dangers, "civilians": civs, "barracks": []}
    if current is not None:
        p["current"] = {"levels": current}
        if tick is not None:
            p["current"]["tick"] = tick
    if current_walk is not None:
        p["current_walk"] = current_walk
    return p


def state(sp, tick=1000, total=20):
    return {"date": {"year": 300, "tick": tick}, "shelter_plan": sp, "civ_alert": True,
            "civ_alert_shelter": "ai", "dwarves": {"total": total}, "military": {"squads": []}}


def run(s, memory=None):
    props, notes = [], []
    PS._shelter_pick_rule(s, CFG, props, notes, memory if memory is not None else Memory())
    return props, notes


def titan_inside(to_shelter=None, did=900, great=True, name="Submergewoods"):
    return [{"id": did, "name": name, "great": great or None, "invader": None if great else True, "inside": True,
             "to_shelter": to_shelter, "x": 80, "y": 150, "z": 160}]


@test("A2: the flee step never sends 97 civilians to level 152 (39 drink, no well, 0 food): they stay put")
def _():
    # B's replay 16:29: the whole fort was the shelter, the titan inside it
    sp = splan([cand(152, 60, drink=39, food=0, tiles=600), cand(148, 70, drink=0, food=0, tiles=500)],
               titan_inside(), civs=97)
    p, n = run(state(sp, total=97))
    assert p == [], [(x.rule, x.action) for x in p]
    assert any("stay where they are" in x and "holds" in x for x in n), n


@test("E: no flee to a level with 0 drink and no well (R-CE: [153], 22 times)")
def _():
    sp = splan([cand(153, 40, drink=0, wells=0, food=500), cand(154, 30, drink=0, food=100)],
               titan_inside(to_shelter=5), current=[160], civs=90)
    p, n = run(state(sp, total=90))
    assert all(x.rule != "shelter_flee" for x in p) and not any(x.action.get("levels") for x in p), \
        [(x.rule, x.action) for x in p]


@test("A2 flip: flee to a level that holds them, then held: no pick undoes it, no flee from the whole fort again")
def _():
    mem = Memory()
    cands = [cand(150, 70, wells=1), cand(140, 95, wells=1, p90=8)]
    # cycle 1: the whole fort, the titan inside: flee once, to a level that holds them
    p, n = run(state(splan(cands, titan_inside()), tick=1000), mem)
    assert [x.rule for x in p] == ["shelter_flee"], [(x.rule, x.action) for x in p]
    lv = p[0].action["levels"]
    # the move made (the pick's own tick in the report); cycle 2: the titan far from it, the
    # ordinary pick would move them again (old: shelter_pick to another level at once)
    other = [cand(150, 140, wells=1), cand(140, 95, wells=1, p90=8)]
    p, n = run(state(splan(other, titan_inside(to_shelter=60), current=lv, tick=300 * YEAR + 1000),
                     tick=1100), mem)
    assert p == [], [(x.rule, x.action) for x in p]
    assert any("held" in x for x in n), n
    # the pick lapsed and the whole fort came back (as in A2): no flee from it while held
    p, n = run(state(splan(cands, titan_inside()), tick=1200), mem)
    assert p == [], [(x.rule, x.action) for x in p]
    assert any("held" in x and "stay where they are" in x for x in n), n
    # the hold over (a game day): a new decision
    p, n = run(state(splan(cands, titan_inside()), tick=1200 + CFG["g4_shelter_hold_ticks"] + 1), mem)
    assert [x.rule for x in p] == ["shelter_flee"], [(x.rule, x.action) for x in p]


@test("hold: the intruder comes close to the picked shelter: fled at once; a new danger: a new decision")
def _():
    mem = Memory()
    cands = [cand(150, 70, wells=1), cand(140, 95, wells=1, p90=8)]
    run(state(splan(cands, titan_inside(to_shelter=60), current=[160], tick=300 * YEAR + 1000), tick=1000), mem)
    p, n = run(state(splan(cands, titan_inside(to_shelter=8), current=[160], tick=300 * YEAR + 1000),
                     tick=1050), mem)
    assert [x.rule for x in p] == ["shelter_flee"], [(x.rule, x.action) for x in p]
    # held, a better pick: none; a second danger comes: a new decision
    far = [cand(160, 40, wells=1), cand(140, 95, wells=1, p90=8)]
    sp = splan(far, [{"id": 901, "name": "Goblin", "invader": True, "x": 1, "y": 1, "z": 170}],
               current=[160], tick=300 * YEAR + 1000)
    mem2 = Memory()
    run(state(sp, tick=1000), mem2)
    sp["dangers"] = sp["dangers"] + [{"id": 902, "name": "Goblin 2", "invader": True, "x": 1, "y": 1, "z": 170}]
    p, n = run(state(sp, tick=1100), mem2)
    assert [x.rule for x in p] == ["shelter_pick"] and p[0].action["levels"] == [140], [(x.rule, x.action) for x in p]


@test("B y262: level 163 marked 'none the civilians surely reach first' is never taken: they stay where they are")
def _():
    # the journal 09:25:16: walk 7 from x108 y149 z170, the civilians' 26 (90%); 176 drink, 207 food, 665 tiles
    sp = splan([cand(163, 7, p90=26, drink=176, food=207, tiles=665),
                cand(166, 4, p90=20, drink=30, food=50, tiles=300)],
               [{"id": 77, "name": "Len", "invader": True, "x": 113, "y": 116, "z": 162}], civs=30)
    c = PS.choose_shelter(sp, CFG, citizens=30)
    assert c["main"] == 163 and not c["safe"], c                   # the old pick, marked unsafe
    p, n = run(state(sp, total=30))
    assert p == [], [(x.rule, x.action) for x in p]
    assert any("stay where they are" in x for x in n), n


@test("B y262: a level whose way passes the intruder (civ_exposed) is never safe; one clear of it is taken")
def _():
    dz = [{"id": 77, "name": "Len", "invader": True, "inside": True, "to_shelter": 60, "x": 113, "y": 116, "z": 162}]
    # 163: the farthest by walk and the only wet one, but every civilian's way passes Len's stair
    sp = splan([cand(163, 34, p90=8, wells=1, civ_exposed=15), cand(165, 36, p90=6, drink=100, civ_exposed=0)],
               dz, current=[169], civs=15)
    c = PS.choose_shelter(sp, CFG, citizens=15)
    assert c["main"] == 165 and c["safe"], c
    sp["candidates"][1]["civ_exposed"] = 3
    c = PS.choose_shelter(sp, CFG, citizens=15)
    assert not c["safe"] and "passes an intruder" in c["why"], c
    p, n = run(state(sp, total=15))
    assert all(x.action.get("levels") is None for x in p), [(x.rule, x.action) for x in p]


@test("an intruder's own walk (d_inside) counts, not only the entrance's")
def _():
    sp = splan([cand(150, 90, p90=10, wells=1, d_inside=12), cand(160, 40, p90=10, wells=1)],
               [{"id": 77, "name": "Len", "invader": True, "inside": True, "x": 1, "y": 1, "z": 150}])
    c = PS.choose_shelter(sp, CFG, citizens=20)
    assert c["main"] == 160 and c["d_threat"] == 40, c


@test("an invader (not a great danger) inside, close to the shelter: the flee step runs for it too")
def _():
    sp = splan([cand(150, 70, wells=1), cand(140, 95, wells=1, p90=8)],
               titan_inside(to_shelter=6, great=False, name="Len"), current=[160])
    p, n = run(state(sp))
    assert [x.rule for x in p] == ["shelter_flee"] and 160 not in p[0].action["levels"], p


# --- the bridge's walk (lupa) ----------------------------------------------------------

PURE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.reqscript = function(n) error('no ' .. tostring(n)) end
assert(load(src, 'ai-shelter-plan', 't', env))()
-- B's main stair: one column x108 y149 from z162 to z170; each level a room
-- x100-116 y110-155 round it
function env.b_fort()
    local g = {}
    for z = 162, 170 do
        for x = 100, 116 do
            for y = 110, 155 do g[env.K(x, y, z)] = env.WALK + env.INSIDE end
        end
        local f = env.WALK + env.INSIDE
        if z < 170 then f = f + env.UP end
        if z > 162 then f = f + env.DOWN end
        g[env.K(108, 149, z)] = f
    end
    return g
end
function env.level_seeds(z)
    local s = {}
    for x = 100, 116 do for y = 110, 155 do table.insert(s, env.K(x, y, z)) end end
    return s
end
return env
"""


@test("walk (B's stair): Len at x113 y116 z162: every way to 163 passes his stair; 165 and 169 none")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(PURE, module_src("ai-shelter-plan.lua"))
    g = env.b_fort()
    len_k = env.K(113, 116, 162)
    zone, nz = env.danger_zone(g, T(lua, [{"key": len_k, "z": 162}]))
    assert zone[env.K(108, 149, 162)] and zone[env.K(108, 149, 163)], nz       # his level's stair, the next
    assert not zone[env.K(108, 149, 164)] and not zone[env.K(108, 140, 163)], nz
    civs = [env.K(105 + i % 5, 145 + i // 5, 168) for i in range(10)] + [env.K(110 + i, 150, 166) for i in range(5)]
    cands = T(lua, [{"z": z, "key": z, "seeds": env.level_seeds(z)} for z in (163, 165, 169)])
    out, _ = env.plan(g, cands, T(lua, [len_k]), T(lua, civs), T(lua, [len_k]), T(lua, {"zone": zone}))
    by = {c["z"]: c for c in py(out)}
    assert by[163]["civ_exposed"] == 15, by[163]
    assert by[165]["civ_exposed"] == 0 and by[169]["civ_exposed"] == 0, (by[165], by[169])
    assert by[163]["d_threat"] == 34 and by[165]["d_inside"] == 36, by
    # end to end: 163 the only wet one -> nothing taken; 165 wet too -> 165
    sp = splan([dict(c, drink=0, wells=1 if c["z"] == 163 else 0, food=400, tiles=800, chokes=[], way_in=None)
                for c in by.values()], [{"id": 77, "name": "Len", "invader": True, "inside": True, "to_shelter": 60}],
               current=[170], civs=15)
    p, n = run(state(sp, total=15))
    assert all(x.action.get("levels") is None for x in p), [(x.rule, x.action) for x in p]
    for c in sp["candidates"]:
        if c["z"] == 165:
            c["drink"] = 100
    c = PS.choose_shelter(sp, CFG, citizens=15)
    assert c["main"] == 165 and c["safe"], c


@test("walk: a clean way as short as a tainted one counts as clean; no zone: as before (3 values)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(PURE, module_src("ai-shelter-plan.lua"))
    g = env.b_fort()
    seeds = T(lua, [env.K(100, 110, 165)])
    # (101,110) is walked first and tainted; (102,111) is found from it first, then
    # from the clean (101,111) at the same distance: clean
    zone = T(lua, {env.K(101, 110, 165): True})
    dist, n, capped, bad = env.bfs(g, seeds, None, zone)
    assert bad[env.K(101, 110, 165)] and dist[env.K(102, 111, 165)] == 2
    assert not bad[env.K(102, 111, 165)] and not bad[env.K(102, 110, 165)], "a clean way as short"
    r = env.bfs(g, seeds)
    assert len(r) == 3, r


@test("plan freshness: an intruder inside: walked again after SHELTER_PLAN_INSIDE_TICKS (it moves)")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(PURE, module_src("ai-shelter-plan.lua"))
    m = T(lua, {"sig": "a", "dsig": "1", "tick": 1000})
    assert env.plan_fresh(m, "a", "1", 1050, True)[0] is True
    assert env.plan_fresh(m, "a", "1", 1000 + env.SHELTER_PLAN_INSIDE_TICKS, True)[0] is False
    assert env.plan_fresh(m, "a", "1", 1300, False)[0] is True


def _fake_src(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


@test("report: an invader inside is a source at its own tile; the civilians' ways past it counted; nothing taken")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake_src("test_h5_shelter_plan.py", "FAKE"), module_src("ai-shelter-plan.lua"))
    lua.execute("""local env, W = ...
        W.block(100, {'', ' o............>'})
        local hall, deep = {'', ' .............X'}, {'', ' .............<'}
        for i = 1, 6 do table.insert(hall, ' ..............'); table.insert(deep, ' ..............') end
        W.block(99, hall)
        W.block(98, deep)""", env, w)

    def unit(**kw):
        u = T(lua, kw)
        w.units[len(w.units) + 1] = u
        if kw.get("citizen"):
            w.cits[len(w.cits) + 1] = u
    for x, y, z in ((5, 1, 100), (3, 5, 99)):
        unit(citizen=True, pos={"x": x, "y": y, "z": z}, military={"squad_id": -1},
             flags1={"caged": False, "chained": False})
    unit(id=77, name="Len", danger=True, invader=True, pos={"x": 13, "y": 1, "z": 100},
         flags1={"caged": False, "chained": False})
    r = py(env.report())
    assert r["danger"] is True and r["dangers"][0].get("inside") is True, r.get("dangers")
    assert r.get("intruders_walked") == 1 and r.get("zone_tiles", 0) > 0, r
    by = {c["z"]: c for c in r["candidates"]}
    assert by[99]["civ_exposed"] == 1 and by[98]["civ_exposed"] == 2, by
    assert by[99]["way_in"]["kind"] == "intruder" and by[99]["d_threat"] == 2, by[99]
    sp = dict(r)
    p, n = run(state(sp, total=2))
    assert all(x.action.get("levels") is None for x in p), [(x.rule, x.action) for x in p]


if __name__ == "__main__":
    finish()
