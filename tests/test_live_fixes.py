"""(0.105.30 live fixes) The forensic review of 8 Nov's live logs:

 1. E: a hidden thief (DF's invasion record, civ -1, 1 invader) was spotted
    only among the dwarves; the alarm came then and went down 635 ticks later
    with her still killing (3 citizens dead).
    a. the alarm sounds on the invasion record itself (note_intrusions,
       unseen_intrusion) and holds while nobody is seen;
    b. the half-day for a few ordinary enemies counts from the last cycle
       one was near a dwarf (few_near), not from when they came;
    c. a stranger (not of the fort's race, not a resident) seeking a meeting
       shuts the tavern, temple and library to visitors for
       stranger_shut_days, below Outsiders stranger_shut_outsiders only.
 2. dig_first never asks for a well (its tile is a channel on a floor);
    prioritize_dig refuses a channel level.
 3. disposal_melt proposes from the census' `meltable` (ai-disposal
    melt_check, mark_melt's own test), only when it is above 0.
 4. a census from before unknown_reachable (REMAINS in unknown) raises no
    Needs you.

    python tests/test_live_fixes.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import (PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick, note_cycle, plan, record)  # noqa: E402
from planner_threats import note_intrusions, unseen_intrusion  # noqa: E402
from planner_gates import few_alert_over, note_lockdown  # noqa: E402
from planner_visitors import (_location_access_rule, note_locations, stranger_shut,  # noqa: E402
                              strangers_seeking)

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
ON = {"type": "civ_alert", "on": True}
OFF = {"type": "civ_alert", "on": False}
INVASION = {"kind": "invasion", "civ_id": -1, "invaders_now": 1, "invasion_id": 0, "siege": False, "size": 0}


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["civ_alert"] = False
    s["civ_alert_ready"] = True
    s["others_on_map"] = dict(s.get("others_on_map") or {}, threats=[], threats_that_can_reach_dwarves=0)
    return s


def later(s: dict, ticks: int) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] += ticks
    return s


def alarm(props, on=True):
    return [p for p in props if p.action == (ON if on else OFF)]


# ---- 1a. the alarm on DF's invasion record ----------------------------------------------

@test("1a E: DF's invasion record of a hidden thief (nobody seen) sounds the alarm, and it is held")
def _():
    s, m = fort(), Memory()
    assert note_intrusions(s, m, [INVASION]) == 1 and m.intrusion["tick"] == abs_tick(s), m.intrusion
    note_cycle(s, m)
    p, _ = plan(s, m)
    a = alarm(p)
    assert a and "DF reports an intruder" in a[0].reason and "nobody seen yet" in a[0].reason, a
    record([(a[0], {"ok": True, "on": True})], s, m)
    assert m.ai_alert_raised
    # up, nobody seen, for several quiet cycles: it stays up (all_clear would have lowered it)
    up = later(s, 300)
    up["civ_alert"] = True
    for i in range(5):
        st = later(up, i * 50)
        note_cycle(st, m)
        p, notes = plan(st, m)
        assert not alarm(p, False), [x.reason for x in alarm(p, False)]
        assert any("DF reported an intruder" in n for n in notes), notes
    # past intrusion_alert_days: the usual quiet rules again
    over = later(up, PLANNER_CONFIG["intrusion_alert_days"] * TICKS_PER_DAY)
    assert unseen_intrusion(over, m, PLANNER_CONFIG) is None
    for i in range(4):
        note_cycle(later(over, i), m)
    assert alarm(plan(later(over, 4), m)[0], False)


@test("1a the record ends once an enemy is seen; the player lowering the AI's alarm isn't overruled")
def _():
    s, m = fort(), Memory()
    note_intrusions(s, m, [INVASION])
    seen = later(s, 100)
    seen["others_on_map"]["threats"] = [{"id": 2266, "name": "Tustong, Weasel Woman Lasher", "can_reach_dwarves": True,
                                         "distance_to_nearest_dwarf": 1, "levels_from_nearest_dwarf": 0}]
    seen["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    note_cycle(seen, m)
    assert unseen_intrusion(seen, m, PLANNER_CONFIG) is None
    a = alarm(plan(seen, m)[0])
    assert a and "1 threat(s) can reach the dwarves" in a[0].reason, a      # the usual rule has her
    # the player lowers the AI's alarm for the record: not raised again for it
    s2, m2 = fort(), Memory()
    note_intrusions(s2, m2, [INVASION])
    m2.ai_alert_raised = True
    note_cycle(later(s2, 50), m2)                   # civ_alert False: the player lowered it
    assert m2.intrusion.get("cleared") and not alarm(plan(later(s2, 60), m2)[0])
    # a new record counts again
    note_intrusions(later(s2, 100), m2, [INVASION])
    note_cycle(later(s2, 100), m2)
    assert alarm(plan(later(s2, 100), m2)[0])
    # no record, nothing seen: no alarm (as before)
    assert not alarm(plan(fort(), Memory())[0])


@test("1a the overseer keeps the records before planning")
def _():
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert "note_intrusions(state, memory, events)" in src


# ---- 1b. the half-day from the last sighting near the dwarves -----------------------------

def thief(dist: int, tick_add: int = 0) -> dict:
    s = later(fort(), tick_add)
    s["civ_alert"] = True
    s["others_on_map"]["threats"] = [{"id": 2266, "name": "Tustong, Weasel Woman Lasher", "invader": False,
                                      "can_reach_dwarves": True, "great_danger": False, "flier": False,
                                      "distance_to_nearest_dwarf": dist, "levels_from_nearest_dwarf": 0}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    return s


@test("1b E: a thief among the dwarves keeps the alarm up past half a day; far off, it comes down as before")
def _():
    half = PLANNER_CONFIG["lone_intruder_alert_ticks"]
    m = Memory(ai_alert_raised=True)
    note_cycle(thief(1), m)
    t = thief(1, half + 35)                   # E: 635 ticks on, 1 tile from the citizens
    note_cycle(t, m)
    assert not few_alert_over(t, m, PLANNER_CONFIG)
    assert not alarm(plan(t, m)[0], False)
    # gone far off (or hid) for half a day since last seen near: down
    far = thief(40, 2 * half + 40)
    note_cycle(far, m)
    assert few_alert_over(far, m, PLANNER_CONFIG)
    a = alarm(plan(far, m)[0], False)
    assert a and "half a day" in a[0].reason, a
    # B's thief, never near (18+ tiles): half a day from when it came, as 0.105.8
    m2 = Memory(ai_alert_raised=True)
    note_cycle(thief(40), m2)
    t2 = thief(40, half)
    note_cycle(t2, m2)
    assert few_alert_over(t2, m2, PLANNER_CONFIG) and alarm(plan(t2, m2)[0], False)


# ---- 1c. strangers seeking a meeting ------------------------------------------------------

BOTH = ["VISITORS_ALLOWED", "NON_CITIZENS_ALLOWED"]


def town(outsiders=0, stranger=True, heist=True) -> dict:
    s = fort()
    s["settings"]["traits"] = {"outsiders": outsiders}
    s["settings"]["heist_lockout"] = heist
    s["locations"] = {"count": {}, "total": 4, "list": [
        {"id": 0, "type": "INN_TAVERN", "flags": list(BOTH)}, {"id": 1, "type": "TEMPLE", "flags": list(BOTH)},
        {"id": 2, "type": "LIBRARY", "flags": list(BOTH)}, {"id": 4, "type": "HOSPITAL", "flags": list(BOTH)}]}
    acts = [{"actor": "Atu, Goblin Poet", "noble": "Inod, expedition leader", "visitor": True, "resident": True}]
    if stranger:
        acts.append({"actor": "Tustong, Weasel Woman Lasher", "noble": "Inod, expedition leader", "visitor": True,
                     "stranger": True})
    s["meetings"] = {"activities": acts, "requests": 0, "requests_visitors": 0, "requests_residents": 0,
                     "requests_strangers": 0}
    return s


def access(s, m, notes=None):
    props = []
    _location_access_rule(s, m, PLANNER_CONFIG, props, notes if notes is not None else [])
    return props


@test("1c a stranger seeking a meeting: tavern, temple and library shut to visitors 7 days, said in a note")
def _():
    s, m = town(), Memory()
    assert strangers_seeking(s) == ["Tustong, Weasel Woman Lasher"]
    note_locations(s, m, PLANNER_CONFIG)
    assert m.stranger_shut["seen"] == abs_tick(s), m.stranger_shut
    notes = []
    p = access(s, m, notes)
    assert len(p) == 1 and p[0].action == {"type": "location_access", "ids": [0, 1, 2], "visitors": False}, p
    assert "a stranger (Tustong" in p[0].reason and p[0].priority == 3, p[0].reason
    assert any("sought a meeting" in n and "7 more day(s)" in n for n in notes), notes
    record([(p[0], {"ok": True, "changed": [0, 1, 2]})], s, m)
    assert m.locations_closed == [0, 1, 2]
    # 7 days with no stranger: open again
    calm = later(town(stranger=False), 7 * TICKS_PER_DAY)
    for e in calm["locations"]["list"]:
        if e["id"] in (0, 1, 2):
            e["flags"] = ["NON_CITIZENS_ALLOWED"]
    calm["locations"]["built"] = abs_tick(calm)
    note_locations(calm, m, PLANNER_CONFIG)
    assert stranger_shut(calm, m, PLANNER_CONFIG) is None
    r = access(calm, m)
    assert r and r[0].action["visitors"] is True and sorted(r[0].action["ids"]) == [0, 1, 2], r
    assert "no stranger sought a meeting" in r[0].reason, r[0].reason


@test("1c not at Outsiders 50+ (the Merchant city), not with the Rules switch off, not for residents or kin")
def _():
    for s in (town(outsiders=50), town(outsiders=100), town(heist=False), town(stranger=False)):
        m = Memory()
        note_locations(s, m, PLANNER_CONFIG)
        assert not access(s, m), (s["settings"]["traits"], s["meetings"])
    # waiting strangers (meeting_requests) count too
    s = town(stranger=False)
    s["meetings"].update(requests=2, requests_visitors=2, requests_strangers=2, strangers=["Ngom, Elf Dancer"])
    assert strangers_seeking(s) == ["Ngom, Elf Dancer", "a stranger"]
    m = Memory()
    note_locations(s, m, PLANNER_CONFIG)
    assert access(s, m)


@test("1c a place the player opened again is never shut by the AI for a stranger")
def _():
    s, m = town(), Memory(locations_yours=[1])
    note_locations(s, m, PLANNER_CONFIG)
    p = access(s, m)
    assert p and p[0].action["ids"] == [0, 2], p


@test("1c the bridge: a stranger in a meeting is marked; waiting strangers counted and named")
def _():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        return
    import ast
    src = (ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8")
    harness = next(n.value.value for n in ast.parse(src).body if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", None) == "HARNESS")
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(harness, (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    M = H.module()
    lua.execute("""local M, df, dfhack = ...
        local units = {[1] = {id = 1, cit = true, race = 7}, [2] = {id = 2, race = 9},
                       [3] = {id = 3, res = true, race = 9}, [4] = {id = 4, race = 7}, [5] = {id = 5, race = 9}}
        df.unit = {find = function(id) return units[id] end}
        df.global.plotinfo.race_id = 7
        dfhack.units = dfhack.units or {}
        dfhack.units.isCitizen = function(u) return u.cit == true end
        dfhack.units.isResident = function(u) return u.res == true end
        dfhack.units.getReadableName = function(u) return 'u' .. u.id end
        df.global.plotinfo.activities = {{unit_actor = 2, unit_noble = 1, flags = {}},
                                         {unit_actor = 3, unit_noble = 1, flags = {}},
                                         {unit_actor = 4, unit_noble = 1, flags = {}}}
        df.global.plotinfo.dip_meeting_info = {}
        df.global.plotinfo.meeting_requests = {1, 3, 4, 5}
        df.global.plotinfo.dipscript_popups = {}""", M, H.df, H.dfhack)
    r = M.get_meetings()
    a, b, c = r.activities[1], r.activities[2], r.activities[3]
    assert a.stranger and not b.stranger and not c.stranger, (dict(a), dict(b), dict(c))
    assert r.requests_strangers == 1 and len(list(r.strangers.values())) == 1, (r.requests_strangers, r.strangers)


# ---- 2. dig_first and wells -----------------------------------------------------------------

def dig_fort(kind: str) -> tuple[dict, Memory]:
    s = fort()
    s["projects"] = dict(s.get("projects") or {}, open=[{"id": 5, "kind": kind, "phase": "dig", "urgent": True,
                                                         "dig": {"total": 1, "dug": 0, "digging": 0}}])
    m = Memory()
    m.dig_seen = {"5": {"dug": 0, "tick": abs_tick(s) - 20 * TICKS_PER_DAY}}
    return s, m


@test("2 dig_first: never a well level ('0 of 1 tiles dug', its channel); other levels still raised")
def _():
    from planner_building import _dig_stall_rule
    for kind, want in (("well", False), ("hospital", True), ("bedrooms", True)):
        s, m = dig_fort(kind)
        props = []
        _dig_stall_rule(s, m, PLANNER_CONFIG, s["projects"]["open"], props)
        got = [p for p in props if p.rule == "dig_first"]
        assert bool(got) == want, (kind, props)


@test("2 the bridge: prioritize_project refuses a channel level (a well's hole)")
def _():
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    i = src.index("function prioritize_project")
    body = src[i:i + 2500]
    assert "p.dig_done == 'open'" in body and "rejected = true" in body.split("p.dig_done == 'open'")[1][:200]


# ---- 3. disposal_melt from `meltable` -----------------------------------------------------

@test("3 ai-disposal: meltable counts what mark_melt marks (one test, melt_check), the enemy's kept apart")
def _():
    try:
        import test_disposal_actions as A
    except SystemExit:
        return
    if not A.need_lua():
        return
    lua, env, w = A.world()
    mk = A.mk
    mk(lua, w, kind="WEAPON", metal=True, wear=1, flags={"forbid": True, "dead_dwarf": True})     # worn: yes
    mk(lua, w, kind="CORPSE", race=2, flags={"forbid": True}, pos=(20, 20, 130))
    mk(lua, w, kind="ARMOR", metal=True, flags={"forbid": True}, pos=(20, 20, 130))               # enemy's
    mk(lua, w, kind="WEAPON", metal=True, wear=2, quality=5, flags={"forbid": True, "dead_dwarf": True})
    for _ in range(18):                                                   # E's "18 metal items lie forbidden"
        mk(lua, w, kind="WEAPON", metal=True, flags={"forbid": True, "dead_dwarf": True})
    r = env.meltable()
    assert r.n == 2 and r.keep_enemy == 1, dict(r)
    dry = env.mark_melt(A.opts(lua), True)
    assert dry.n == r.n, (dict(dry), dict(r))
    dry2 = env.mark_melt(A.opts(lua, keep_enemy_gear=True), True)
    assert dry2.n == r.keep_enemy, dict(dry2)
    # nothing meltable: 0 (the brain asks nothing; the bridge would refuse)
    lua2, env2, w2 = A.world()
    for _ in range(18):
        mk(lua2, w2, kind="WEAPON", metal=True, flags={"forbid": True, "dead_dwarf": True})
    assert env2.meltable().n == 0
    assert env2.mark_melt(A.opts(lua2), False).rejected


@test("3 ai-census: items.forbidden.meltable from ai-disposal's meltable (absent without it)")
def _():
    try:
        import test_disposal_census as C
    except SystemExit:
        return
    lua, env = C.world()
    assert C.forbidden(env).meltable is None
    lua.execute("""local env = ...
        local old = env.reqscript
        env.reqscript = function(n)
            if n == 'ai-disposal' then return {meltable = function() return {n = 3, keep_enemy = 1} end} end
            return old(n)
        end""", env)
    fb = C.forbidden(env)
    assert fb.meltable == 3 and fb.meltable_keep_enemy == 1, (fb.meltable, fb.meltable_keep_enemy)


def melt_state(meltable, keep=None):
    import test_disposal_brain as BR
    s, m = BR.state()
    fb = m.census["items"]["forbidden"]
    fb["metal"] = 18
    if meltable is not None:
        fb["meltable"] = meltable
        fb["meltable_keep_enemy"] = meltable if keep is None else keep
    return BR, s, m


@test("3 brain: no disposal_melt when nothing is meltable (18 forbidden metal items); one when some is")
def _():
    BR, s, m = melt_state(0)
    got, _ = BR.run(s, m)
    assert "disposal_melt" not in got, sorted(got)
    BR, s, m = melt_state(2)
    got, _ = BR.run(s, m)
    assert "disposal_melt" in got and got["disposal_melt"].reason.startswith("2 worn or enemy metal items"), got
    # keep_enemy_gear on: its own count
    BR, s, m = melt_state(2, keep=0)
    s["settings"]["keep_enemy_gear"] = True
    got, _ = BR.run(s, m)
    assert "disposal_melt" not in got, sorted(got)
    # an older census (no meltable): as before, the forbidden-metal count
    BR, s, m = melt_state(None)
    got, _ = BR.run(s, m)
    assert "disposal_melt" in got and "18 metal items lie forbidden" in got["disposal_melt"].reason


# ---- 4. the unknown-items note ---------------------------------------------------------------

@test("4 E/F: 0.105.27's census (410 REMAINS read unknown, no unknown_reachable): no Needs you; 0.105.28's: on its field")
def _():
    import test_disposal_brain as BR
    s, m = BR.state()
    fb = m.census["items"]["forbidden"]
    fb.update(total=410, by_type={"REMAINS": 410}, corpses={"own": 0, "other": 0})
    fb["by_reason"]["unknown"] = 410
    _, notes = BR.run(s, m)
    assert not [n for n in notes if n.startswith("[you] ") and "no reason the game gives" in n], notes
    fb.update(unknown_reachable=250, unknown_where={"surface": 250, "inside": 0})
    _, notes = BR.run(s, m)
    assert [n for n in notes if "250 items lie forbidden on the surface (250)" in n], notes


if __name__ == "__main__":
    finish()
