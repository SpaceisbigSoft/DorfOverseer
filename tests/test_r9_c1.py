"""(r9 c1) The Garden fort's garden court: a meeting area only while no danger
is about, and only once it is secured. The player (21 Nov, 23:24).

1. the brain (planner_garden._court_meeting_rule): the meeting area off under
   each of the fort's danger signals, its door locked; on again only once no
   danger has been read for garden_court_lift_ticks (no flapping); never on
   while the court isn't secured; a plain court says why;
2. the Lua (ai-builder-court): the 'secure' stage before the zone; no
   meeting area while unsecured; a court that can't be secured stays a plain
   garden with its why; an older save past the zone gets 'secure' and its
   area off; the court's door never locked with a citizen inside or a way
   into the fort inside it;
3. the wiring: the action, its dry run, label, classes, the DF field.

    python tests/test_r9_c1.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import make_test, finish  # noqa: E402
from lua_modules_util import bridge_hub_src  # noqa: E402

import planner_garden as G  # noqa: E402
from planner import Memory, PLANNER_CONFIG  # noqa: E402
from planner_core import TICKS_PER_YEAR, EMERGENCY  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

test = make_test()
CFG = PLANNER_CONFIG
GARDEN = {"agriculture": 120, "grandeur": 40, "surface": 80}
LIFT = CFG["garden_court_lift_ticks"]

ON = {"stage": "done", "done": True, "secured": True, "zoned": True, "meeting_on": True, "door_built": True,
      "locked": False, "lockable": True, "inside": 0}


def state(tick=0, **kw) -> dict:
    s = {"dwarves": {"total": 40}, "date": {"year": 160, "tick": tick}, "stocks": {"blocks": 80},
         "others_on_map": {"threats": []}, "settings": {}, "buildings": {}, "garden_court": dict(ON)}
    s.update(kw)
    return s


def now_of(s) -> int:
    return s["date"]["year"] * TICKS_PER_YEAR + s["date"]["tick"]


def run(s, m) -> tuple[list, list]:
    props, notes = [], []
    G._garden_court_rule(s, CFG, 40, GARDEN, props, notes, m, {})
    return [p for p in props if p.rule == "court_meeting"], notes


# --- 1. the brain -------------------------------------------------------------------------------

def dangers():
    """(name, state, memory) for each of the fort's danger signals."""
    out = []
    out.append(("threats that can reach the dwarves",
                state(others_on_map={"threats": [{"id": 7, "can_reach_dwarves": True}]}), Memory()))
    out.append(("an enemy (invader)", state(others_on_map={"threats": [{"id": 8, "invader": True,
                                                                       "can_reach_dwarves": False}]}), Memory()))
    out.append(("a siege held off", state(others_on_map={"threats": [{"id": 9, "layer": "upper_levels",
                                                                     "kinds": ["Beast"], "can_reach_dwarves": False}]}),
                Memory()))
    out.append(("a great danger", state(others_on_map={"threats": [{"id": 10, "great_danger": True,
                                                                   "layer": "upper_levels"}]}), Memory()))
    out.append(("the gates watched", state(entrances={"armed": True}), Memory()))
    out.append(("the alarm (DF's)", state(civ_alert=True), Memory()))
    m = Memory()
    m.ai_alert_raised = True
    out.append(("the AI's alarm", state(), m))
    s = state()
    m = Memory()
    m.intrusion = {"tick": now_of(s) - 100, "civ": -1, "invaders": 1}
    out.append(("a thief or an ambush", s, m))
    s = state()
    m = Memory()
    m.weather_alarm = {"seen": now_of(s) - 10, "since": now_of(s) - 10, "why": "evil weather: blood rain"}
    out.append(("evil weather", s, m))
    out.append(("the threats unread", state(_errors={"others_on_map": "timeout"}), Memory()))
    return out


@test("brain: the meeting area off (its door locked) under each danger signal, at once and never quiet")
def _():
    for name, s, m in dangers():
        assert G.court_danger(s, m, GARDEN, CFG), name
        props, _ = run(s, m)
        assert len(props) == 1, (name, props)
        a = props[0].action
        assert a == {"type": "garden_court_meeting", "on": False, "lock": True}, (name, a)
        assert props[0].priority <= 2 and "door locked" in props[0].reason, (name, props[0].reason)
    # no danger: nothing to do (already on)
    assert not G.court_danger(state(), Memory(), GARDEN, CFG)
    props, _ = run(state(), Memory())
    assert not props, props
    assert "court_meeting" in EMERGENCY                     # no action limit, no back-off, never held


@test("brain: on again only once no danger has been read for a day (the gates' lift); a flicker starts it again")
def _():
    m = Memory()
    t0 = 1000
    threat = {"threats": [{"id": 8, "invader": True}]}
    props, _ = run(state(t0, others_on_map=threat), m)
    assert props and props[0].action["on"] is False
    off = dict(ON, meeting_on=False, locked=True)
    # danger still about, already off and locked: nothing (no flapping), a note
    props, notes = run(state(t0 + 100, others_on_map=threat, garden_court=off), m)
    assert not props and any("meeting area is off" in n for n in notes), notes
    # gone half a day: stays off
    props, notes = run(state(t0 + 600, garden_court=off), m)
    assert not props and any("after a day without danger" in n for n in notes), notes
    # a flicker of danger: the lift starts again from it
    props, _ = run(state(t0 + 700, others_on_map=threat, garden_court=off), m)
    assert not props
    props, _ = run(state(t0 + 700 + LIFT - 1, garden_court=off), m)
    assert not props
    props, _ = run(state(t0 + 700 + LIFT, garden_court=off), m)
    assert len(props) == 1 and props[0].action == {"type": "garden_court_meeting", "on": True}, props
    # on again: nothing more
    props, _ = run(state(t0 + 700 + LIFT + 100), m)
    assert not props
    # every look over a run of a flickering danger proposes at most one switch each way
    m = Memory()
    st, switches = dict(ON), []
    for i in range(0, 6000, 100):
        danger = (i // 100) % 7 == 0 and i < 2500           # seen every 700 ticks for a while
        s = state(i, others_on_map=threat if danger else {"threats": []}, garden_court=dict(st))
        props, _ = run(s, m)
        for p in props:
            switches.append((i, p.action["on"]))
            st["meeting_on"] = p.action["on"]
            st["locked"] = p.action.get("lock", False)
    assert [on for _, on in switches] == [False, True], switches
    assert switches[1][0] >= 2100 + LIFT, switches


@test("brain: never on while the court isn't secured; an older save's area switched off; a plain court says why")
def _():
    m = Memory()
    old = {"stage": "secure", "zoned": True, "meeting_on": True, "door_built": True, "locked": False,
           "lockable": True, "inside": 0, "secure_planned": 0, "secure_missing": 3}
    props, _ = run(state(garden_court=old), m)
    assert len(props) == 1 and props[0].action == {"type": "garden_court_meeting", "on": False, "lock": False}, props
    assert "isn't secured" in props[0].reason
    # off already, not secured, no danger: nothing, and never on
    props, _ = run(state(garden_court=dict(old, meeting_on=False)), m)
    assert not props
    # the build rule goes on with the secure step (the construction quiet as before)
    props, notes = [], []
    import planner_garden
    real = planner_garden.young_fort
    planner_garden.young_fort = lambda *a: False
    try:
        G._garden_court_rule(state(garden_court=dict(old, meeting_on=False)), CFG, 40, GARDEN, props, notes, m, {})
    finally:
        planner_garden.young_fort = real
    assert any(p.action["type"] == "place_garden_court" for p in props), (props, notes)
    assert any("secure it" in p.reason for p in props)
    # a plain garden: a note, no step, its area kept off
    plain = {"stage": "plain", "done": True, "plain": True, "plain_why": "a way into the fort is inside it",
             "zoned": True, "meeting_on": True, "door_built": True, "lockable": False, "inside": 0}
    props, notes = run(state(garden_court=plain), m)
    assert len(props) == 1 and props[0].action["on"] is False, props
    assert any("plain garden" in n and "way into the fort" in n for n in notes), notes
    props, notes = run(state(garden_court=dict(plain, meeting_on=False)), m)
    assert not props and any("plain garden" in n for n in notes)


@test("brain: the door is never asked locked with a citizen inside or when it can't be (a way in inside)")
def _():
    threat = {"threats": [{"id": 8, "invader": True}]}
    for st in (dict(ON, meeting_on=False, inside=2), dict(ON, meeting_on=False, lockable=False)):
        props, _ = run(state(others_on_map=threat, garden_court=st), Memory())
        assert not props, (st, props)                       # off, unlocked: as it should be
        props, _ = run(state(others_on_map=threat, garden_court=dict(st, locked=True)), Memory())
        assert len(props) == 1 and props[0].action["on"] is False, props   # asked again: the Lua unlocks it
    # the Lua side decides the lock again each time (see below); the brain's words say no lock
    props, _ = run(state(others_on_map=threat, garden_court=dict(ON, inside=1)), Memory())
    assert props and "door locked" not in props[0].reason


@test("brain: the secure stage's waits are notes; past the wait (or a gap) the step is asked")
def _():
    import planner_garden
    real = planner_garden.young_fort
    planner_garden.young_fort = lambda *a: False
    try:
        st = {"stage": "secure", "secure_planned": 4, "secure_missing": 0, "stage_days": 3}
        props, notes = [], []
        G._garden_court_rule(state(garden_court=st), CFG, 40, GARDEN, props, notes, Memory(), {})
        assert not props and any("4 wall or door piece(s)" in n for n in notes), notes
        for st2 in (dict(st, wait_over=True, stage_days=31), dict(st, secure_missing=2)):
            props = []
            G._garden_court_rule(state(garden_court=st2), CFG, 40, GARDEN, props, [], Memory(), {})
            assert len(props) == 1 and props[0].action["type"] == "place_garden_court", (st2, props)
    finally:
        planner_garden.young_fort = real


# --- 2. the Lua side ----------------------------------------------------------------------------

def _string_assign(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == name)


HARNESS = _string_assign(ROOT / "tests" / "test_builder.py", "HARNESS")
LUA = LuaRuntime(unpack_returned_tuples=True)
LUA.globals().LUA_DIR = str(ROOT / "lua")
B, W = LUA.execute(HARNESS, (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8"),
                   (ROOT / "lua" / "ai-builder.lua").read_text(encoding="utf-8"))
T = LUA.table_from
LUA.execute("df = df or {}; df.global = df.global or {}; df.global.world = df.global.world or {}")
LUA.execute("df.global.world.buildings = {other = {TRADE_DEPOT = {}}}")
SWAPPED = ("pasture_anchors", "surface_farm_spots", "hall_planned_at", "hall_free_items", "fell_tree",
           "deep_depot_mouth", "court_zone", "court_door_state", "court_door_locked", "court_lock_door", "qf_try")
SAVED = {k: B[k] for k in SWAPPED}
KEY = "ai-overseer/garden_court"


def lua_reset():
    W.reset()
    for k, v in SAVED.items():
        B[k] = v
    B.CACHE = None
    B.pasture_anchors = LUA.eval("function() return {{x = 60, y = 60, z = 80}} end")
    B.surface_farm_spots = LUA.eval("function() return {{x = 90, y = 60, z = 80}} end")
    B.hall_planned_at = LUA.eval("function() return false end")
    B.hall_free_items = LUA.eval("function() return 0 end")
    B.deep_depot_mouth = LUA.eval("function() return {} end")
    B.fell_tree = LUA.eval("function() return true end")
    for x in range(64, 110):
        for y in range(40, 81):
            W.set(x, y, 80, T({"shape": "FLOOR", "material": "SOIL", "outside": True}))
            W.set(x, y, 81, T({"shape": "EMPTY", "outside": True}))
    W.set(90, 60, 80, T({"taken": True}))
    # the stubs of the meeting area and the door: ZONE, DOOR (DOOR.state, DOOR.locked)
    LUA.execute("ZONE = {spec_sub_flag = {active = true}}; DOOR = {state = 'built', locked = false, locks = 0}")
    B.court_zone = LUA.eval("function() return ZONE end")
    B.court_door_state = LUA.eval("function() return DOOR.state end")
    B.court_door_locked = LUA.eval("function() return DOOR.locked end")
    B.court_lock_door = LUA.eval("function(c, l) DOOR.locks = DOOR.locks + 1; local ch = DOOR.locked ~= l;"
                                 " DOOR.locked = l; return ch end")


def lua_test(name):
    def deco(fn):
        def run_():
            lua_reset()
            fn()
        return test(name)(run_)
    return deco


def to_furnished():
    """The court built up to its furnish stage (the stub builds nothing)."""
    for _ in range(3):
        r = B.place_garden_court(False, T({"name": "Rose", "statues": 0}))
    assert r.ok and r.stage == "furnish", dict(r)
    return W.persist[KEY]


def build_ring(c):
    for t in c.tiles.values():
        if t.t == "Cw":
            W.set(t.x, t.y, 80, T({"shape": "WALL", "building": False}))


def zones():
    return [p for p in W.placed.values() if p.mode == "zone"]


@lua_test("lua: furnish goes to 'secure'; missing walls placed again; the zone only once secured")
def _():
    c = to_furnished()
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "secure" and not zones(), dict(r)
    st = B.garden_court_status()
    assert st.stage == "secure" and st.secure_missing == 39 and not st.done and not st.secured, dict(st)
    # unsecured: the meeting area can't be switched on
    r = B.garden_court_meeting(False, T({"on": True}))
    assert not r.ok and r.rejected and "not secured" in r.error, dict(r)
    # the walls gone missing (the stub built none): placed again, once
    n0 = len(W.placed)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "secure" and r.walls == 39, dict(r)
    assert [p.text for p in list(W.placed.values())[n0:]].count("Cw") == 39
    assert W.persist[KEY].secure_tries == 1 and not zones()
    # planned (waiting for the masons): a wait, no zone
    c = W.persist[KEY]
    for t in c.tiles.values():
        if t.t == "Cw":
            W.set(t.x, t.y, 80, T({"building": True}))
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert not r.ok and r.waiting and r.stage == "secure", dict(r)
    st = B.garden_court_status()
    assert st.secure_planned == 39 and st.secure_missing == 0, dict(st)
    # the door still planned: a wait
    build_ring(c)
    LUA.execute("DOOR.state = 'planned'")
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert not r.ok and r.waiting, dict(r)
    LUA.execute("DOOR.state = 'built'")
    # a dry run places nothing
    r = B.place_garden_court(True, T({"name": "Rose"}))
    assert r.ok and r.stage == "done" and r.dry_run and not zones(), dict(r)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "done" and r.secured and r.zone, dict(r)
    assert len(zones()) == 1 and zones()[0].text == 'm{name="The Rose Garden Court"}(9x9)'
    st = B.garden_court_status()
    assert st.done and st.secured and st.zoned and st.meeting_on is True and st.door_built and st.lockable, dict(st)
    assert st.locked is False and st.inside == 0


@lua_test("lua: garden_court_meeting: off (zone inactive, door locked), on (active, unlocked); a dry run changes nothing")
def _():
    c = to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    build_ring(c)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.stage == "done", dict(r)
    r = B.garden_court_meeting(True, T({"on": False, "lock": True}))
    assert r.ok and r.dry_run and LUA.eval("ZONE.spec_sub_flag.active") is True and LUA.eval("DOOR.locks") == 0
    r = B.garden_court_meeting(False, T({"on": False, "lock": True}))
    assert r.ok and r.zone and r.locked and LUA.eval("ZONE.spec_sub_flag.active") is False, dict(r)
    assert LUA.eval("DOOR.locked") is True
    st = B.garden_court_status()
    assert st.meeting_on is False and st.locked is True, dict(st)
    r = B.garden_court_meeting(False, T({"on": True}))
    assert r.ok and LUA.eval("ZONE.spec_sub_flag.active") is True and LUA.eval("DOOR.locked") is False, dict(r)
    # the real zone helpers on a zone's flags (spec_sub_flag.active)
    zn = LUA.eval("{spec_sub_flag = {active = true}}")
    assert SAVED["court_zone"] is not None
    assert B.zone_on(zn) is True and B.set_zone_on(zn, False) and B.zone_on(zn) is False


@lua_test("lua: never sealed in: no lock with a citizen inside the court, nor with a way into the fort inside it")
def _():
    c = to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    build_ring(c)
    assert B.place_garden_court(False, T({"name": "Rose"})).stage == "done"
    c = W.persist[KEY]
    W.citizens = T({1: T({"x": c.x, "y": c.y, "z": c.z})})
    r = B.garden_court_meeting(False, T({"on": False, "lock": True}))
    assert r.ok and not r.locked and r.inside == 1 and "inside" in r.unlocked_why, dict(r)
    assert LUA.eval("DOOR.locked") is False and LUA.eval("ZONE.spec_sub_flag.active") is False
    # nobody inside: locked; then a dwarf found inside: the next call unlocks it
    W.citizens = T({})
    assert B.garden_court_meeting(False, T({"on": False, "lock": True})).locked
    W.citizens = T({1: T({"x": c.x + 1, "y": c.y, "z": c.z})})
    assert B.garden_court_status().inside == 1
    assert not B.garden_court_meeting(False, T({"on": False, "lock": True})).locked
    assert LUA.eval("DOOR.locked") is False
    # a way into the fort inside it: never locked
    W.citizens = T({})
    B.pasture_anchors = LUA.eval("function() return {{x = %d, y = %d, z = 80}} end" % (c.x + 1, c.y + 1))
    r = B.garden_court_meeting(False, T({"on": False, "lock": True}))
    assert not r.locked and "way into the fort" in r.unlocked_why, dict(r)
    assert B.garden_court_status().lockable is False


@lua_test("lua: a court that can't be secured stays a plain garden (no meeting area), its why on record")
def _():
    # (a) a way into the fort inside it
    c = to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    B.pasture_anchors = LUA.eval("function() return {{x = %d, y = %d, z = 80}} end" % (c.x, c.y))
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "plain" and "way into the fort" in r.why and not zones(), dict(r)
    st = B.garden_court_status()
    assert st.plain and st.done and "way into the fort" in st.plain_why, dict(st)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert not r.ok and r.plain and r.done, dict(r)
    assert not B.garden_court_meeting(False, T({"on": True})).ok
    # (b) the game refuses its walls COURT_SECURE_TRIES times
    lua_reset()
    to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    B.qf_try = LUA.eval("function() return false, 'refused' end")
    for i in range(B.COURT_SECURE_TRIES - 1):
        r = B.place_garden_court(False, T({"name": "Rose"}))
        assert not r.ok and "refused" in r.error, dict(r)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.stage == "plain" and "refused its walls 3 times" in r.why, dict(r)
    # (c) its walls placed again and again, never built (no material)
    lua_reset()
    to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    for i in range(B.COURT_SECURE_TRIES):
        r = B.place_garden_court(False, T({"name": "Rose"}))
        assert r.ok and r.stage == "secure" and r.walls, dict(r)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.stage == "plain" and "put up 3 times" in r.why and not zones(), dict(r)
    # (d) no room: a tile of the ring takes no wall (water on its line)
    lua_reset()
    c = to_furnished()
    B.place_garden_court(False, T({"name": "Rose"}))
    W.set(c.x - c.r, c.y + 2, 80, T({"liquid": True}))         # (the door is mid-west)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.stage == "plain" and "water" in r.why, dict(r)
    # (e) walls planned that never come: COURT_WAIT_DAYS, then plain
    lua_reset()
    LUA.execute("W_NOW = 5000000")
    real_now = B.now_tick
    B.now_tick = LUA.eval("function() return W_NOW end")
    try:
        c = to_furnished()
        B.place_garden_court(False, T({"name": "Rose"}))
        build_ring(c)
        LUA.execute("DOOR.state = 'planned'")
        r = B.place_garden_court(False, T({"name": "Rose"}))
        assert r.waiting, dict(r)
        LUA.execute("W_NOW = W_NOW + 31 * 1200")
        assert B.garden_court_status().wait_over
        r = B.place_garden_court(False, T({"name": "Rose"}))
        assert r.stage == "plain" and "waited 31 days" in r.why, dict(r)
    finally:
        B.now_tick = real_now


@lua_test("lua: an older save past the zone gets 'secure' next, its meeting area switched off until secured")
def _():
    c = to_furnished()
    # as 0.105.47-64 left it: done, the zone on record, no secured
    c.stage = "done"
    q = c.r - 1
    c.tiles[len(c.tiles) + 1] = T({"x": c.x - q, "y": c.y - q, "z": 80, "t": 'm{name="The Rose Garden Court"}(9x9)'})
    st = B.garden_court_status()
    assert st.stage == "secure" and st.zoned and not st.done and not st.secured, dict(st)
    assert st.meeting_on is True                                  # (on, as it was: the brain switches it off)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "secure", dict(r)
    assert LUA.eval("ZONE.spec_sub_flag.active") is False         # off until secured
    c = W.persist[KEY]
    assert c.stage == "secure" and c.zoned
    build_ring(c)
    r = B.place_garden_court(False, T({"name": "Rose"}))
    assert r.ok and r.stage == "done" and r.secured and r.zone_kept and not zones(), dict(r)   # no second zone
    assert LUA.eval("ZONE.spec_sub_flag.active") is False         # on again by the brain's watch, not here
    assert B.garden_court_meeting(False, T({"on": True})).ok
    assert LUA.eval("ZONE.spec_sub_flag.active") is True


# --- 3. the wiring ------------------------------------------------------------------------------

@test("wiring: the action and its dry run, its arguments checked, label, classes, cooldown, the DF field")
def _():
    hub = bridge_hub_src()
    body = re.search(r"garden_court_meeting = function\(a\)\n(.*?)\n    end,", hub, re.S).group(1)
    assert "'garden_court_meeting'," in hub.split("DRY_OK = {}")[1].split("}) do DRY_OK")[0]
    env = LUA.eval("function(body) local calls = {}\n"
                   "local env = setmetatable({reject = function(w) return {ok = false, rejected = true, error = w} end,"
                   " reqscript = function() return {garden_court_meeting = function(d, o) table.insert(calls, {d, o})"
                   " return {ok = true, dry_run = d} end} end}, {__index = _G})\n"
                   "local f = assert(load('return function(a)\\n' .. body .. '\\nend', 'act', 't', env))()\n"
                   "return f, calls end")
    f, calls = env(body)
    assert f(T({"on": False, "lock": True, "dry_run": True})).dry_run
    o = calls[1][2]
    assert (o.on, o.lock) == (False, True)
    for bad in ({}, {"on": "yes"}, {"on": True, "lock": 1}):
        r = f(T(bad))
        assert not r.ok and r.rejected, bad
    import overseer_words
    assert "garden_court_meeting" in overseer_words.ACTION_WORDS if hasattr(overseer_words, "ACTION_WORDS") else True
    assert '"garden_court_meeting": "' in (ROOT / "brain" / "overseer_words.py").read_text(encoding="utf-8")
    assert "garden_court_meeting" not in overseer_words.BIG_MOVES     # the AI does it itself
    import hold_classes
    assert hold_classes.ACTION_CLASS["garden_court_meeting"] == hold_classes.DEFENCE
    assert "court_meeting" in hold_classes.RULE_SETS[hold_classes.DEFENCE]
    assert CFG["court_meeting_cooldown_ticks"] <= 100 and LIFT == 1200
    import planner_guards
    from planner_core import Proposal
    assert not planner_guards.is_outdoor(Proposal("court_meeting", {"type": "garden_court_meeting", "on": False}, "", 2))
    # the zone's on/off: building_civzonest.spec_sub_flag (civzone_activity_flag) .active in DFHack 53.17
    names = json.loads((ROOT / "tests" / "fixtures" / "df-names.json").read_text(encoding="utf-8"))
    t = names["types"]
    assert t["building_civzonest"]["f"]["spec_sub_flag"] == "civzone_activity_flag"
    assert "active" in t["civzone_activity_flag"]["v"]
    assert "MeetingHall" in t["civzone_type"]["v"] and "forbidden" in t["building_door_flag"]["v"]
    assert "findCivzonesAt" in names["dfhack"]["buildings"]
    src = (ROOT / "lua" / "ai-builder-court.lua").read_text(encoding="utf-8")
    assert "zn.spec_sub_flag.active" in src and "findCivzonesAt" in src


if __name__ == "__main__":
    finish()
