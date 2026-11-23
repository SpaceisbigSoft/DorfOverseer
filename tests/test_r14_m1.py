"""(r14 m1, live 22 Nov 20:58) A messenger who left the fort.

In forts A, C and F the messenger's one slot named a figure with no unit
anywhere in world.units.all, whose whereabouts was an army of a nomadic group
of the fort's own civilisation (goal CAMP, "The Torments of Tattooing"), and
the fort had no mission out: every Make contact was refused "the messenger is
away" and the post could never be refilled. Now such a holder is STALE
(lua/ai-nobles-swap.lua stale_holder): reported (messenger_status, the
offices survey), taken off and the post refilled in one all-or-nothing action
(appoint with replace_stale), never "away" to the sender (messenger_home picks
a holder at home among several), proposed by the planner (planner_world
_stale_rule, rule office_free), and the planner never appoints a second
messenger right after one. Each messenger appointment logs the figure and its
whereabouts.

    python tests/test_r14_m1.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import PLANNER_CONFIG  # noqa: E402
from planner_core import Memory, Proposal, abs_tick  # noqa: E402
from planner_core_refusals import refusal_key  # noqa: E402
import planner_world  # noqa: E402
import hold_classes as H  # noqa: E402
from overseer_words import short  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = 1200


def _fake() -> str:
    """test_r11_n1.py's fake world (seven founders holding offices), read
    without running that file's tests."""
    tree = ast.parse((ROOT / "tests" / "test_r11_n1.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FAKE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("no FAKE in test_r11_n1.py")


FAKE = _fake()

# The world around the offices: every unit in world.units.all (from W.UNITS),
# armies and their controllers (W.ARMIES, W.CTLS), the nomadic group 60 ("The
# Torments of Tattooing", of the fort's civilisation 40; the fort is 50).
# W.gone(uid) takes a dwarf off the map (no unit anywhere); W.away(uid, entity,
# goal) puts their figure on an army of that entity's controller.
WORLD = r"""
W.ARMIES, W.CTLS = {}, {}
df.global.world.units = setmetatable({}, {__index = function(_, k)
  if k == 'all' then local l = {}; for _, u in pairs(W.UNITS) do table.insert(l, u) end; return W.ivec(l) end end})
df.army = {find = function(id) return W.ARMIES[id] end}
df.army_controller = {find = function(id) return W.CTLS[id] end}
df.global.world.army_controllers = setmetatable({}, {__index = function(_, k)
  if k == 'all' then local l = {}; for _, c in pairs(W.CTLS) do table.insert(l, c) end; return W.ivec(l) end end})
df.army_controller_goal_type = {[1] = 'CAMP', [25] = 'DIPLOMACY', [2] = 'SITE_INVASION', CAMP = 1, DIPLOMACY = 25,
                                SITE_INVASION = 2}
df.whereabouts_type = {[0] = 'alive_settled', [3] = 'army_died', [4] = 'army_alive'}
df.historical_entity_type = {[0] = 'Civilization', [1] = 'SiteGovernment', [5] = 'NomadicGroup'}
W.NOMADS = {id = 60, type = 5, name = 'The Torments of Tattooing', positions = {own = W.ivec({}), assignments = W.ivec({})}}
local find0 = df.historical_entity.find
df.historical_entity.find = function(id) if id == 60 then return W.NOMADS end return find0(id) end
CIV.type, FORT.type = 0, 1
function W.gone(uid)
  W.UNITS[uid] = nil
  for i = #W.CITS, 1, -1 do if W.CITS[i].id == uid then table.remove(W.CITS, i) end end
end
function W.away(uid, entity, goal, n)
  n = n or 77
  W.CTLS[n + 1] = {id = n + 1, entity_id = entity, goal = goal, year = 250}
  W.ARMIES[n] = {id = n, controller_id = n + 1}
  W.HFS[890 + uid].info = {whereabouts = {state = 3, army_id = n}}
end
"""


def world(setup: str = ""):
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, module_src("ai-nobles.lua"),
                      "local FORT, CIV = df.historical_entity.find(50), df.historical_entity.find(40)\n" + WORLD + setup)
    return env


def _run(env, code: str):
    env.load(code, "t", "t", env)()


def _table(env, d):
    t = env.W.T()
    for k, v in d.items():
        t[k] = v
    return t


def holders(env) -> dict:
    out = {}
    for uid in sorted(env.W.UNITS.keys()):
        lst = env.dfhack.units.getNoblePositions(env.W.UNITS[uid])
        for i in range(1, len(lst) + 1):
            out.setdefault(lst[i].position.code, []).append(uid)
    return out


def snapshot(env) -> tuple:
    a = env.W.FORT.positions.assignments
    links = tuple((k, env.W.HFS[k].entity_links.n) for k in sorted(env.W.HFS.keys()))
    return (a.n, env.W.FORT.positions.next_assignment_id, tuple(a[i].histfig for i in range(a.n)), links,
            env.df["global"].hist_event_next_id)


def free_stale(env, dry=False, code="MESSENGER"):
    return env.appoint(code, dry, None, _table(env, {"replace_stale": True}))


# the messenger (18) appointed while home, then gone with the nomads' CAMP army; 19 free at home
GONE_CAMP = "W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.gone(18); W.away(18, 60, 1)"


# ---- 1. the stale holder reported, freed and refilled -----------------------------------------------

@test("stale: a messenger with no unit, on another entity's CAMP army, is reported (status, survey, why)")
def _():
    env = world(GONE_CAMP)
    st = env.messenger_status(None)
    assert st.held_by == "Dwarf18" and st.stale is not None, dict(st)
    s = st.stale
    assert (s.name, s.entity, s.entity_name, s.goal, s.year) == ("Dwarf18", 60, "The Torments of Tattooing", "CAMP", 250), dict(s)
    assert s.entity_type == "NomadicGroup" and s.state == "army_died" and s.army_id == 77, dict(s)
    assert st.why == ("the messenger Dwarf18 left the fort with The Torments of Tattooing (CAMP): the post is free"), st.why
    assert not st.away, dict(st)                                # never "away"
    sv = env.survey(None)
    assert sv.stale.MESSENGER.entity_name == "The Torments of Tattooing" and sv.stale.MESSENGER.fixed is None
    assert sv.messenger.stale.goal == "CAMP" and "left the fort" in sv.messenger.left
    # (r14 m1 fixes) no army at all, or an army whose controller is missing: unknown, kept (below)


@test("stale: freed and refilled in one action: the free citizen appointed, the gone one's former link and event")
def _():
    env = world(GONE_CAMP)
    ev = env.df["global"].hist_event_next_id
    r = free_stale(env)
    assert r.ok is True and r.unit_id == 19 and r.freed == "Dwarf18" and r.left_with == "The Torments of Tattooing", dict(r)
    assert r.goal == "CAMP" and "left the fort" in r.why
    assert holders(env)["MESSENGER"] == [19], holders(env)
    a = env.W.FORT.positions.assignments
    assert a.n == 8 and a[7].histfig == 909, [a[i].histfig for i in range(a.n)]   # the same slot, no second one
    links = env.W.HFS[908].entity_links
    assert links.n == 1 and links[0].former, "the gone figure keeps only a former-position link"
    assert env.df["global"].hist_event_next_id == ev + 2        # the remove event and the new add event
    st = env.messenger_status(None)
    assert st.held_by == "Dwarf19" and st.stale is None and st.why is None, dict(st)
    # (5) the appointment's result names the new figure and its whereabouts
    assert r.figure == 909, dict(r)


@test("stale: nobody suitable at home: refused, nothing changed; with interim an office holder takes it")
def _():
    env = world("W.unit(18, 6); W.hold(18, 7); W.gone(18); W.away(18, 60, 1)")
    before = snapshot(env)
    r = free_stale(env)
    assert r.ok is False and r.rejected and "nobody suitable" in r.error, dict(r)
    assert snapshot(env) == before
    r = env.appoint("MESSENGER", False, None, _table(env, {"replace_stale": True, "interim": True}))
    assert r.ok is True and r.unit_id == 13 and r.keeps == "BOOKKEEPER", dict(r)
    h = holders(env)
    assert h["MESSENGER"] == [13] and h["BOOKKEEPER"] == [13], h


@test("stale: a failed write puts the gone holder back as they were")
def _():
    env = world(GONE_CAMP + "; W.BLIND[909] = true")
    before = snapshot(env)
    r = free_stale(env)
    assert r.ok is False and r.restored is True and "put back" in r.error, dict(r)
    assert snapshot(env) == before


# ---- 2. away on the fort's own mission: kept ---------------------------------------------------------

@test("away: a messenger on the fort's own DIPLOMACY mission (no unit) is kept and 'away', never freed")
def _():
    for entity in (50, 40):                                      # the fort's government or its civilisation
        env = world("W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.gone(18); W.away(18, %d, 25)" % entity)
        st = env.messenger_status(None)
        assert st.stale is None and st.away and "army" in st.away, dict(st)
        assert env.survey(None).stale.MESSENGER is None
        before = snapshot(env)
        r = free_stale(env)
        assert r.ok is False and r.rejected and "nothing to free" in r.error, dict(r)
        assert snapshot(env) == before
    # the fort's own controller but a CAMP goal: stale
    env = world("W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.gone(18); W.away(18, 50, 1)")
    assert env.messenger_status(None).stale is not None
    # a Make contact run under way: never judged
    env = world(GONE_CAMP)
    _run(env, "W.RUN = {goal = 'make_contact'}")
    assert env.messenger_status(None).stale is None


@test("dead: a holder whose unit is dead (or whose figure died) is stale and freed; one on the map is not")
def _():
    env = world("W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.UNITS[18].flags2.killed = true")
    st = env.messenger_status(None)
    assert st.stale is not None and st.stale.dead is True and st.why == "the messenger Dwarf18 is dead: the post is free", dict(st)
    r = free_stale(env)
    assert r.ok is True and r.unit_id == 19, dict(r)
    env = world("W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.gone(18); W.HFS[908].died_year = 255")
    assert env.messenger_status(None).stale.dead is True
    env = world("W.unit(18, 6); W.hold(18, 7); W.unit(19, 4)")
    assert env.messenger_status(None).stale is None and env.survey(None).stale.MESSENGER is None
    # a manager gone too: freed the same way (every civilian office the AI fills)
    env = world("W.unit(18, 6); W.gone(12); W.away(12, 60, 1)")
    assert env.survey(None).stale.MANAGER.name == "Dwarf12"
    r = free_stale(env, code="MANAGER")
    assert r.ok is True and r.unit_id == 18 and holders(env)["MANAGER"] == [18], dict(r)


# ---- 3. the sender: the holder at home among several ----------------------------------------------

def messenger_home_src() -> str:
    src = (ROOT / "lua" / "ai-mission-send-run.lua").read_text(encoding="utf-8")
    m = re.search(r"^function messenger_home\(\).*?^end\n", src, re.M | re.S)
    return ("local U = {fort_entity = function() return W.FORT end}\n"
            "local function first_name(hf) return hf.name end\n" + m.group(0))


@test("messenger_home: the holder at home among several is sent; 'away' only when none is; a stale one 'left the fort'")
def _():
    setup = ("W.FORT.positions.own[6].number = -1; W.unit(18, 6); W.unit(19, 6); W.unit(20, 6); "
             "W.hold(18, 7); W.hold(19, 7); W.hold(20, 7); "
             "W.gone(18); W.away(18, 60, 1, 77); W.gone(19); W.away(19, 50, 25, 80)")
    env = world(setup)
    _run(env, messenger_home_src())
    uid, why = env.messenger_home()
    assert uid == 20 and env.MESSENGER_HF == 910, (uid, why)
    st = env.messenger_status(None)
    assert st.held_by == "Dwarf20" and st.holders == 3 and st.stale is None and not st.away, dict(st)
    _run(env, "W.gone(20)")
    uid, why = env.messenger_home()
    assert uid is None and why == "the messenger is away", why
    env = world("W.unit(18, 6); W.hold(18, 7); W.gone(18); W.away(18, 60, 1)")
    _run(env, messenger_home_src())
    uid, why = env.messenger_home()
    assert uid is None and "left the fort with The Torments of Tattooing (CAMP)" in why, why
    # during a run the sender's own check still says "left the fort"
    _run(env, "W.RUN = {goal = 'make_contact'}")
    assert "left the fort" in env.messenger_home()[1]


# ---- 4. never a second messenger --------------------------------------------------------------------

@test("no second appointment: a vacant slot beside a held one is not filled (Lua); the result logs the figure")
def _():
    env = world("W.FORT.positions.own[6].number = -1; W.unit(18, 6); W.unit(19, 4);"
                " W.FORT.positions.assignments:insert('#', {id = 20, position_id = 7, histfig = -1, flags = {}, squad_id = -1});"
                " W.FORT.positions.next_assignment_id = 21; W.hold(18, 7)")
    before = snapshot(env)
    r = env.appoint("MESSENGER", False, None)
    assert r.ok is False and "already held" in r.error, dict(r)
    assert snapshot(env) == before and holders(env)["MESSENGER"] == [18]
    # a first appointment: the chosen figure and its whereabouts in the result
    env = world("W.unit(18, 6); W.HFS[908].info = {whereabouts = {state = 0, army_id = -1}}")
    r = env.appoint("MESSENGER", False, None)
    assert r.ok is True and r.unit_id == 18 and r.figure == 908, dict(r)
    assert r.whereabouts.state == "alive_settled" and r.whereabouts.army_id == -1, dict(r.whereabouts)
    d = world("W.unit(18, 6)").appoint("MESSENGER", True, None)
    assert d.ok is True and d.dry_run is True and d.figure == 908, dict(d)


def state(messenger=None, offices=None, stale=None, tick=10 * DAY, **kw):
    s = {"settings": {"make_contact": True, "appoint_nobles": True, "send_messenger": True},
         "dwarves": {"total": 12}, "stocks": {"drink": 2000, "prepared_meals": 2000},
         "buildings": {"other": {"FarmPlot": 4}},
         "offices": {"offices": offices or {}, "messenger": messenger or {}, "stale": stale or {}},
         "missions": {"controllers": [], "send": {}},
         "date": {"year": 256, "tick": tick}}
    s.update(kw)
    return s


VACANT = {"MESSENGER": {"vacant": 1, "held": [], "slots": 2, "appointable": True}}
NOBODY = {"position": True, "post": "fort", "why": "post exists, nobody appointed"}


@test("planner: no new appointment while the report shows a holder (even away) or one was appointed lately")
def _():
    for ms in (dict(NOBODY, held_by="Urist", away="away with an army (a mission)"), dict(NOBODY, holder_unit=18)):
        props = []
        planner_world._messenger_rule(state(ms, VACANT), CFG, props, [], Memory())
        assert not props, (ms, props)
    s = state(NOBODY, VACANT, tick=40 * DAY)
    m = Memory()
    now = abs_tick(s)
    m.last_fired = {"messenger": now - DAY}                        # appointed a day ago: "nobody holds it" again
    props = []
    planner_world._messenger_rule(s, CFG, props, [], m)
    assert not props, props
    m.last_fired = {"messenger": now - (CFG["m1_messenger_reappoint_days"] + 1) * DAY}
    props = []
    planner_world._messenger_rule(s, CFG, props, [], m)
    assert props and props[0].action == {"type": "appoint", "office": "MESSENGER"}, props


STALE = {"name": "Urist", "entity": 3160, "entity_name": "The Torments of Tattooing", "entity_type": "NomadicGroup",
         "goal": "CAMP", "year": 250, "holder_hf": 908}
HELD = {"MESSENGER": {"vacant": 0, "held": ["Urist"], "slots": 1, "appointable": True}}


@test("planner: a stale messenger: freed and refilled (one action), the journal names who left and with whom")
def _():
    ms = dict(NOBODY, held_by="Urist", stale=STALE, why="the messenger Urist left the fort with The Torments of "
              "Tattooing (CAMP): the post is free")
    props, notes = [], []
    planner_world._messenger_rule(state(ms, HELD, {"MESSENGER": dict(STALE, why="x")}), CFG, props, notes, None)
    assert len(props) == 1 and props[0].rule == "office_free", props
    assert props[0].action == {"type": "appoint", "office": "MESSENGER", "replace_stale": True, "interim": True}
    assert "Urist left the fort with The Torments of Tattooing (CAMP, a NomadicGroup, since year 250)" in props[0].reason
    assert short(props[0].action).startswith("give the messenger's post, whose holder left the fort")
    assert H.RULE_CLASS["office_free"] == H.RULE_CLASS["messenger"]
    # never while a Make contact run is going or a Diplomacy mission is out: a note instead
    for missions in ({"controllers": [], "send": {"running": {"goal": "make_contact", "step": "open"}}},
                     {"controllers": [{"id": 4, "goal": "DIPLOMACY"}], "send": {}}):
        props, notes = [], []
        planner_world._messenger_rule(state(ms, HELD, missions=missions), CFG, props, notes, Memory())
        assert not props and any("left the fort" in n for n in notes), (missions, props, notes)
    # the contact rule never sends a stale messenger
    props = []
    planner_world._contact_rule(state(ms, HELD), CFG, props, [], Memory())
    assert not props, props
    # a stale manager (no messenger matter): freed too; its refusal is its own
    props = []
    planner_world._messenger_rule(state(dict(NOBODY, held_by="Kib"), HELD, {"MANAGER": dict(STALE, name="Kib")}),
                                  CFG, props, [], None)
    assert props and props[0].action == {"type": "appoint", "office": "MANAGER", "replace_stale": True}, props
    pa = Proposal("office_free", {"type": "appoint", "office": "MANAGER", "replace_stale": True}, "", 5)
    pb = Proposal("office_free", {"type": "appoint", "office": "MESSENGER", "replace_stale": True}, "", 5)
    assert refusal_key(pa) != refusal_key(pb)


# ---- (r14 m1 fixes) the verifier's findings -------------------------------------------------------

@test("M1: stale only on evidence: an army or controller missing, the fort's own controller with another goal, no army: unknown, never freed")
def _():
    base = "W.unit(18, 6); W.hold(18, 7); W.unit(19, 4); W.gone(18); "
    for setup in ("W.away(18, 50, 25); W.CTLS[78] = nil",                     # controller dropped
                  "W.away(18, 50, 25); W.ARMIES[77] = nil",                   # army record gone
                  "W.HFS[908].info = {whereabouts = {state = 5, army_id = -1, site_id = 9}}",   # arrived, a visitor
                  "W.HFS[908].info = nil",                                    # nothing read
                  "W.away(18, 50, 12)",                                       # the fort's controller, another goal
                  "W.away(18, 40, 12)"):                                      # the civilisation's, another goal
        env = world(base + setup)
        st = env.messenger_status(None)
        assert st.stale is None and st.unknown is not None and st.unknown.reason, (setup, dict(st))
        assert env.survey(None).stale.MESSENGER is None, setup
        before = snapshot(env)
        for dry in (True, False):
            r = free_stale(env, dry)
            assert r.ok is False and r.rejected and "nothing to free" in r.error, (setup, dry, dict(r))
        assert snapshot(env) == before
    # the live case still caught: the nomads' CAMP army; and any other entity's army
    for setup in ("W.away(18, 60, 1)", "W.away(18, 60, 25)"):
        assert world(base + setup).messenger_status(None).stale is not None, setup


@test("M1: free_stale itself refuses the messenger while a Diplomacy mission of the fort or its civilisation is out")
def _():
    for entity in (50, 40):
        env = world(GONE_CAMP + "; W.CTLS[500] = {id = 500, entity_id = %d, goal = 25, year = 256}" % entity)
        before = snapshot(env)
        for dry in (True, False):
            r = free_stale(env, dry)
            assert r.ok is False and r.rejected and "Diplomacy mission" in r.error, (entity, dry, dict(r))
        assert snapshot(env) == before
    env = world(GONE_CAMP + "; W.CTLS[500] = {id = 500, entity_id = 60, goal = 25, year = 256}")   # another's: no matter
    assert free_stale(env).ok is True


@test("M1: the planner frees only after the stale reading held m1_stale_confirm_days (same holder; kept by note_world, plan writes nothing)")
def _():
    import json
    ms = dict(NOBODY, held_by="Urist", stale=STALE)
    m = Memory()
    m.world_seen = {}
    seen = []
    for day in (10, 10.5, 12, 13):
        st = state(ms, HELD, tick=int(day * DAY))
        planner_world.note_stale(st, m)                  # the bookkeeping (note_world, note_cycle) before planning
        before = json.dumps(m.to_dict(), sort_keys=True, default=str)
        props, notes = [], []
        planner_world._messenger_rule(st, CFG, props, notes, m)
        assert json.dumps(m.to_dict(), sort_keys=True, default=str) == before   # the rule never writes memory
        seen.append((len(props), sum("after 3 day(s)" in n for n in notes)))
    assert seen == [(0, 1), (0, 1), (0, 1), (1, 0)], seen
    # another holder stale: the clock starts again; not stale any more: forgotten
    st = state(dict(ms, stale=dict(STALE, holder_hf=999)), HELD, tick=14 * DAY)
    planner_world.note_stale(st, m)
    props = []
    planner_world._messenger_rule(st, CFG, props, [], m)
    assert not props
    planner_world.note_stale(state(dict(NOBODY, held_by="Urist"), HELD, tick=15 * DAY), m)
    assert "MESSENGER" not in m.world_seen["stale_seen"]
    import inspect
    assert "note_stale(s, memory)" in inspect.getsource(planner_world.note_world)


@test("L4: with m1_free_stale off, a stale-held post is said (no proposal, no plain appointment)")
def _():
    props, notes = [], []
    planner_world._messenger_rule(state(dict(NOBODY, held_by="Urist", stale=STALE), HELD), dict(CFG, m1_free_stale=False),
                                  props, notes, Memory())
    assert not props and any("left the fort" in n and "m1_free_stale" in n and "no messenger can make contact" in n
                             for n in notes), notes


@test("L6: the waiting notes read right while a Diplomacy mission is out or a run is going")
def _():
    ms = dict(NOBODY, held_by="Urist", stale=STALE)
    for missions, words in (({"controllers": [{"id": 4, "goal": "DIPLOMACY"}], "send": {}}, "once the Diplomacy mission is back"),
                            ({"controllers": [], "send": {"running": {"goal": "make_contact"}}}, "once the Make contact run is over")):
        notes = []
        planner_world._messenger_rule(state(ms, HELD, missions=missions), CFG, [], notes, None)
        assert any(n.endswith(words) for n in notes), notes
        assert not any("is out is over" in n for n in notes), notes


# ---- 5. dry runs and posts the fort doesn't fill -----------------------------------------------------

@test("dry runs change nothing: replace_stale dry, the reads")
def _():
    env = world(GONE_CAMP)
    before = snapshot(env)
    d = free_stale(env, dry=True)
    assert d.ok is True and d.dry_run is True and d.unit_id == 19 and d.freed == "Dwarf18", dict(d)
    env.survey(None)
    env.messenger_status(None)
    assert snapshot(env) == before


@test("elected posts untouched: an ELECTED messenger, the expedition leader gone, a squad-leading slot")
def _():
    env = world(GONE_CAMP + "; W.P.MESSENGER.flags.ELECTED = true")
    assert env.survey(None).stale.MESSENGER.fixed == "elected"
    before = snapshot(env)
    r = free_stale(env)
    assert r.ok is False and r.rejected and "not the fort's to fill" in r.error, dict(r)
    assert snapshot(env) == before
    env = world("W.unit(18, 6); W.gone(11); W.away(11, 60, 1)")      # the expedition leader left with the nomads
    sv = env.survey(None).stale
    assert sv.EXPEDITION_LEADER is None and sv.MANAGER is None, dict(sv)
    before = snapshot(env)
    for code in ("EXPEDITION_LEADER", "MAYOR", "MILITIA_COMMANDER"):
        r = free_stale(env, code=code)
        assert r.ok is False and r.rejected, (code, dict(r))
    assert snapshot(env) == before
    # a manager's slot that leads a squad: reported fixed, never freed
    env = world("W.unit(18, 6); W.gone(12); W.away(12, 60, 1); W.FORT.positions.assignments[1].squad_id = 3")
    assert env.survey(None).stale.MANAGER.fixed == "leads a squad"
    before = snapshot(env)
    assert free_stale(env, code="MANAGER").ok is False and snapshot(env) == before


# ---- the sources ------------------------------------------------------------------------------------

CHANGED = ["ai-nobles.lua", "ai-nobles-swap.lua", "ai-mission-send-run.lua", "ai-bridge-actions-works.lua"]


@test("every changed Lua file compiles under Lua 5.3 and stays under 60 KB; the action passes replace_stale")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    check = lua.eval("function(src, name) local f, e = load(src, name, 't', {}); return f ~= nil, e end")
    for n in CHANGED:
        src = (ROOT / "lua" / n).read_text(encoding="utf-8")
        ok, err = check(src, n)
        assert ok, (n, err)
        assert len(src.encode("utf-8")) < 60 * 1024, n
    works = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "replace_stale = a.replace_stale == true" in works


@test("r14 hold: with MESSENGER_HOLD on, no messenger is appointed and no messenger post freed; other offices go on")
def _():
    env = world()
    env.MESSENGER_HOLD = True
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False and "held (22 Nov)" in str(a.error), dict(a)
    S = env.reqscript("ai-nobles-swap")
    f = S.free_stale("MESSENGER", False, None, None)
    assert f.ok is False and "held (22 Nov)" in str(f.error), dict(f)
    m = env.appoint("MANAGER", True, None)
    assert "held (22 Nov)" not in str(m.error or ""), dict(m)


# ---- (r15, live 22 Nov 21:52) the slot's army link: DF's own slots hold -1 ------------------------

@test("r15: a slot the AI makes holds -1 in assigned_army_controller_id (and ab, st, vassal), as DF's own")
def _():
    env = world()
    a, idx, p = env.add_slot(env.W.FORT, "MESSENGER")
    assert a is not None, (a, idx, p)
    for f in ("assigned_army_controller_id", "ab_id", "st_id", "vassal_of_entity_id", "vassal_of_position_profile_id"):
        assert a[f] == -1, (f, a[f])


@test("r15: an old AI slot's army controller 0 is cleared as a holder is written into it")
def _():
    env = world(GONE_CAMP)
    a = env.W.FORT.positions.assignments
    a[7].assigned_army_controller_id = 0             # the AI's slot before 0.105.72
    r = free_stale(env)
    assert r.ok is True and a[7].histfig == 909, dict(r)
    assert a[7].assigned_army_controller_id == -1, a[7].assigned_army_controller_id


@test("r15: a slot on one of the fort's own missions keeps its army controller; a camp's or another entity's is cleared")
def _():
    env = world()
    fort = env.W.FORT
    for ctl, keep in (({"id": 5, "entity_id": 50, "goal": 25}, True),     # the fort's own DIPLOMACY
                      ({"id": 5, "entity_id": 40, "goal": 25}, True),     # the civ's DIPLOMACY
                      ({"id": 5, "entity_id": 50, "goal": 1}, False),     # a CAMP
                      ({"id": 5, "entity_id": 60, "goal": 25}, False),    # another entity's
                      (None, False)):                                     # no such controller
        env.W.CTLS[5] = _table(env, ctl) if ctl else None
        a = _table(env, {"assigned_army_controller_id": 5, "ab_id": 3})
        env.clear_slot_links(a, env.own_mission_controller(a, fort))
        assert (a.assigned_army_controller_id == 5) is keep and a.ab_id == -1, (ctl, a.assigned_army_controller_id)


@test("r15 v8: once a DF session, the first real appointment clears every slot's stray army link (the fort's own mission kept); a dry run sweeps nothing")
def _():
    env = world()
    a = env.W.FORT.positions.assignments
    a[0].assigned_army_controller_id = 0                  # an AI slot made before 0.105.72
    env.W.CTLS[5] = _table(env, {"id": 5, "entity_id": 50, "goal": 25})
    a[1].assigned_army_controller_id = 5                  # on the fort's own DIPLOMACY
    env.appoint("MANAGER", True, None)                    # dry: nothing swept
    assert a[0].assigned_army_controller_id == 0 and env.SLOTS_SWEPT is False
    env.appoint("MANAGER", False, None)
    assert a[0].assigned_army_controller_id == -1 and a[1].assigned_army_controller_id == 5, \
        (a[0].assigned_army_controller_id, a[1].assigned_army_controller_id)
    assert env.SLOTS_SWEPT is True
    a[0].assigned_army_controller_id = 0
    env.appoint("MANAGER", False, None)                   # not again this session
    assert a[0].assigned_army_controller_id == 0


@test("r15 v8: the militia's add_post sets the new slot's army link to -1 too (source)")
def _():
    src = (ROOT / "lua" / "ai-military-draft.lua").read_text(encoding="utf-8")
    body = src[src.index("function add_post("):]
    body = body[:body.index("\nend\n")]
    assert "clear_slot_links(a)" in body and "assigned_army_controller_id = -1" in body, body[:400]


if __name__ == "__main__":
    finish()
