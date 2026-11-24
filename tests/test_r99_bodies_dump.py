"""(0.105.99) Bodies hauled to the dump or buried instead of lying around (fort B).

Live 24 Nov 00:35, B: 135 items marked for the garbage dump (89 of them
under the sky: the dead birds by the gate, a visitor's body), none in the
dump; DF's standing order "gather refuse from outside" off, 77 refuse
haulers and not one DumpItem job (DF dumps nothing lying outside while that
order is off). burial_others refused 44 times in 2 hours: the one body it
counted was a visiting marksdwarf of civ 272 whose body carries DF's
dead_dwarf flag, which the action kept as the fort's own remains. Two
ghosts' bodies lay forbidden on a barracks floor in reach while 6 drowned
lay unforbidden under water: the burial rule's "forbidden less unreachable"
(2 - 6) never unforbade them.

    python tests/test_r99_bodies_dump.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_part_src, split_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import player_rules  # noqa: E402
from planner_industry import _disposal_rules  # noqa: E402
import planner_welfare as W  # noqa: E402
import planner_society as PS  # noqa: E402

CFG = PLANNER_CONFIG
LUA = ROOT / "lua"
DISPOSAL = (LUA / "ai-disposal.lua").read_text(encoding="utf-8")
REPORT = bridge_part_src("ai-bridge-report")
ACTS = bridge_part_src("ai-bridge-actions")
UTIL = split_src("ai-util.lua")

B_DISPOSAL = {"dump_zones": [{"id": 228, "inside": False, "items": 0, "x": 100, "y": 158, "z": 170}],
              "dumped_items": 0, "marked_dump": 135, "marked_dump_outside": 89, "marked_melt": 0,
              "invaders": 0, "siege": False, "smelters": 1, "magma_smelters": 0, "sealed_caverns": 0}
B_WHY = {"carried": 0, "dump": 0, "forbidden": 2, "free": 1, "in_job": 0, "not_ours": 1, "not_ours_loose": 1,
         "outside": 3, "unreachable": 6}
B_STANDING = {"forbid_own_dead": 0, "forbid_other_dead_items": 1, "forbid_used_ammo": 1, "gather_refuse": 1,
              "gather_refuse_outside": 0}


def st(why=None, disposal=None, **dead):
    d = {"free_tombs": 7, "unburied": 10, "why": dict(B_WHY, **(why or {})), "standing": dict(B_STANDING),
         "ghosts": 0}
    d.update(dead)
    return {"settings": {"traits": {}, "fort_goal": "expand"}, "dwarves": {"total": 60},
            "date": {"year": 264, "tick": 300000}, "dead": d, "welfare": {},
            "disposal": copy.deepcopy(disposal if disposal is not None else B_DISPOSAL),
            "projects": {"open": []}, "orders": [], "_errors": {},
            "buildings": {"workshops": {"Masons": 1}}, "stocks": {}, "supplies": {}}


def welfare(s):
    props, notes = [], []
    W._welfare_rules(s, CFG, props, notes, Memory(), {})
    return [p for p in props if p.rule == "burial_others"], notes


def disposal(s, m=None):
    props, notes = [], []
    _disposal_rules(s, dict(CFG), props, notes, m or Memory(), player_rules(s))
    return {p.rule: p for p in props}, notes


# --- burial_others: asks only for what the dump may take ---------------------------------

@test("burial_others: B's one visitor body kept by the action (not_ours_kept): no proposal, a note saying why")
def _():
    o, notes = welfare(st({"not_ours_kept": 1}))
    assert not o, o
    n = [x for x in notes if "dead of other civs" in x]
    assert n and "none can go to the dump now" in n[0] and "kept as the fort's own remains" in n[0], notes


@test("burial_others: the loose ones out of reach (or already marked) are said, nothing asked")
def _():
    o, notes = welfare(st({"not_ours": 3, "not_ours_loose": 1, "not_ours_unreachable": 1}))
    assert not o
    n = [x for x in notes if "dead of other civs" in x][0]
    assert "1 where the dwarves can't walk" in n and "2 more already marked or in the dump" in n, n


@test("burial_others: one the dump may take and the dwarves reach: marked for the dump outside (the count said)")
def _():
    o, _ = welfare(st({"not_ours_dumpable": 1}))
    assert len(o) == 1 and o[0].action["type"] == "mark_dump" and o[0].action["bodies"] is True, o
    assert o[0].reason.startswith("1 dead of other civs") and "where the dwarves can reach" in o[0].reason


@test("burial_others: an older bridge (none of the new counts): asked as before")
def _():
    o, _ = welfare(st())
    assert len(o) == 1 and o[0].action["type"] == "mark_dump", o


# --- gather refuse from outside ---------------------------------------------------------

@test("disposal_outside: B's 89 marked items outside with the order off: the order switched on")
def _():
    got, _ = disposal(st())
    p = got.get("disposal_outside")
    assert p and p.action == {"type": "set_standing_orders", "orders": {"gather_refuse_outside": 1}}, got.keys()
    assert "89 items marked" in p.reason


@test("disposal_outside: none with no marked item outside, with the order on, with no dump zone, or in a siege")
def _():
    assert "disposal_outside" not in disposal(st(disposal=dict(B_DISPOSAL, marked_dump_outside=0)))[0]
    assert "disposal_outside" not in disposal(st(disposal={k: v for k, v in B_DISPOSAL.items()
                                                           if k != "marked_dump_outside"}))[0]
    s = st()
    s["dead"]["standing"]["gather_refuse_outside"] = 1
    assert "disposal_outside" not in disposal(s)[0]
    assert "disposal_outside" not in disposal(st(disposal=dict(B_DISPOSAL, dump_zones=[])))[0]
    assert "disposal_outside" not in disposal(st(disposal=dict(B_DISPOSAL, siege=True)))[0]


@test("disposal_outside: set by the AI, off again later: left as the player set it (a note), within the month nothing")
def _():
    from planner_core import abs_tick
    s = st()
    m = Memory()
    m.last_fired["disposal_outside"] = abs_tick(s) - 2 * CFG["disposal_outside_cooldown_ticks"]
    got, notes = disposal(s, m)
    assert "disposal_outside" not in got and any("left as you set it" in n and "from outside" in n for n in notes)
    m.last_fired["disposal_outside"] = abs_tick(s) - 10
    got, notes = disposal(s, m)
    assert "disposal_outside" not in got and not any("from outside is off again" in n for n in notes)



@test("(merge) disposal_outside waits while a danger can reach the dwarves; the AI's own switch goes back off")
def _():
    from planner_core import abs_tick
    s = st()
    s["others_on_map"] = {"threats": [], "threats_that_can_reach_dwarves": 2}
    got, notes = disposal(s)
    assert "disposal_outside" not in got and any("wait for the danger" in n for n in notes), (got.keys(), notes)
    # on by the AI, then a danger: off
    s["dead"]["standing"]["gather_refuse_outside"] = 1
    m = Memory()
    m.last_fired["disposal_outside"] = abs_tick(s) - 100
    got, _ = disposal(s, m)
    p = got.get("disposal_outside_off")
    assert p and p.action["orders"] == {"gather_refuse_outside": 0}, got.keys()
    # on by the AI, nothing outside any more: off
    s2 = st(disposal=dict(B_DISPOSAL, marked_dump_outside=0))
    s2["dead"]["standing"]["gather_refuse_outside"] = 1
    assert "disposal_outside_off" in disposal(s2, m)[0]
    # on by the player (never by the AI): left alone
    assert "disposal_outside_off" not in disposal(s2)[0]
    # the AI set it off itself: it may switch it on again when it is clear
    m.last_fired["disposal_outside_off"] = abs_tick(s) - 50
    assert "disposal_outside" not in disposal(st(), m)[0]          # two days clear first
    m.last_fired["disposal_outside"] = abs_tick(s) - 5 * 1200     # on 5 days ago, off 3 days ago
    m.last_fired["disposal_outside_off"] = abs_tick(s) - 3 * 1200
    assert "disposal_outside" in disposal(st(), m)[0]

@test("disposal_outside is a known rule: a hold class and its own cooldown")
def _():
    from hold_classes import RULE_CLASS
    assert "disposal_outside" in RULE_CLASS
    assert CFG["disposal_outside_cooldown_ticks"] == 28 * 1200


# --- the fort's own forbidden dead in reach -----------------------------------------------

def dead_notes(s):
    props, notes = [], []
    PS._dead_notes(s, notes, props, {"engrave_slabs": True}, Memory())
    return [p for p in props if p.rule == "burial"], notes


@test("burial: B's 2 ghosts' bodies forbidden in reach while 6 others lie unforbidden under water: unforbidden")
def _():
    o, notes = dead_notes(st({"forbidden_reach": 2, "in_water": 6}))
    u = [p for p in o if p.action.get("type") == "unforbid_dead"]
    assert u and u[0].reason.startswith("2 of the fort's 10 unburied dead lie forbidden"), o
    n = [x for x in notes if "can't walk" in x][0]
    assert "6 of them under water: left where they lie" in n, n


@test("burial: no forbidden body in reach (forbidden_reach 0): nothing unforbidden; an older bridge keeps the old sum")
def _():
    o, _ = dead_notes(st({"forbidden_reach": 0}))
    assert not [p for p in o if p.action.get("type") == "unforbid_dead"]
    o, _ = dead_notes(st())          # 2 - 6: as before, nothing
    assert not [p for p in o if p.action.get("type") == "unforbid_dead"]
    o, _ = dead_notes(st({"unreachable": 0}))
    assert [p for p in o if p.action.get("type") == "unforbid_dead"]


# --- the bridge -------------------------------------------------------------------------

@test("bridge: the dead report counts by the action's own test (dumpable_other_body), reach and the forbidden in reach")
def _():
    assert "side_ctx.U.dumpable_other_body(it, 'CORPSE', side_ctx)" in REPORT
    for k in ("why.not_ours_dumpable", "why.not_ours_unreachable", "why.not_ours_kept", "why.forbidden_reach",
              "why.in_water"):
        assert k in REPORT, k
    assert "if not U.dumpable_other_body(it, kind, ctx) then return end" in DISPOSAL
    assert "function dumpable_other_body(it, kind, ctx)" in UTIL
    assert "out.marked_dump_outside = out.marked_dump_outside + 1" in DISPOSAL


@test("bridge: unforbid_dead leaves a body by a live danger or on the cistern's tiles forbidden, and says so")
def _():
    i = ACTS.index("function act_unforbid_dead(a)")
    body = ACTS[i:ACTS.index("\nend\n", i)]
    assert "U.danger_spots(), U.cistern_tiles()" in body and "near_danger(spots, x, y, z)" in body
    assert "left forbidden" in body


@test("bridge: Lua files stay under 60 KB")
def _():
    for f in ("ai-disposal.lua", "ai-util.lua", "ai-bridge-report-supplies.lua", "ai-bridge-actions.lua"):
        assert (LUA / f).stat().st_size < 60 * 1024, f


@test("lua: dumpable_other_body: a visitor's dwarf body with DF's dead_dwarf flag goes; a citizen's, or one of the fort's civ, stays")
def _():
    need_lua()
    import test_k48_dead_unhappy as K
    lua, env = K.util_env()
    ctx = env.forbid_context()
    fl = lambda: lua.table_from({"forbid": False, "on_ground": True, "dead_dwarf": True})  # noqa: E731
    assert env.dumpable_other_body(env.item("CORPSE", 1, 12, -1, fl()), "CORPSE", ctx)      # visitor, civ 9
    assert not env.dumpable_other_body(env.item("CORPSE", 1, 11, -1, fl()), "CORPSE", ctx)  # a citizen
    assert not env.dumpable_other_body(env.item("CORPSE", 1, 15, -1, fl()), "CORPSE", ctx)  # fort's civ, no record
    assert env.dumpable_other_body(env.item("CORPSE", 1, 13, -1, fl()), "CORPSE", ctx)      # own civ's merchant
    assert env.dumpable_other_body(env.item("CORPSE", 1, 12), "CORPSE", ctx)                # no flag: as before
    assert not env.dumpable_other_body(env.item("CORPSE", 3, 99), "CORPSE", ctx)            # an animal's


@test("lua: mark_dump bodies takes B's visitor body with the dead_dwarf flag")
def _():
    need_lua()
    import test_k48_dead_unhappy as K
    A, lua, env, w = K.disposal_world()
    v = A.mk(lua, w, kind="CORPSE", race=1, unit_id=6, flags={"dead_dwarf": True}, pos=(70, 70, 130))
    c = A.mk(lua, w, kind="CORPSE", race=1, unit_id=5, flags={"dead_dwarf": True}, pos=(71, 70, 130))
    r = env.mark_dump(A.opts(lua, bodies=True, junk=False, reasons=["free", "other_dead"], max=50), False)
    assert r.ok and v.flags.dump and not c.flags.dump, (r.ok, A.skipped(r), r.error)


if __name__ == "__main__":
    finish()
