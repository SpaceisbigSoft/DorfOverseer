"""(R2 h3) Building slots: levels held for years by one missing piece, small
needs starved by the cap, digs that never began, and paper that was never
made. The evidence (run2/ROUND2.md; audit A1 4, A3 B3 and 31, R-CE):

1. A level waiting on the same pieces for h3_park_days is parked
   (park_project): it holds no slot while those pieces are missing, its
   pieces stay ordered, and it counts again once one comes. E's Millstone
   levels #75 and #78 (640 and 499 days, "Workshop: 1"), F's bedrooms #66
   (711 days, one bed and one box). Pieces nothing makes, or that never come
   in h3_park_drop_days, are taken off and the level finished (named).
2. The small needs (paper shop, mood workshops, wells, a still or kitchen
   while drink or meals are short) have a pool of their own (NEED_SLOTS, the
   one R1 g6's mood workshops used): C refused paper_shop 9 times and E 13
   with "already N unfinished building projects".
3. A level with no tile dug for h3_dig_check_days whose waiting tiles no dwarf
   can reach is given up then (F's storage level #55, 0 of 505, "beside
   ground the dwarves can't reach"), not after unreached_dig_days.
4. Paper: A milled slurry 135 times, D 264, and the press never once had any
   to press (press inputs 0, 0 sheets in six forts): the press is ordered
   beside the slurry; and a press reagent of REACTION_CLASS form is counted.

    python tests/test_r2_h3.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import digest  # noqa: E402
import planner  # noqa: E402
import planner_paper as PP  # noqa: E402
import planner_slots as SL  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, TICKS_PER_DAY  # noqa: E402
from planner_core import Proposal  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BUILDER_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', (ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"),
                            re.S).group(1)
DAY = 1200
YEAR = 403200


def builder():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA_DIR)
    B, W = lua.execute(BUILDER_HARNESS, (LUA_DIR / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA_DIR / "ai-builder.lua").read_text(encoding="utf-8"))
    return lua, B, W


def ltab(lua, **kw):
    t = lua.table()
    for k, v in kw.items():
        t[k] = lua.table_from(v) if isinstance(v, (list, dict)) else v
    return t


# E at the snapshot (A1 4): two Millstone levels furnishing 640 and 499 days, one
# waiting workshop each; F's bedrooms 711 days on one bed and one box; a hospital
NOW = 259 * YEAR + 259313
E_LEVELS = """function(now)
  local function lvl(id, kind, days, parked)
    local t = now - days * 1200
    return {id = id, kind = kind, phase = 'furnish', area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70},
            furnish_started = {year = t // 403200, tick = t % 403200},
            parked = parked and {sig = parked, year = 259, tick = 0} or nil}
  end
  return {lvl(75, 'workshops', 640, 'Workshop:1'), lvl(78, 'workshops', 499, 'Workshop:1'),
          lvl(66, 'bedrooms', 711, 'Bed:1,Box:1'), lvl(45, 'hospital', 113, 'Bed:4,Box:2,Table:1'),
          {id = 129, kind = 'storage', phase = 'dig'}}
end"""
WAITS = """function(by)
  return function(p) return {placed = 3, done = 1, waiting = by[p.id] or {}} end
end"""


# ---- 1. parked levels hold no slot ----------------------------------------------------------------

@test("1 lua: parked levels (E's Millstones 640/499 days, F's bedrooms 711) hold no slot; a new level goes in")
def _():
    lua, B, W = builder()
    B.now_tick = lua.eval(f"function() return {NOW} end")
    levels = lua.eval(E_LEVELS)(NOW)
    waits = lua.eval("{[75] = {Workshop = 1}, [78] = {Workshop = 1}, [66] = {Bed = 1, Box = 1}, "
                     "[45] = {Bed = 4, Box = 2, Table = 1}}")
    B.furnish_progress = lua.eval(WAITS)(waits)
    B.open_projects = lambda data: levels
    # today's cap would be 2 + 3 lent (FURNISH_LEND_MAX): 5 open, refused
    cap = B.slot_cap(levels)
    assert cap == int(B.MAX_OPEN_PROJECTS) + 4, cap      # four parked: a slot back each (none lent twice)
    r = B.start_project(ltab(lua, kind="bedrooms", rooms=4, room_size=3), lua.table(), True)
    assert "unfinished building projects" not in str(r.error), dict(r)
    # a bed comes to F's level: its waiting list changes, it holds its slot again
    waits[66] = lua.eval("{Box = 1}")
    assert not B.is_parked(levels[3]) and B.is_parked(levels[1])
    assert B.slot_cap(levels) == int(B.MAX_OPEN_PROJECTS) + 3 + 1, B.slot_cap(levels)   # 3 parked, F's lent once
    # never parked: as before (lent, FURNISH_LEND_MAX at most)
    for i in (1, 2, 3, 4):
        levels[i].parked = None
    assert B.slot_cap(levels) == int(B.MAX_OPEN_PROJECTS) + int(B.FURNISH_LEND_MAX)


@test("1 lua: park_project parks a level on its current pieces only; the report says parked and the pool")
def _():
    lua, B, W = builder()
    B.now_tick = lua.eval(f"function() return {NOW} end")
    data = B.load_projects()
    data.list[1] = lua.eval("{id = 66, kind = 'bedrooms', phase = 'furnish', z = 70, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70}, cells = {}}")
    data.list[2] = lua.eval("{id = 70, kind = 'bedrooms', phase = 'dig', z = 71, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 71}, cells = {}}")
    data.next_id = 71
    B.save_projects(data)
    waits = lua.eval("{[66] = {Bed = 1, Box = 1}}")
    B.furnish_progress = lua.eval(WAITS)(waits)
    r = B.park_project(66, "Bed:2,Box:1")
    assert not r.ok and "changed" in str(r.error), dict(r)
    assert not B.park_project(70, "x").ok                       # being dug: not parked
    r = B.park_project(66, "Bed:1,Box:1")
    assert r.ok and r.parked and r.sig == "Bed:1,Box:1", dict(r)
    rec = [p for p in B.load_projects().list.values() if p.id == 66][0]
    assert rec.parked.sig == "Bed:1,Box:1"
    assert B.park_project(66, "Bed:1,Box:1").already
    waits[66] = lua.eval("{}")
    assert not B.park_project(66, "").ok                        # nothing missing: it finishes instead


@test("1 lua: finish_project give_up with drop takes the named pieces off (F's one bed and one box) and finishes")
def _():
    lua, B, W = builder()
    B.now_tick = lua.eval(f"function() return {NOW} end")
    B.df = lua.eval("{building_type = {Bed = 3, Box = 4, Workshop = 1, Furnace = 2}}")
    data = B.load_projects()
    data.list[1] = lua.eval("{id = 66, kind = 'bedrooms', phase = 'furnish', z = 70, "
                            "area = {x1 = 0, y1 = 0, x2 = 9, y2 = 9, z = 70}, cells = {}}")
    data.next_id = 67
    B.save_projects(data)
    B.furnish_progress = lua.eval("function() return {placed = 28, done = 26, waiting = {Bed = 1, Box = 1}} end")
    calls = lua.eval("{}")
    B.drop_waiting_shops = lua.eval("function(calls) return function(p, kinds) "
                                    "table.insert(calls, kinds); return 2 end end")(calls)
    got = B.finish_project(66, False, False, True)
    assert not got.ok and "other than workshops" in str(got.error), dict(got)     # as before without drop
    got = B.finish_project(66, False, False, True, lua.table_from(["Bed"]))
    assert not got.ok and "other than those named" in str(got.error), dict(got)   # the box still waits
    got = B.finish_project(66, False, False, True, lua.table_from(["Bed", "Box"]))
    assert got.ok and got.phase == "done" and got.dropped == 2, dict(got)
    assert list(got.dropped_kinds.values()) == ["Bed", "Box"]
    k = calls[1]
    assert k.Bed and k.Box and k.Workshop and not k.Door
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "a.give_up == true, drop," in src and "function act_park_project(a)" in src
    assert "park_project = act_park_project" in (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"] = {"year": 259, "tick": 259313, "season": "autumn", "month": "Sandstone", "day": 21}
    s["orders"] = []
    return s


def furnish_level(id_, kind, waiting, days, **kw):
    sig = ",".join(sorted(f"{k}:{n}" for k, n in waiting.items()))
    p = {"id": id_, "kind": kind, "phase": "furnish", "started": {"year": 252, "tick": 51324},
         "furnish": {"placed": 3, "done": 1, "waiting": dict(waiting), "days": days, "sig": sig}}
    p.update(kw)
    return p


def park(s, memory):
    props, notes = [], []
    SL._park_rule(digest.normalize(s), memory, CFG, props, notes)
    return props, notes


@test("1 brain: the same pieces for h3_park_days: park_project (its sig); a change starts the count again")
def _():
    s = fort()
    s["projects"] = {"open": [furnish_level(66, "bedrooms", {"Bed": 1, "Box": 1}, 711)], "max_open": 3}
    m = Memory()
    props, _ = park(s, m)
    assert not props and m.furnish_seen["66"]["sig"] == "Bed:1,Box:1"         # first seen now
    m.furnish_seen["66"]["tick"] -= (CFG["h3_park_days"] - 1) * TICKS_PER_DAY
    assert not park(s, m)[0]
    m.furnish_seen["66"]["tick"] -= TICKS_PER_DAY
    props, _ = park(s, m)
    assert [p.action for p in props] == [{"type": "park_project", "project_id": 66, "sig": "Bed:1,Box:1"}], props
    assert "Bed 1, Box 1" in props[0].reason and "building slot" in props[0].reason
    # a box comes: the count starts again
    s["projects"]["open"] = [furnish_level(66, "bedrooms", {"Bed": 1}, 712)]
    assert not park(s, m)[0] and m.furnish_seen["66"]["sig"] == "Bed:1"
    s["projects"]["open"] = []
    park(s, m)
    assert "66" not in m.furnish_seen                                         # forgotten once closed


@test("1 brain: parked: a floodgate never taken off (y2 W3); the rest after h3_park_drop_days; a well kept")
def _():
    s = fort()
    m = Memory()
    lvl = furnish_level(90, "workshops", {"Workshop": 1, "Floodgate": 2}, 60, parked=True, parked_days=5)
    s["projects"] = {"open": [lvl]}
    m.furnish_seen = {"90": {"sig": lvl["furnish"]["sig"], "tick": abs_tick(s) - 60 * TICKS_PER_DAY}}
    assert not park(s, m)[0]                     # a workshop waits too: its own give-up (shop_piece_wait_days)
    lvl = furnish_level(90, "workshops", {"Floodgate": 2}, 60, parked=True, parked_days=5)
    s["projects"] = {"open": [lvl]}
    m.furnish_seen = {"90": {"sig": lvl["furnish"]["sig"], "tick": abs_tick(s) - 60 * TICKS_PER_DAY}}
    assert not park(s, m)[0]                     # (y2 W3) a floodgate is a KEEP_KINDS piece: never dropped
    lvl["parked_days"] = CFG["h3_park_drop_days"] + 1
    assert not park(s, m)[0]
    # F's bed and box: ordered, so they wait (parked) until h3_park_drop_days
    lvl = furnish_level(66, "bedrooms", {"Bed": 1, "Box": 1}, 711, parked=True, parked_days=100)
    s["projects"] = {"open": [lvl]}
    m.furnish_seen = {"66": {"sig": "Bed:1,Box:1", "tick": abs_tick(s) - 711 * TICKS_PER_DAY}}
    props, notes = park(s, m)
    assert not props and any("waits apart" in n for n in notes), notes
    lvl["parked_days"] = CFG["h3_park_drop_days"]
    props, _ = park(s, m)
    assert [p.action for p in props] == [{"type": "finish_project", "project_id": 66, "give_up": True,
                                          "drop": ["Bed", "Box"]}]
    lvl = furnish_level(7, "well", {"Well": 1}, 900, parked=True, parked_days=900)
    s["projects"] = {"open": [lvl]}
    m.furnish_seen = {"7": {"sig": "Well:1", "tick": abs_tick(s) - 900 * TICKS_PER_DAY}}
    assert not park(s, m)[0]                                                  # a well's well is never dropped


# ---- 2. the small needs' pool ---------------------------------------------------------------------

@test("2 lua: a small need (paper, well, drink) starts past the full cap, NEED_SLOTS of them; others refused")
def _():
    lua, B, W = builder()
    full = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                    "return t end")(int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 3)
    B.open_projects = lambda data: full
    r = B.start_project(ltab(lua, kind="workshops", shops=["ScrewPress"]), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)       # C 9, E 13 refusals
    for need in ("paper", "drink", "meals"):
        r = B.start_project(ltab(lua, kind="workshops", shops=["ScrewPress"], need=need), lua.table(), True)
        assert "unfinished building projects" not in str(r.error), (need, dict(r))
    assert int(B.MOOD_SHOP_OPEN_MAX) == int(B.NEED_SLOTS)                          # one pool, one number
    pool = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'workshops', phase = 'dig', "
                    "need = 'paper'} end return t end")(int(B.NEED_SLOTS))
    B.open_projects = lambda data: pool
    # the pool's own levels hold no ordinary slot (slot_cap gives each back) ...
    assert B.slot_cap(pool) == int(B.MAX_OPEN_PROJECTS) + int(B.NEED_SLOTS)
    # ... and the pool is full: another need waits for the ordinary cap
    for i in range(1, 4):
        pool[i] = lua.eval("{kind = 'workshops', phase = 'dig', need = 'well'}")
    extra = lua.eval("function(t, n) for i = 1, n do table.insert(t, {kind = 'bedrooms', phase = 'dig'}) end end")
    extra(pool, int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA))
    r = B.start_project(ltab(lua, kind="workshops", shops=["Quern"], need="paper"), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    r = B.start_project(ltab(lua, kind="workshops", shops=["Quern"], need="nonsense"), lua.table(), True)
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    src = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "p.need = a.need" in src


@test("2 lua: the need is kept on the new level (counted in the pool); a well always takes the pool")
def _():
    lua, B, W = builder()
    r = B.start_project(ltab(lua, kind="workshops", shops=["Quern"], need="paper"),
                        lua.table_from({"year": 148, "tick": 100}))
    assert r.ok and r.need == "paper", dict(r)
    rec = [p for p in B.load_projects().list.values() if p.id == r.project_id][0]
    assert rec.need == "paper" and B.project_need(rec) == "paper"
    rep = B.projects_report()
    assert rep.need_slots_free == int(B.NEED_SLOTS) - 1, rep.need_slots_free
    assert [o.need for o in rep.open.values()] == ["paper"]
    full = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                    "return t end")(int(B.MAX_OPEN_PROJECTS) + int(B.URGENT_EXTRA) + 3)
    B.open_projects = lambda data: full
    r = B.place_well(ltab(lua, urgent=True), lua.table(), True)        # a well: always the needs' pool
    assert "unfinished building projects" not in str(r.error), dict(r)
    wells = lua.eval("function(t, n) for i = 1, n do table.insert(t, {kind = 'well', phase = 'dig', need = 'well'}) "
                     "end end")
    wells(full, int(B.NEED_SLOTS))
    r = B.place_well(ltab(lua, urgent=True), lua.table(), True)        # the pool full: the cap as before
    assert not r.ok and "unfinished building projects" in str(r.error), dict(r)
    assert "need = 'well'," in (LUA_DIR / "ai-builder-wells.lua").read_text(encoding="utf-8")


@test("2 brain: needs_pass marks the paper shop, a mood reserve's shops, a still while drink is short")
def _():
    s = digest.normalize(fort())
    cit = s["dwarves"]["total"]
    s["stocks"]["drink"] = 0
    s["stocks"]["prepared_meals"] = cit * 100
    props = [Proposal("paper_shop", {"type": "start_project", "kind": "workshops", "shops": ["ScrewPress"]}, "x", 6),
             Proposal("mood_reserve", {"type": "start_project", "kind": "workshops", "shops": ["Tanners"]}, "x", 5),
             Proposal("mood", {"type": "start_project", "kind": "workshops", "shops": ["Jewelers"], "mood": True}, "x", 5),
             Proposal("well", {"type": "place_well", "urgent": True}, "x", 3),
             Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Kitchen", "Still"],
                                     "added_shops": ["Kitchen"]}, "x", 4),
             Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Kitchen"]}, "x", 4),
             Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Smelter"]}, "x", 5),
             Proposal("build", {"type": "start_project", "kind": "bedrooms", "rooms": 8}, "x", 5)]
    SL.needs_pass(s, CFG, props)
    assert [p.action.get("need") for p in props] == ["paper", "mood", None, None, "drink", None, None, None], \
        [p.action.get("need") for p in props]
    s["stocks"]["drink"] = cit * 100
    s["stocks"]["prepared_meals"] = 0
    props = [Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Still"]}, "x", 4),
             Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": ["Kitchen"]}, "x", 4)]
    SL.needs_pass(s, CFG, props)
    assert [p.action.get("need") for p in props] == [None, "meals"]
    assert "_guard(needs_pass, s, cfg, proposals, memory)" in (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")


@test("2 brain: a well for every 70 waits for no ordinary slot while the needs' pool has room (r1 g3's silent return)")
def _():
    import planner_wells
    src = (ROOT / "brain" / "planner_wells.py").read_text(encoding="utf-8")
    assert src.count("not need_slots_free(s)") == 2
    s = {"projects": {"need_slots_free": 2}}
    assert planner_wells.need_slots_free(s) == 2 and SL.need_slots_free({"projects": {}}) == 0


# ---- 3. a dig that never began --------------------------------------------------------------------

F_STORAGE = {"id": 55, "kind": "storage", "phase": "dig", "started": {"year": 256, "tick": 14762},
             "dig": {"digging": 1, "dug": 0, "marked": 0, "stuck": 0, "total": 505,
                     "waiting": ["x97 y149 z164: Dig, no worker (dessource, priority 2), beside ground the dwarves "
                                 "can't reach"]}}


def dig_check(s, memory):
    props, notes = [], []
    SL._dig_check_rule(digest.normalize(s), memory, CFG, props, notes)
    return props, notes


@test("3 brain: F's storage level (0 of 505, its tile beside ground no dwarf reaches): given up at h3_dig_check_days")
def _():
    s = fort()
    s["projects"] = {"open": [copy.deepcopy(F_STORAGE)]}
    m = Memory()
    m.dig_seen = {"55": {"dug": 0, "tick": abs_tick(s) - (CFG["h3_dig_check_days"] - 1) * TICKS_PER_DAY}}
    assert not dig_check(s, m)[0]
    assert CFG["h3_dig_check_days"] < CFG["unreached_dig_days"]
    m.dig_seen["55"]["tick"] -= TICKS_PER_DAY
    props, _ = dig_check(s, m)
    assert [p.action for p in props] == [{"type": "cancel_project", "project_id": 55, "unreached": True}], props
    assert "no dwarf can reach" in props[0].reason
    # reachable, but no miner / the alarm: said, not given up
    s["projects"]["open"][0]["dig"]["waiting"] = ["x97 y149 z164: Dig, no worker (dessource, priority 2)"]
    s["labor"]["miners"] = 0
    props, notes = dig_check(s, m)
    assert not props and any("no miner" in n for n in notes), notes
    s["labor"]["miners"] = 4
    s["civ_alert"] = True
    props, notes = dig_check(s, m)
    assert not props and any("alarm keeps the miners" in n for n in notes), notes
    # something dug: not this rule's
    s["projects"]["open"][0]["dig"]["dug"] = 3
    assert dig_check(s, m) == ([], [])


@test("3 plan: the slot rules run in plan() (dig_seen filled by the dig rule first)")
def _():
    s = fort()
    lvl = copy.deepcopy(F_STORAGE)
    t = abs_tick(s) - 33 * TICKS_PER_DAY            # F: 33 days old (unreached_dig_days, 56, not yet)
    lvl["started"] = {"year": t // YEAR, "tick": t % YEAR}
    s["projects"] = {"open": [lvl], "max_open": 2, "finished": 0, "decorating": []}
    m = Memory()
    planner.plan(s, m)
    assert "55" in m.dig_seen
    m.dig_seen["55"]["tick"] = abs_tick(s) - 30 * TICKS_PER_DAY
    props, _ = planner.plan(s, m)
    assert any(p.rule == "slots" and p.action.get("type") == "cancel_project" and p.action.get("unreached")
               for p in props), [(p.rule, p.action) for p in props if p.action.get("project_id") == 55]


# ---- 4. paper -------------------------------------------------------------------------------------

def paper_fort():
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["locations"]["list"] = [{"id": 2, "type": "LIBRARY", "have": {"paper": 0}, "want": {"paper": 10},
                               "jobs": {"SCRIBE": {"filled": 1, "posts": 1}}, "zones": [70], "chests": 1,
                               "flags": ["VISITORS_ALLOWED"]}]
    s["supplies"].update(sheets=0, blank_quires=0)
    s["buildings"]["workshops"].update({"Quern": 1, "ScrewPress": 1, "Craftsdwarfs": 1, "Carpenters": 1})
    # A's paper section at the snapshot
    s["paper"] = {"bindings": 0, "codices": 1, "quires_blank": 0, "quires_written": 1, "rollers": 0, "sheets": 0,
                  "scrolls_blank": 0, "scrolls_written": 0, "thread": 10521,
                  "reactions": {"codex": {"code": "BIND_BOOK", "shops": ["Craftsdwarfs"]},
                                "papyrus": {"code": "MAKE_SHEET_FROM_PLANT", "inputs": 0, "shops": ["Farmers"]},
                                "press": {"code": "PRESS_PLANT_PAPER", "inputs": 0, "shops": ["ScrewPress"]},
                                "scroll": {"code": "MAKE_SCROLL", "shops": ["Craftsdwarfs"]},
                                "slurry": {"code": "MAKE_SLURRY_FROM_PLANT", "inputs": 40,
                                           "shops": ["Millstone", "Quern"]}}}
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in PP.PAPER_RECIPES + PP.KILN_PAPER]
    return digest.normalize(s)


@test("4 brain: A's slurry (135 orders, never pressed): the press is ordered beside it and both pass select()")
def _():
    s = paper_fort()
    props, notes = [], []
    PP._paper_rule(s, CFG, props, notes, None)
    got = [(p.rule, p.action.get("recipe"), p.action.get("amount")) for p in props]
    n = CFG["paper_batch"]
    assert got == [("paper", "make_slurry", n), ("paper_press", "press_paper", n)], got
    m = Memory()
    allowed, held = planner.select(props, s, m)
    assert {p.action.get("recipe") for p in allowed} == {"make_slurry", "press_paper"}, held
    # next cycle: the press order still waits for slurry: nothing more (one step a cycle)
    s["orders"].append({"id": 5, "recipe": "press_paper", "amount_left": n, "by_ai": True})
    props = []
    PP._paper_rule(s, CFG, props, [], None)
    assert not props


PAPER_FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_paper.py").read_text(encoding="utf-8"),
                       re.S).group(1)


@test("4 lua: a press reagent that names a REACTION_CLASS (no material product) counts the slurry")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, g = lua.execute(PAPER_FAKE, module_src("ai-paper.lua"))
    lua.execute("""
        local env, G = ...
        G.rx('MAKE_SLURRY_FROM_PLANT', {'PLANT'}, {'GLOB'}, {'Quern'}, 'PAPER_SLURRY_MAT')
        local press = G.rx('PRESS_PLANT_PAPER', {'GLOB'}, {'SHEET'}, {'SCREW_PRESS'}, '')
        press.reagents[1].reaction_class = 'PAPER_SLURRY'
        G.item('GLOB', 5, 4)            -- slurry: no material product, the class only
        G.item('GLOB', 6, 9)            -- some other glob (a paste)
        local decode = env.dfhack.matinfo.decode
        env.dfhack.matinfo.decode = function(it)
            local mi = decode(it)
            mi.material.reaction_class = it.mat == 5 and {{value = 'PAPER_SLURRY'}} or {}
            return mi
        end
    """, env, g)
    r = lua.execute("local env, G = ...; return env.report()", env, g)["reactions"]
    assert r["press"]["code"] == "PRESS_PLANT_PAPER" and r["press"]["inputs"] == 4, dict(r["press"])


finish()
