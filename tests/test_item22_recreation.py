"""(0.105.115 item22) The recreation burrow made its members meet: why they didn't.

25 Nov 07:23 (a probe over the forts): 19 members (A 3, B 2, E 11, F 3), one
in a social activity (Worship and Prayer), the rest hauling
(StoreItemInBarrel, PickupEquipment) or idle in bedrooms. 10:48-10:50 (probes
i22-rec, i22-fr on B and F): the burrow held 41 (B) and 37 (F) stockpiles,
95-99 bedroom and 13-14 dining zones and F's pond besides the tavern and
temple; every member had 85-89 labours on (the "everybody" details); F's
members were filling the pond, storing in barrels, asleep in bedrooms. None
of the members' close friends (love 50+) was a member or in the burrow; two
of F's (BeWithFriends -200000) had no close friend in the fort at all.

1. The burrow is the tavern's and temple's zones only (no bedroom, dining
   hall or stockpile; the food and drink piles only when neither drink in
   those zones nor a well is found). The drowsy go out to sleep (no bed).
2. A member's labours go off while in (kept in the save, given back when it
   goes out; one the details give back is taken off again at each report);
   out early when patients wait and nobody outside can diagnose.
3. Half a game day at least in (REC_MIN_STAY), unless an emergency.
4. The places for friends go first to those with a close friend already in
   the burrow, then to those whose close friend can come along (brought in:
   a pal, kept while the lonely one is); never one with no close friend.
5. Why each member went out, in the tick's result (out_why: the journal).

    python tests/test_item22_recreation.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

SRC = split_src("ai-society-burrows.lua")


def body(name: str) -> str:
    b = SRC[SRC.index(name):]
    return b[:b.index("\nend\n")]


def _fake() -> str:
    tree = ast.parse((ROOT / "tests" / "test_society.py").read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "FAKE" for t in n.targets))


def world():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, units, assigned, ntiles, g = lua.execute(_fake(), module_src("ai-society.lua"))
    lua.execute("""local env, units = ...
      env.df.unit_labor = {[0] = 'MINE', [1] = 'HAUL_FOOD', [2] = 'DIAGNOSE',
                           MINE = 0, HAUL_FOOD = 1, DIAGNOSE = 2, _last_item = 2}
      for _, u in pairs(units) do u.status = {labors = {[0] = true, [1] = true, [2] = false}} end
    """, env, units)
    return lua, env, units, assigned, ntiles, g


def lst(t) -> list:
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


# ---- the source --------------------------------------------------------------------------------

@test("1: the burrow is the tavern's and temple's zones; bedrooms, dining halls and piles gone (piles a last resort)")
def _():
    assert "local REC_ZONES = {MeetingHall = true}" in SRC
    f = body("function fill_recreation(burrow)")
    first = f[:f.index("local water = rec_water(burrow, cx)")]
    assert "Stockpile" not in first, "no pile before the drink is looked for"
    rest = f[f.index("local water = rec_water(burrow, cx)"):]
    assert "if water == nil then" in rest and "b.settings.flags.food" in rest and "AI cell larder " in rest
    assert "REC_FILL_V = 3" in SRC                      # a burrow of the old layout filled again at once
    tick = body("function recreation_tick(")
    assert "rec_gathering(rec_locations())" in tick and "moved" in tick


@test("1: the drowsy never join and are let out (no bed in the burrow); the weather's rec_dry unchanged")
def _():
    assert "u.counters2.sleepiness_timer >= REC_SLEEPY" in SRC and "REC_SLEEPY = 57600" in SRC
    assert "if rec_tired(u) then return false end" in body("local function rec_base(u)")
    assert "rec_tired(u)" in body("local function rec_soldier_base(u)")
    assert "'drowsy'" in body("local function rec_keep(") and "'drowsy'" in body("local function rec_keep_soldier(")
    assert "sleepiness" not in body("local function rec_dry(u)")


@test("2/3: labours off on the way in and back on the way out; half a day at least, emergencies first")
def _():
    keep = body("local function rec_keep(")
    i_min = keep.index("if now - since < REC_MIN_STAY then return true, nil, u end")
    for e in ("'thirsty or hungry'", "'drowsy'", "'a tantrum'", "'needs care'", "'a mood'", "'a held killer'"):
        assert keep.index(e) < i_min, e
    assert keep.index("'recovered'") > i_min and keep.index("'need met'") > i_min
    assert "REC_MIN_STAY = 600" in SRC
    out = body("local function rec_let_out(")
    assert "rec_labors_back(d, id, u)" in out and "d.out_why[why]" in out and "d.pals[id] = nil" in out
    tick = body("function recreation_tick(")
    assert "laboff = laboff + rec_labors_off(d, tostring(u.id), u)" in tick
    assert tick.count("admit(") >= 4                    # the unhappy, the lonely, their pals, the soldiers
    assert "out_why = out_why" in tick and "d.out_why = nil" in tick
    st = body("function recreation_status(")
    assert "relabored = relabored + rec_labors_off(d, id, u)" in st and "'a doctor needed'" in st


@test("4: friends' places: a friend inside first, then one who can come along; none with no close friend")
def _():
    tick = body("function recreation_tick(")
    assert "close_friends(u, by_hf)" in tick and "if close and #close == 0 then tier = nil" in tick
    assert "d.pals[tostring(p.id)] = c.u.id" in tick
    assert "r.core.love >= REC_CLOSE_LOVE" in SRC and "REC_CLOSE_LOVE = 50" in SRC
    assert "'friend gone out'" in body("local function rec_keep(")


@test("the hub stays under the 60,000-byte limit")
def _():
    n = len((ROOT / "lua" / "ai-society-burrows.lua").read_bytes().replace(b"\r", b""))
    assert n < 60000, n


@test("brain: the recreation rule's reason names the tavern and temple, labours off")
def _():
    import copy
    import json
    import digest
    from planner import PLANNER_CONFIG as CFG, Memory
    from planner_society import _recreation_rule
    s = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s = digest.normalize(copy.deepcopy(s))
    s["dwarves"]["total"] = 40
    s.setdefault("society", {})["recreation"] = {"members": 2}
    props: list = []
    _recreation_rule(s, CFG, [], props, Memory())
    assert props and "the tavern and temple" in props[0].reason and "labours off" in props[0].reason, \
        [p.reason for p in props]


# ---- the bridge in a Lua engine (lupa) -----------------------------------------------------------

@test("lupa 1: bedrooms and dining halls stay out; a food pile only when no drink is in the zones")
def _():
    need_lua()
    lua, env, units, assigned, ntiles, g = world()
    lua.execute("""local env = ...
      local all = env.df.global.world.buildings.all
      env.df.civzone_type[2], env.df.civzone_type[3] = 'Bedroom', 'DiningHall'
      local function z(id, t, x) return {id = id, x1 = x, y1 = 0, x2 = x + 1, y2 = 0, z = 10, type = t,
                                         getType = function() return 'Civzone' end} end
      all[1] = z(51, 2, 10); all[2] = z(52, 3, 13)
      all[3] = {id = 53, x1 = 20, y1 = 0, x2 = 20, y2 = 0, z = 10, name = 'food', settings = {flags = {food = true}},
                getType = function() return 'Stockpile' end}
    """, env)
    r = env.recreation_tick(8, 28, False)
    assert r.ok and r.tiles == 6 and ntiles() == 6, dict(r)          # the 3x2 meeting hall alone
    assert env.recreation_status().water == "drink"
    lua, env, units, assigned, ntiles, g = world()
    lua.execute("""local env = ...
      local all = env.df.global.world.buildings.all
      all[1] = {id = 53, x1 = 20, y1 = 0, x2 = 20, y2 = 0, z = 10, name = 'food', settings = {flags = {food = true}},
                getType = function() return 'Stockpile' end}
      env.df.global.world.items.other.DRINK[0].pos = {x = 20, y = 0, z = 10}
    """, env)
    r = env.recreation_tick(8, 28, False)
    assert r.ok and r.tiles == 7 and env.recreation_status().water == "piles" and r.members == 3, dict(r)


@test("lupa 2/3: labours off in, re-cleared at the report, given back out; the recovered wait half a day")
def _():
    need_lua()
    lua, env, units, assigned, ntiles, g = world()
    r = env.recreation_tick(8, 28, False)
    assert assigned[1] and assigned[2] and assigned[7] and r.labors_off == 6, dict(r)
    assert not units[1].status.labors[0] and not units[1].status.labors[1]
    assert units[6].status.labors[0], "a non-member keeps his"
    units[1].status.labors[1] = True                                  # the details gave one back
    st = env.recreation_status()
    assert st.labors_reset == 1 and not units[1].status.labors[1], dict(st)
    units[1].cat = 3                                                  # no longer unhappy
    g.cur_year_tick = 1000 + 300
    assert env.recreation_status().members == 3, "half a day at least"
    g.cur_year_tick = 1000 + 700
    st = env.recreation_status()
    assert st.members == 2 and not assigned[1] and st.out_why.recovered == 1, dict(st)
    assert units[1].status.labors[0] and units[1].status.labors[1] and not units[1].status.labors[2]
    r = env.recreation_tick(8, 28, False)
    assert r.out_why.recovered == 1, dict(r)                          # into the journal, then cleared
    g.cur_year_tick = 1000 + 800
    assert env.recreation_status().out_why is None


@test("lupa 2: an emergency never waits; patients and no diagnoser outside: the member who diagnosed goes out")
def _():
    need_lua()
    lua, env, units, assigned, ntiles, g = world()
    units[1].status.labors[2] = True                                  # dwarf 1 diagnoses; 5 is a patient
    env.recreation_tick(8, 28, False)
    assert not assigned[1] and assigned[2]
    lua, env, units, assigned, ntiles, g = world()
    units[5].health.flags.needs_healthcare = False
    units[1].status.labors[2] = True
    env.recreation_tick(8, 28, False)
    assert assigned[1]
    units[5].health.flags.needs_healthcare = True                     # a patient now (5 is never a member)
    st = env.recreation_status()
    assert not assigned[1] and assigned[2] and st.out_why["a doctor needed"] == 1, dict(st)
    assert units[1].status.labors[2]


@test("lupa 4: a lonely dwarf's close friend comes along; one with no close friend gets no place")
def _():
    need_lua()
    lua, env, units, assigned, ntiles, g = world()
    lua.execute("""local env, units = ...
      env.df.need_type = {[9] = 'BeWithFriends'}
      local function lonely(u, f) u.status.current_soul = {personality = {needs = {[0] = {id = 9, focus_level = f}}}} end
      for id, u in pairs(units) do u.hist_figure_id = 100 + id end
      lonely(units[6], -20000)            -- content, badly lonely, a close friend: dwarf 1
      lonely(units[7], -50000)            -- worse, but no close friend in the fort
      units[7].cat = 4
      local HF = {}
      for id in pairs(units) do HF[100 + id] = {info = {relationships = {hf_visual = {}}}} end
      HF[106].info.relationships.hf_visual = {{histfig_id = 101, core = {love = 60}},
                                              {histfig_id = 102, core = {love = 10}}}
      env.df.historical_figure = {find = function(id) return HF[id] end}
      units[1].cat = 4; units[2].cat = 4  -- nobody unhappy: the friends' places only
    """, env, units)
    r = env.recreation_tick(8, 28, False, None, 2, 7)
    added = lst(r.added)
    assert assigned[6] and assigned[1] and not assigned[7] and not assigned[2], (added, dict(assigned))
    assert "dwarf 1 (a friend of dwarf 6)" in added and r.no_close_friend == 1, added
    st = env.recreation_status()
    assert st.for_friends == 2 and st.for_pals == 1, dict(st)
    # the lonely one's need met (after half a day): out, and his friend with him
    lua.execute("local units = ...; units[6].status.current_soul.personality.needs[0].focus_level = 0", units)
    g.cur_year_tick = 1000 + 700
    env.recreation_status()
    env.recreation_status()
    assert not assigned[6] and not assigned[1], dict(assigned)


finish()
