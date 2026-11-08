"""(0.105.26 fix round, visitors) Places shut to visitors: a shut is never
taken for the player's doing on a stale (cached) locations report; the heist
lockout is short in a welcoming fort; the swamped-mayor shut waits for new
complaints after a reopen and counts only true visitors; plan() changes no
memory (the mayor's rest and the reopen's mark are kept by record()).

    python tests/test_fix26_visitors.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import (PLANNER_CONFIG, TICKS_PER_DAY, Memory, Proposal, abs_tick, note_cycle,  # noqa: E402
                     plan, record)
from planner_society import (_location_access_rule, heist_lockout, heist_lockout_days, mayor_meetings,  # noqa: E402
                             note_heists, note_locations, visitor_shut)

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
BOTH = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]
SHUT = ["NON_CITIZENS_ALLOWED"]
HEIST = {"kind": "report", "topic": "thief", "text": "The Goblin Thief Snodub was spotted "
         "sneaking around!  \"You will not stand between me and Bluegold!\""}


def fort(outsiders=0) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["locations"] = {"count": {}, "total": 2, "list": [{"id": 1, "type": "INN_TAVERN", "flags": list(BOTH)},
                                                         {"id": 3, "type": "TEMPLE", "flags": list(BOTH)}]}
    s["settings"]["traits"] = {"outsiders": outsiders}
    return s


def swamped(unheard=9, outsiders=60, residents=0) -> dict:
    s = fort(outsiders)
    s["needs"] = dict(s.get("needs") or {}, stress_causes={"days": 28, "causes": [
        {"thought": "UnableComplain", "citizens": unheard}]})
    s["offices"] = {"offices": {"MAYOR": {"held": ["Oddom Nomaluker"]}}}
    s["meetings"] = {"activities": [{"actor": "Mosus, Poet", "noble": "Oddom Nomaluker, mayor", "visitor": True}],
                     "requests": 3, "requests_visitors": 2, "requests_residents": residents}
    return s


def rule(s, m, notes=None):
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, notes if notes is not None else [])
    return props


def set_flags(s, ids, flags):
    for e in s["locations"]["list"]:
        if e["id"] in ids:
            e["flags"] = list(flags)


def later(s, days):
    s = copy.deepcopy(s)
    s["date"]["tick"] += days * TICKS_PER_DAY
    return s


# ---- 1. the stale locations report ---------------------------------------

@test("1 the bridge: location_access clears the cached locations section; the section says when it was built")
def _():
    try:
        from lupa import LuaRuntime
    except ImportError:
        return
    src = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")
    harness = next(n.value.value for n in ast.parse(src).body if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", None) == "HARNESS")
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(harness, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    M = H.module()
    inv = M.CACHE_INVALIDATES.location_access
    assert inv is not None and list(inv.values()) == ["locations"], inv
    lua.execute("""local M, df, dfhack = ...
        dfhack.world.getCurrentSite = function() return {buildings = {}} end""", M, H.df, H.dfhack)
    r = M.get_locations()
    assert r.built == 150 * 403200 + 1000, r.built
    # the mayor's meetings: a resident (lives here, not a citizen) marked apart from visitors
    lua.execute("""local M, df, dfhack = ...
        local units = {[1] = {id = 1, cit = true}, [2] = {id = 2}, [3] = {id = 3, res = true}, [4] = {id = 4, res = true}}
        df.unit = {find = function(id) return units[id] end}
        dfhack.units = dfhack.units or {}
        dfhack.units.isCitizen = function(u) return u.cit == true end
        dfhack.units.isResident = function(u) return u.res == true end
        dfhack.units.getReadableName = function(u) return 'u' .. u.id end
        M.unit_word = function(id) return 'u' .. tostring(id) end
        df.global.plotinfo.activities = {{unit_actor = 2, unit_noble = 1, flags = {}}, {unit_actor = 3, unit_noble = 1, flags = {}}}
        df.global.plotinfo.dip_meeting_info = {}
        df.global.plotinfo.meeting_requests = {1, 2, 4, 4}
        df.global.plotinfo.dipscript_popups = {}""", M, H.df, H.dfhack)
    r = M.get_meetings()
    a, b = r.activities[1], r.activities[2]
    assert a.visitor and not a.resident and b.visitor and b.resident, (dict(a), dict(b))
    assert r.requests_visitors == 3 and r.requests_residents == 2, (r.requests_visitors, r.requests_residents)


@test("1 a shut read open in a stale report (no `built`, same days) is not the player's: not yours, not shut again")
def _():
    s = fort(-150)
    m = Memory()
    p = rule(s, m)
    assert len(p) == 1 and p[0].action["ids"] == [1, 3] and p[0].action["visitors"] is False, p
    record([(p[0], {"ok": True, "changed": [1, 3]})], s, m)
    # the next cycle reads the cached section: still "open"
    for st in (s, later(s, 1)):
        note_locations(st, m, PLANNER_CONFIG)
        assert m.locations_closed == [1, 3] and m.locations_yours == [], (m.locations_closed, m.locations_yours)
        assert rule(st, m) == []
    # a report built before (or at) the shut is stale whatever the age
    old = later(s, 9)
    old["locations"]["built"] = abs_tick(s)
    note_locations(old, m, PLANNER_CONFIG)
    assert m.locations_yours == [] and rule(old, m) == []
    # one built since that reads open: the player opened it, theirs
    fresh = later(s, 1)
    fresh["locations"]["built"] = abs_tick(fresh)
    set_flags(fresh, [1], SHUT)
    note_locations(fresh, m, PLANNER_CONFIG)
    assert m.locations_closed == [1] and m.locations_yours == [3], (m.locations_closed, m.locations_yours)
    # no `built` (an older bridge) and past location_stale_days: yours too
    m2 = Memory(locations_closed=[1, 3], locations_acted={"1": abs_tick(s), "3": abs_tick(s)})
    note_locations(later(s, 5), m2, PLANNER_CONFIG)
    assert m2.locations_yours == [1, 3], m2.locations_yours


@test("1 the reviewer's case end to end: a heist lockout shuts, cached reports follow, and the places reopen")
def _():
    s = fort(0)
    m = Memory()
    assert note_heists(s, m, [HEIST]) == 1
    p = [x for x in plan(s, m)[0] if x.rule == "location_access"]
    assert len(p) == 1 and p[0].action["visitors"] is False, p
    record([(p[0], {"ok": True, "changed": [1, 3]})], s, m)
    for day in (0, 1, 2):                                        # the stale "open" for two days
        st = later(s, day)
        note_cycle(st, m)
        assert not [x for x in plan(st, m)[0] if x.rule == "location_access"]
    assert m.locations_closed == [1, 3] and not m.locations_yours, (m.locations_closed, m.locations_yours)
    st = later(s, 3)                                             # rebuilt: shut
    st["locations"]["built"] = abs_tick(st)
    set_flags(st, [1, 3], SHUT)
    note_cycle(st, m)
    st = later(st, 170)                                          # the lockout over: reopened
    note_cycle(st, m)
    p = [x for x in plan(st, m)[0] if x.rule == "location_access"]
    assert len(p) == 1 and p[0].action["visitors"] is True and p[0].action["ids"] == [1, 3], p


# ---- 2. the heist lockout in a welcoming fort -------------------------------

@test("2 heist lockout: 28 days at Outsiders 100 or more (the Merchant city), 168 elsewhere; the switch as before")
def _():
    assert heist_lockout_days(fort(100), PLANNER_CONFIG) == 28
    assert heist_lockout_days(fort(150), PLANNER_CONFIG) == 28
    assert heist_lockout_days(fort(99), PLANNER_CONFIG) == 168
    assert heist_lockout_days(fort(100), dict(PLANNER_CONFIG, heist_lockout_days=0)) == 0
    s = fort(100)
    m = Memory()
    note_heists(s, m, [HEIST])
    p = rule(s, m)
    assert p and "28 more day" in p[0].reason, p
    assert heist_lockout(later(s, 27), m, PLANNER_CONFIG) and heist_lockout(later(s, 29), m, PLANNER_CONFIG) is None
    record([(p[0], {"ok": True, "changed": [1, 3]})], s, m)
    st = later(s, 29)
    set_flags(st, [1, 3], SHUT)
    p = rule(st, m)
    assert p and p[0].action["visitors"] is True and "no heist for 28 days" in p[0].reason, p
    m2 = Memory()
    s99 = fort(99)
    note_heists(s99, m2, [HEIST])
    assert heist_lockout(later(s99, 100), m2, PLANNER_CONFIG)
    off = fort(100)
    off["settings"]["heist_lockout"] = False
    assert heist_lockout(off, m, PLANNER_CONFIG) is None


# ---- 3. the swamped mayor ----------------------------------------------------

@test("3 the swamped-mayor shut: not again right after a reopen; again for new complaints or once the census moved on")
def _():
    s = swamped()
    m = Memory()
    p = rule(s, m)
    assert len(p) == 1 and p[0].action["visitors"] is False, p
    record([(p[0], {"ok": True, "changed": [1, 3]})], s, m)
    st = later(s, 57)
    set_flags(st, [1, 3], SHUT)
    p = rule(st, m)
    assert p and p[0].action["visitors"] is True, p
    record([(p[0], {"ok": True, "changed": [1, 3]})], st, m)
    assert m.visitor_shut.get("reopened") == abs_tick(st) and m.visitor_shut.get("unheard_at") == 9, m.visitor_shut
    set_flags(st, [1, 3], BOTH)
    st["locations"]["built"] = abs_tick(st) + 1
    note_locations(st, m, PLANNER_CONFIG)
    assert rule(st, m) == [] and visitor_shut(st, m, PLANNER_CONFIG) is None        # the old complaints: no
    more = copy.deepcopy(st)
    more["needs"]["stress_causes"]["causes"][0]["citizens"] = 13
    assert rule(more, m) == []                                                      # 4 new: still too few
    more["needs"]["stress_causes"]["causes"][0]["citizens"] = 14
    p = rule(more, m)
    assert p and p[0].action["visitors"] is False, p                                # 5 new
    gone = later(st, 29)                                                            # the census's 28 days past
    gone["locations"]["built"] = abs_tick(gone)
    p = rule(gone, m)
    assert p and p[0].action["visitors"] is False, p


@test("3 the swamped-mayor shut: residents meeting the mayor aren't visitors")
def _():
    s = swamped(residents=2)            # 3 visitors of 4 meetings, 2 of them residents: 1 true visitor
    acts, waiting, vis = mayor_meetings(s, "Oddom")
    assert vis == 1 and waiting == 3, (vis, waiting)
    assert rule(s, Memory()) == [] and visitor_shut(s, Memory(), PLANNER_CONFIG) is None
    s["meetings"]["activities"][0]["resident"] = True
    s["meetings"]["requests_residents"] = 0
    assert mayor_meetings(s, "Oddom")[2] == 2
    assert mayor_meetings(swamped(), "Oddom")[2] == 3                     # no resident flags: as before


# ---- 4. plan() changes no memory ----------------------------------------------

@test("4 plan() changes no memory: the mayor's rest kept by record() only when the shut went through")
def _():
    s = swamped()
    m = Memory()
    before = json.dumps(m.to_dict(), sort_keys=True, default=str)
    p = rule(s, m)
    assert json.dumps(m.to_dict(), sort_keys=True, default=str) == before
    assert p and p[0].action["visitor_shut"]["until"] - p[0].action["visitor_shut"]["tick"] == 56 * TICKS_PER_DAY
    assert m.visitor_shut == {}
    # held back (a cooldown, the limit, the halt) or refused: no clock
    record([(p[0], {"ok": False, "error": "nothing to change"})], s, m)
    assert m.visitor_shut == {}
    st = later(s, 30)                       # still swamped: a new rest from now, not from 30 days ago
    p = rule(st, m)
    assert p and p[0].action["visitor_shut"]["tick"] == abs_tick(st), p
    record([(p[0], {"ok": True, "changed": [1, 3]})], st, m)
    assert m.visitor_shut["tick"] == abs_tick(st) and m.visitor_shut["until"] == abs_tick(st) + 56 * TICKS_PER_DAY
    # the reopen: plan() leaves the rest alone; record() keeps the reopen's mark
    end = later(st, 57)
    set_flags(end, [1, 3], SHUT)
    snap = json.dumps(m.to_dict(), sort_keys=True, default=str)
    p = rule(end, m)
    assert json.dumps(m.to_dict(), sort_keys=True, default=str) == snap and p and p[0].action["visitors"] is True
    record([(p[0], {"ok": False, "error": "x"})], end, m)
    assert "until" in m.visitor_shut
    record([(p[0], {"ok": True, "changed": [1, 3]})], end, m)
    assert m.visitor_shut == {"reopened": abs_tick(end), "unheard_at": 9}, m.visitor_shut
    # the whole plan() too, with the stale "yours" and a rest over with nothing held
    m3 = Memory(locations_closed=[1], visitor_shut={"tick": 0, "until": 1})
    s3 = fort(-150)
    s3["locations"]["built"] = abs_tick(s3)
    snap = json.dumps(m3.to_dict(), sort_keys=True, default=str)
    plan(s3, m3)
    assert json.dumps(m3.to_dict(), sort_keys=True, default=str) == snap


if __name__ == "__main__":
    finish()
