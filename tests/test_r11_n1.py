"""(r11 n1, the player 22 Nov 01:43) The interim messenger and better office holders.

Live (22 Nov): every fort fresh from embark, 7 founders all holding offices, so
`appoint('MESSENGER')` was refused "no grown citizen to appoint" 4-5 times in
each fort. Now an office holder doubles as messenger (the least needed
office, the best talker; never the leader, the militia, a soldier, the unfit),
is swapped out once a suitable free citizen exists (never while away or on a
run), and any civilian office goes to a free citizen vastly better at its
skills (a high margin, a season per office, one a day fort-wide, never an
elected post, all-or-nothing). lua/ai-nobles.lua, lua/ai-nobles-swap.lua,
brain/planner_world.py _messenger_rule, brain/planner_office_swap.py.

    python tests/test_r11_n1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import PLANNER_CONFIG  # noqa: E402
from planner_core import COOLDOWN_KEYS, Memory, Proposal, abs_tick  # noqa: E402
from planner_core_refusals import cooldown_key  # noqa: E402
import planner_world  # noqa: E402
import planner_office_swap as OS  # noqa: E402
import hold_classes as H  # noqa: E402
from overseer_words import short  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = 1200

# Seven founders, each holding an office: 11 the expedition leader, 12 the
# manager, 13 the bookkeeper, 14 the broker, 15 the chief medical dwarf, 16 the
# sheriff, 17 the militia commander (and a soldier). The messenger's post (7)
# is AS_NEEDED with no slot, appointed by the leader. `talk` is each one's
# level in every skill; W.hold(uid, pos_id) appoints, W.unit(...) adds a dwarf.
FAKE = r"""
local src, setup = ...
local env = setmetatable({}, {__index = _G})
local function ivec(t)
  local v = {n = #t}
  for i, x in ipairs(t) do v[i - 1] = x end
  return setmetatable(v, {__len = function(self) return self.n end,
    __index = {insert = function(self, pos, x)
                 if type(x) == 'table' and type(x.new) == 'table' and x.new.former then x.former = true end
                 if type(pos) == 'number' and pos < self.n then      -- (r11 n1 fixes) at an index, as DF vectors
                   for k = self.n, pos + 1, -1 do self[k] = self[k - 1] end
                   self[pos] = x
                 else
                   self[self.n] = x
                 end
                 self.n = self.n + 1 end,
               erase = function(self, i) for k = i, self.n - 2 do self[k] = self[k + 1] end; self[self.n - 1] = nil; self.n = self.n - 1 end}})
end
local function ipairs0(v)
  if getmetatable(v) and v.n then
    local i = -1
    return function() i = i + 1; if i < v.n then return i, v[i] end end
  end
  return ipairs(v)
end
env.ipairs = ipairs0
local function pos(t)
  t.appointed_by = t.appointed_by or ivec({}); t.flags = t.flags or {}; t.responsibilities = t.responsibilities or {}
  t.number = t.number or 1; t.requires_population = t.requires_population or 0
  return t
end
local P = {}
for i, code in ipairs({'EXPEDITION_LEADER', 'MANAGER', 'BOOKKEEPER', 'BROKER', 'CHIEF_MEDICAL_DWARF', 'SHERIFF'}) do
  P[code] = pos{id = i, code = code, appointed_by = ivec(i == 1 and {} or {1})}
end
P.MESSENGER = pos{id = 7, code = 'MESSENGER', appointed_by = ivec({1}), number = -1}
P.MILITIA_COMMANDER = pos{id = 8, code = 'MILITIA_COMMANDER', appointed_by = ivec({1})}
local own = {}
for _, c in ipairs({'EXPEDITION_LEADER', 'MANAGER', 'BOOKKEEPER', 'BROKER', 'CHIEF_MEDICAL_DWARF', 'SHERIFF',
                    'MESSENGER', 'MILITIA_COMMANDER'}) do table.insert(own, P[c]) end
local FORT = {id = 50, positions = {own = ivec(own), site = ivec({}), assignments = ivec({}), next_assignment_id = 0},
              assignments_by_type = ivec({})}
local CIV = {id = 40, positions = {own = ivec({}), site = ivec({}), assignments = ivec({})}, entity_raw = {positions = ivec({})}}
local HFS, UNITS, CITS = {}, {}, {}
local SKN = {'ORGANIZATION', 'RECORD_KEEPING', 'APPRAISAL', 'NEGOTIATION', 'PERSUASION', 'JUDGING_INTENT', 'DIAGNOSE',
             'OBSERVATION', 'MELEE_COMBAT', 'DISCIPLINE', 'LEADERSHIP', 'MILITARY_TACTICS', 'CONVERSATION'}
local SK = {}
for i, n in ipairs(SKN) do SK[n] = i end
local function unit(id, talk, kw)
  kw = kw or {}
  local hf = {id = 890 + id, unit_id = id, entity_links = ivec({}), name = 'Dwarf' .. id}
  HFS[hf.id] = hf
  local sk = {}
  for i = 1, #SKN do table.insert(sk, {id = i, rating = (kw.sk and kw.sk[SKN[i]]) or talk}) end
  local u = {id = id, hist_figure_id = hf.id, military = {squad_id = kw.squad or -1}, mood = -1,
             status = {current_soul = {skills = ivec(sk)}}, child = kw.child, occupations = ivec({}),
             body = {wounds = ivec({})}, health = nil, relationship_ids = {Mother = -1}, flags1 = {}, flags2 = {},
             job = {current_job = nil}}
  UNITS[id] = u; table.insert(CITS, u)
  return u, hf
end
local function hold(uid, pid)
  local a = {id = FORT.positions.next_assignment_id, position_id = pid, histfig = UNITS[uid].hist_figure_id,
             flags = {active = true}, squad_id = -1}
  FORT.positions.next_assignment_id = a.id + 1
  FORT.positions.assignments:insert('#', a)
  HFS[a.histfig].entity_links:insert('#', {assignment_id = a.id, entity_id = 50, start_year = 250, link_strength = 100})
  return a
end
unit(11, 5); unit(12, 3); unit(13, 6); unit(14, 9); unit(15, 4); unit(16, 7); unit(17, 12, {squad = 5})
hold(11, 1); hold(12, 2); hold(13, 3); hold(14, 4); hold(15, 5); hold(16, 6); hold(17, 8)
local W = {FORT = FORT, CIV = CIV, HFS = HFS, UNITS = UNITS, CITS = CITS, P = P, pos = pos, ivec = ivec,
           unit = unit, hold = hold, BLIND = {}, T = function() return {} end}
env.W = W
env.df = {global = {cur_year = 256, cur_year_tick = 0, hist_event_next_id = 1, world = {history = {events = ivec({})}},
                    plotinfo = {group_id = 50, civ_id = 40, site_id = 1, caravans = ivec({})}},
          historical_entity = {find = function(id) if id == 50 then return FORT elseif id == 40 then return CIV end end},
          job_skill = SK, entity_position_responsibility = {DELIVER_MESSAGES = 40},
          entity_position_assignment = {new = function() return {flags = {}} end},
          histfig_entity_link_positionst = {is_instance = function(self, l) return l.assignment_id ~= nil and not l.former end},
          histfig_entity_link_former_positionst = {former = true},
          history_event_add_hf_entity_linkst = {}, history_event_remove_hf_entity_linkst = {remove = true},
          histfig_entity_link_type = {POSITION = 1},
          caravan_state = {T_trade_state = {None = 0, Approaching = 1, AtDepot = 2, Leaving = 3, Stuck = 4}},
          job_type = {[7] = 'ManageWorkOrders', [8] = 'TradeAtDepot'},
          historical_figure = {find = function(id) return HFS[id] end},
          unit = {find = function(id) return UNITS[id] end}}
local function position_of(id) for _, p in ipairs0(FORT.positions.own) do if p.id == id then return p end end end
env.dfhack = {units = {getNoblePositions = function(u)
                  local hf = HFS[u.hist_figure_id]; local out = {}
                  if W.BLIND[hf.id] then return out end
                  -- (r11 n1 fixes) as DFHack's Units.cpp: each position link's entity, its
                  -- assignment by id and the post; the slot's holder is not checked
                  for _, l in ipairs0(hf.entity_links) do
                    local ent = env.df.historical_entity.find(l.entity_id)
                    if not l.former and ent then
                      for _, a in ipairs0(ent.positions.assignments) do
                        if a.id == l.assignment_id then
                          for _, p in ipairs0(ent.positions.own) do
                            if p.id == a.position_id then table.insert(out, {position = p, entity = ent, assignment = a}) end
                          end
                        end
                      end
                    end
                  end
                  return out end,
                getReadableName = function(u) return 'Dwarf' .. u.id end,
                isChild = function(u) return u.child == true end, isBaby = function() return false end,
                getStressCategory = function() return 4 end,
                getCitizens = function() local l = {}; for i, u in ipairs(CITS) do l[i] = u end; return l end},
              translation = {translateName = function(n) return n end}}
assert(load(setup or '', 'setup', 't', env))()
assert(load(src, 'ai-nobles', 't', env))()
env.MESSENGER_HOLD = false   -- (r14 hold) these tests check the appointment itself
W.RUN = nil
local real_req = env.reqscript
env.reqscript = function(n, ...)
  if n == 'ai-mission-send' then return {RUN = W.RUN} end
  return real_req(n, ...)
end
return env
"""


def world(setup: str = ""):
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(FAKE, module_src("ai-nobles.lua"), setup)


def _table(env, d):
    t = env.W.T()                            # a Lua table
    for k, v in d.items():
        t[k] = v
    return t


def holders(env) -> dict:
    """position code -> [unit ids] holding it, as DFHack (getNoblePositions) sees it."""
    out = {}
    for uid in sorted(env.W.UNITS.keys()):
        u = env.W.UNITS[uid]
        lst = env.dfhack.units.getNoblePositions(u)
        for i in range(1, len(lst) + 1):
            out.setdefault(lst[i].position.code, []).append(uid)
    return out


def snapshot(env) -> tuple:
    a = env.W.FORT.positions.assignments
    links = tuple((k, env.W.HFS[k].entity_links.n) for k in sorted(env.W.HFS.keys()))
    return (a.n, env.W.FORT.positions.next_assignment_id, tuple(a[i].histfig for i in range(a.n)), links,
            env.df["global"].hist_event_next_id)


def messenger_of(env):
    return holders(env).get("MESSENGER", [])


def appoint_interim(env):
    return env.appoint("MESSENGER", False, None, _table(env, {"interim": True}))


def _run(env, code: str):
    """Run Lua in the world's env (its W, df, dfhack)."""
    env.load(code, "t", "t", env)()


def _list(env, rows):
    t = _table(env, {})
    for i, r in enumerate(rows, 1):
        rr = dict(r)
        for k in ("skills", "codes"):
            if k in rr:
                sub = _table(env, {})
                for j, x in enumerate(rr[k], 1):
                    sub[j] = x
                rr[k] = sub
        t[i] = _table(env, rr)
    return t


# ---- 1. the interim messenger ----------------------------------------------------------------------

@test("7 founders all with offices: nobody suitable; the bookkeeper (least needed) doubles as messenger, not the leader or soldier")
def _():
    env = world()
    st = env.messenger_status(None)
    assert st.why.startswith("post exists, nobody suitable"), st.why
    assert st.interim_possible is True and st.interim_unit == 13 and st.interim_office == "BOOKKEEPER", dict(st)
    before = snapshot(env)
    plain = env.appoint("MESSENGER", False, None)          # without interim: refused as before, nothing written
    assert plain.ok is False and "interim" in plain.error, dict(plain)
    assert snapshot(env) == before
    a = appoint_interim(env)
    assert a.ok is True and a.unit_id == 13 and a.interim is True and a.keeps == "BOOKKEEPER", dict(a)
    h = holders(env)
    assert h["MESSENGER"] == [13] and h["BOOKKEEPER"] == [13] and h["EXPEDITION_LEADER"] == [11], h
    st = env.messenger_status(None)
    assert st.why is None and st.interim is True and st.holder_unit == 13 and st.free_unit is None, dict(st)
    s = env.survey(None)
    assert s.messenger.interim is True and s.messenger.holder_unit == 13, dict(s.messenger)


@test("interim: the unfit bookkeeper (wounded) passes to the broker; one also leading the expedition never; the best talker within an office")
def _():
    env = world("W.UNITS[13].body.wounds:insert('#', {id = 1})")
    st = env.messenger_status(None)
    assert st.interim_unit == 14 and st.interim_office == "BROKER", dict(st)
    # the bookkeeper also the expedition leader: never (the leader stays home)
    env = world("W.hold(13, 1)")
    assert env.messenger_status(None).interim_unit == 14
    # two bookkeepers' tier: the better talker of the two (pure)
    c, code = env.pick_interim(_list(env, [
        {"id": 1, "skills": [2, 2], "offices": 1, "codes": ["BOOKKEEPER"]},
        {"id": 2, "skills": [8, 1], "offices": 1, "codes": ["BOOKKEEPER"]},
        {"id": 3, "skills": [20, 20], "offices": 1, "codes": ["MANAGER"]},
        {"id": 4, "skills": [20, 20], "offices": 1, "codes": ["MILITIA_COMMANDER"]},
        {"id": 5, "skills": [20, 20], "offices": 1, "codes": ["BOOKKEEPER"], "soldier": True}]))
    assert c.id == 2 and code == "BOOKKEEPER", (c.id, code)


@test("interim: only the leader and the militia hold offices and the rest are unfit: no interim possible")
def _():
    env = world("for _, id in ipairs({12, 13, 14, 15, 16}) do W.UNITS[id].military.squad_id = 6 end")
    st = env.messenger_status(None)
    assert st.why.startswith("post exists, nobody suitable") and st.interim_possible is False, dict(st)
    before = snapshot(env)
    a = appoint_interim(env)
    assert a.ok is False and snapshot(env) == before, dict(a)


# ---- 2. the interim swapped out ----------------------------------------------------------------------

def with_interim(setup: str = ""):
    env = world(setup)
    assert appoint_interim(env).ok is True
    return env


@test("swap-out: a suitable free citizen arrives: the interim bookkeeper steps down, keeps the bookkeeping; history noted")
def _():
    env = with_interim()
    env.W.unit(18, 2)                                       # a poor talker, but free and suitable
    st = env.messenger_status(None)
    assert st.interim is True and st.free_unit == 18 and st.away is None, dict(st)
    ev = env.df["global"].hist_event_next_id
    r = env.appoint("MESSENGER", False, None, _table(env, {"replace": True, "interim_out": True}))
    assert r.ok is True and r.unit_id == 18 and r.replaced_unit == 13 and r.interim_out is True, dict(r)
    h = holders(env)
    assert h["MESSENGER"] == [18] and h["BOOKKEEPER"] == [13], h
    # DFHack's removal: a former-position link on the old holder and a remove event (the new one's add event too)
    links = env.W.HFS[903].entity_links
    assert any(links[i].former for i in range(links.n)), "no former-position link"
    assert sum(1 for i in range(links.n) if not links[i].former) == 1      # the messenger's link gone, the bookkeeper's kept
    assert env.df["global"].hist_event_next_id == ev + 2
    st = env.messenger_status(None)
    assert st.held_by == "Dwarf18" and not st.interim, dict(st)


@test("swap-out: never while the messenger is away (an army's roll, off the map) or a mission is being sent")
def _():
    for setup, word in (("W.HFS[903].info = {whereabouts = {army_id = 3}}", "army"),
                        ("W.UNITS[13].flags1.inactive = true", "off the map"),
                        ("W.RUN = {goal = 'make_contact'}", "being sent")):
        env = with_interim()
        env.W.unit(18, 2)
        _run(env, setup)
        st = env.messenger_status(None)
        assert st.away and word in st.away, (word, dict(st))
        before = snapshot(env)
        r = env.appoint("MESSENGER", False, None, _table(env, {"replace": True, "interim_out": True}))
        assert r.ok is False and r.busy and word in r.busy, (word, dict(r))
        assert snapshot(env) == before and messenger_of(env) == [13]


# ---- 3. better holders in general ------------------------------------------------------------------

def manager_world(org: int):
    # the manager (12): ORGANIZATION 2, RECORD_KEEPING 0 -> 2*2 + 0 = 4; a free newcomer 18
    env = world("W.UNITS[12].status.current_soul.skills[0].rating = 2; W.UNITS[12].status.current_soul.skills[1].rating = 0")
    env.W.unit(18, 0)
    _run(env, f"W.UNITS[18].status.current_soul.skills[0].rating = {org}")
    return env


def replace_manager(env, dry=False):
    return env.appoint("MANAGER", dry, None, _table(env, {"replace": True, "margin_add": CFG["n1_swap_margin_add"],
                                                         "margin_factor": CFG["n1_swap_margin_factor"]}))


@test("better holder: vastly better (skill 4 -> 16, 14 needed) replaces the manager; slightly better (4 -> 12) doesn't")
def _():
    env = manager_world(6)                                  # 2*6 = 12 < max(4 + 10, 8) = 14
    before = snapshot(env)
    r = replace_manager(env)
    assert r.ok is False and "not vastly better" in r.error and r.holder_score == 4 and r.cand_score == 12, dict(r)
    assert snapshot(env) == before
    env = manager_world(8)                                  # 16 >= 14
    sw = env.survey(None).swap.MANAGER
    assert sw.holder_unit == 12 and sw.holder_score == 4 and sw.cand_unit == 18 and sw.cand_score == 16, dict(sw)
    r = replace_manager(env)
    assert r.ok is True and r.unit_id == 18 and r.replaced_unit == 12, dict(r)
    assert holders(env)["MANAGER"] == [18]
    sw_mod = env.reqscript("ai-nobles-swap")
    assert sw_mod.needed(4, 10, 2.0) == 14 and sw_mod.needed(20, 10, 2.0) == 40 and sw_mod.needed(0, 10, 2.0) == 10


@test("better holder: an elected post, a holder in a mood, mid-job, or the broker while a caravan is here: untouched")
def _():
    env = manager_world(15)
    _run(env, "W.P.MANAGER.flags.ELECTED = true")
    assert env.survey(None).swap.MANAGER.fixed == "elected"
    before = snapshot(env)
    r = replace_manager(env)
    assert r.ok is False and "not the fort's to fill" in r.error and snapshot(env) == before, dict(r)
    for setup, word in (("W.UNITS[12].mood = 0", "mood"), ("W.UNITS[12].job.current_job = {job_type = 7}", "ManageWorkOrders")):
        env = manager_world(15)
        _run(env, setup)
        before = snapshot(env)
        r = replace_manager(env)
        assert r.ok is False and word in r.busy and snapshot(env) == before, (word, dict(r))
    env = world("W.UNITS[14].status.current_soul.skills[2].rating = 0")
    env.W.unit(18, 20)
    _run(env, "df.global.plotinfo.caravans:insert('#', {trade_state = 2})")
    r = env.appoint("BROKER", False, None, _table(env, {"replace": True}))
    assert r.ok is False and "caravan" in r.busy, dict(r)


@test("better holder: the new write fails (DFHack doesn't see it): the old holder is put back as they were")
def _():
    env = manager_world(15)
    before = snapshot(env)
    _run(env, "W.BLIND[908] = true")                       # the newcomer's figure: DFHack sees no office of theirs
    r = replace_manager(env)
    assert r.ok is False and r.restored is True and "put back" in r.error, dict(r)
    _run(env, "W.BLIND[908] = nil")
    assert holders(env)["MANAGER"] == [12] and snapshot(env) == before, (holders(env), snapshot(env), before)


@test("dry runs change nothing: the interim, the swap-out, the better holder")
def _():
    env = world()
    before = snapshot(env)
    d = env.appoint("MESSENGER", True, None, _table(env, {"interim": True}))
    assert d.ok is True and d.dry_run is True and d.unit_id == 13 and d.interim is True, dict(d)
    assert snapshot(env) == before
    env = with_interim()
    env.W.unit(18, 2)
    before = snapshot(env)
    d = env.appoint("MESSENGER", True, None, _table(env, {"replace": True, "interim_out": True}))
    assert d.ok is True and d.dry_run is True and d.unit_id == 18, dict(d)
    assert snapshot(env) == before
    env = manager_world(15)
    before = snapshot(env)
    d = replace_manager(env, dry=True)
    assert d.ok is True and d.dry_run is True and snapshot(env) == before, dict(d)
    env.survey(None)
    env.messenger_status(None)
    assert snapshot(env) == before                         # the reads write nothing


@test("the swap module only replaces civilian offices; the leader's and the militia's are refused")
def _():
    env = world()
    for code in ("MILITIA_COMMANDER", "EXPEDITION_LEADER"):
        r = env.appoint(code, False, None, _table(env, {"replace": True}))
        assert r.ok is False and r.rejected, (code, dict(r))


# ---- 4. the planner --------------------------------------------------------------------------------

def state(messenger=None, offices=None, swap=None, tick=10 * DAY, **kw):
    s = {"settings": {"make_contact": True, "appoint_nobles": True, "send_messenger": True},
         "dwarves": {"total": 7}, "stocks": {"drink": 2000, "prepared_meals": 2000},
         "buildings": {"other": {"FarmPlot": 4}},
         "offices": {"offices": offices or {}, "messenger": messenger or {}, "swap": swap or {}},
         "missions": {"controllers": [], "send": {}},
         "date": {"year": 256, "tick": tick}}
    s.update(kw)
    return s


NOBODY = "post exists, nobody suitable to appoint (soldiers, office holders, staff, patients, the wounded, mothers of babies and children stay home)"
EMPTY = {"MESSENGER": {"vacant": 0, "held": [], "slots": 0, "no_slot": True, "appointable": True}}


@test("planner: nobody suitable and no interim possible: no proposal (the refused appointment isn't re-proposed), a note")
def _():
    s = state({"position": True, "post": "fort", "why": NOBODY, "interim_possible": False}, EMPTY)
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert not props and any("nobody can be the messenger" in n for n in notes), (props, notes)


@test("planner: nobody suitable but an interim possible: the interim proposed (bookkeeper named); the plain case as before")
def _():
    s = state({"position": True, "post": "fort", "why": NOBODY, "interim_possible": True, "interim_unit": 13,
               "interim_name": "Urist", "interim_office": "BOOKKEEPER"}, EMPTY)
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert props and props[0].action == {"type": "appoint", "office": "MESSENGER", "interim": True}, props
    assert "Urist, the bookkeeper" in props[0].reason
    assert short(props[0].action).startswith("let an office holder double as messenger")
    s = state({"position": True, "post": "fort", "why": "post exists, nobody appointed"}, EMPTY)
    props = []
    planner_world._messenger_rule(s, CFG, props, [])
    assert props[0].action == {"type": "appoint", "office": "MESSENGER"}


HELD = {"MESSENGER": {"vacant": 0, "held": ["Urist"], "slots": 1}}
INTERIM = {"position": True, "post": "fort", "held_by": "Urist", "interim": True, "holder_unit": 13,
           "free_unit": 18, "free_name": "Kib"}


@test("planner: an interim messenger and a free suitable one: swapped out (its own rule and label)")
def _():
    props, notes = [], []
    OS._office_swap_rule(state(INTERIM, HELD), CFG, props, notes, Memory())
    assert len(props) == 1 and props[0].rule == "office_swap", (props, notes)
    assert props[0].action == {"type": "appoint", "office": "MESSENGER", "replace": True, "interim_out": True}
    assert "Urist" in props[0].reason and "Kib" in props[0].reason
    assert short(props[0].action).startswith("give the messenger's post to a free, suitable dwarf")
    assert H.RULE_CLASS["office_swap"] == H.RULE_CLASS["appoint"] == H.RULE_CLASS["messenger"]


@test("planner: not while the messenger is away, a run is being sent, a Diplomacy mission is out, a threat or a crisis")
def _():
    cases = [state(dict(INTERIM, away="off the map"), HELD),
             state(INTERIM, HELD, missions={"send": {"running": {"goal": "make_contact"}}}),
             state(INTERIM, HELD, missions={"controllers": [{"id": 4, "goal": "DIPLOMACY"}]}),
             state(INTERIM, HELD, others_on_map={"threats_that_can_reach_dwarves": 2})]
    for s in cases:
        props = []
        OS._office_swap_rule(s, CFG, props, [], Memory())
        assert not props, (s.get("missions"), props)
    m = Memory()
    m.crisis = {"since": 1, "why": ["deaths"]}
    props = []
    OS._office_swap_rule(state(INTERIM, HELD), CFG, props, [], m)
    assert not props


def swap_state(hs, cs, code="MANAGER", tick=10 * DAY, **o):
    row = {"holder": "Urist", "holder_unit": 12, "holder_score": hs, "cand": "Kib", "cand_unit": 18,
           "cand_score": cs}
    row.update(o)
    return state({}, {}, {code: row}, tick=tick)


@test("planner: a vastly better candidate replaces (skill a -> b said); a slightly better one, a fixed post, a busy holder don't")
def _():
    props = []
    OS._office_swap_rule(swap_state(4, 16), CFG, props, [], Memory())
    assert props and props[0].action["replace"] is True and props[0].action["office"] == "MANAGER", props
    assert "skill 4 -> 16" in props[0].reason and "Kib" in props[0].reason and "Urist" in props[0].reason
    assert short(props[0].action) == "give the manager's post to a far better-suited dwarf"
    for s in (swap_state(4, 13), swap_state(20, 39), swap_state(4, 30, fixed="elected"),
              swap_state(4, 30, busy="in a strange mood")):
        props, notes = [], []
        OS._office_swap_rule(s, CFG, props, notes, Memory())
        assert not props, (s["offices"]["swap"], props)
    assert OS.swap_needed(0, CFG) == 10 and OS.swap_needed(6, CFG) == 16 and OS.swap_needed(30, CFG) == 60


@test("planner: a season per office (cooldown_key office_swap:<CODE>) and one swap a day fort-wide")
def _():
    now = abs_tick(swap_state(4, 16, tick=200 * DAY))
    p = Proposal("office_swap", {"type": "appoint", "office": "MANAGER", "replace": True}, "", 5)
    assert cooldown_key(p) == "office_swap:MANAGER"
    assert CFG[COOLDOWN_KEYS.get("office_swap", "office_swap_cooldown_ticks")] == 84 * DAY
    m = Memory()
    m.last_fired = {"office_swap:MANAGER": now - 30 * DAY}       # a month ago: the manager waits its season
    props = []
    OS._office_swap_rule(swap_state(4, 16, tick=200 * DAY), CFG, props, [], m)
    assert not props
    m.last_fired = {"office_swap:MANAGER": now - 90 * DAY}       # past the season
    props = []
    OS._office_swap_rule(swap_state(4, 16, tick=200 * DAY), CFG, props, [], m)
    assert props
    m.last_fired = {"office_swap:BROKER": now - DAY // 2}         # another office swapped today: none now
    props = []
    OS._office_swap_rule(swap_state(4, 16, tick=200 * DAY), CFG, props, [], m)
    assert not props


# ---- (r11 n1 fixes) the verifier's findings ----------------------------------------------------------

def links_of(env, hf):
    L = env.W.HFS[hf].entity_links
    return [(L[i].entity_id, L[i].assignment_id, bool(L[i].former), L[i].tag) for i in range(L.n)]


@test("M1: a holder's post in another entity with the same assignment id survives the swap and a failed write")
def _():
    for blind in (False, True):
        env = manager_world(15)
        _run(env, "W.HFS[902].entity_links:insert('#', {assignment_id = 1, entity_id = 40, start_year = 200,"
                  " link_strength = 100, tag = 'civ'})")
        if blind:
            _run(env, "W.BLIND[908] = true")
        r = replace_manager(env)
        assert r.ok is (not blind), dict(r)
        assert any(e == 40 and t == "civ" for e, a, f, t in links_of(env, 902)), (blind, links_of(env, 902))
    # undo_appointment (the plain appoint's undo) by entity too
    env = world()
    _run(env, "W.HFS[908] = nil; W.unit(18, 2); W.HFS[908].entity_links:insert('#', {assignment_id = 1, entity_id = 40, tag = 'civ'});"
              " local a = W.FORT.positions.assignments[1]; W.HFS[908].entity_links:insert('#', {assignment_id = 1, entity_id = 50});"
              " undo_appointment(a, W.HFS[908])")
    assert links_of(env, 908) == [(40, 1, False, "civ")], links_of(env, 908)


@test("M2: the captain of the guard (its slot leads a squad) and the sheriff are never swapped; no soldier candidate")
def _():
    env = world("""
W.P.CAPTAIN_OF_THE_GUARD = W.pos{id = 9, code = 'CAPTAIN_OF_THE_GUARD', appointed_by = W.ivec({1})}
W.FORT.positions.own:insert('#', W.P.CAPTAIN_OF_THE_GUARD)
W.unit(19, 1, {squad = 7})
local a = W.hold(19, 9); a.squad_id = 7
W.unit(18, 0, {sk = {JUDGING_INTENT = 18, MELEE_COMBAT = 15, LEADERSHIP = 15, DISCIPLINE = 15}})
""")
    sw = env.survey(None).swap
    assert sw.CAPTAIN_OF_THE_GUARD is None and sw.SHERIFF is None, (sw.CAPTAIN_OF_THE_GUARD, sw.SHERIFF)
    before = snapshot(env)
    for code in ("CAPTAIN_OF_THE_GUARD", "SHERIFF"):
        r = env.appoint(code, False, None, _table(env, {"replace": True}))
        assert r.ok is False and r.rejected, (code, dict(r))
    assert snapshot(env) == before
    # a manager's slot that leads a squad: fixed, refused
    env = manager_world(15)
    _run(env, "W.FORT.positions.assignments[1].squad_id = 3")
    assert env.survey(None).swap.MANAGER.fixed == "leads a squad"
    r = replace_manager(env)
    assert r.ok is False and "leads a squad" in r.error, dict(r)
    # a soldier is never the newcomer
    env = manager_world(15)
    _run(env, "W.UNITS[18].military.squad_id = 4")
    assert env.survey(None).swap.MANAGER.cand_unit is None
    assert OS.SWAP_ORDER == ("MANAGER", "CHIEF_MEDICAL_DWARF", "BROKER", "BOOKKEEPER", "MESSENGER")


@test("M3: a miserable free dwarf is not offered as the interim's successor (messenger_status picks as replace does)")
def _():
    env = world("dfhack.units.getStressCategory = function(u) if u.id == 18 then return 0 end return 4 end")
    assert appoint_interim(env).ok
    env.W.unit(18, 6)
    st = env.messenger_status(None)
    assert st.interim is True and st.free_unit is None, dict(st)


@test("M3: a refused swap backs off only its own office; a refused interim swap-out lets a better holder through")
def _():
    from planner_core_refusals import refusal_key
    pm = Proposal("office_swap", {"type": "appoint", "office": "MANAGER", "replace": True}, "", 5)
    pb = Proposal("office_swap", {"type": "appoint", "office": "BROKER", "replace": True}, "", 5)
    pi = Proposal("office_swap", {"type": "appoint", "office": "MESSENGER", "replace": True, "interim_out": True}, "", 4)
    assert len({refusal_key(pm), refusal_key(pb), refusal_key(pi)}) == 3
    s = state(INTERIM, HELD, swap={"MANAGER": {"holder": "Urist", "holder_unit": 12, "holder_score": 4,
                                               "cand": "Kib", "cand_unit": 19, "cand_score": 16}})
    m = Memory()
    m.refusals = {refusal_key(pi): {"until": abs_tick(s) + 3 * DAY, "n": 1}}
    props = []
    OS._office_swap_rule(s, CFG, props, [], m)
    assert len(props) == 1 and props[0].action["office"] == "MANAGER" and not props[0].action.get("interim_out"), props


@test("L1: an error inside the new write: the old holder is put back, nobody left half-appointed")
def _():
    env = manager_world(15)
    _run(env, """
local hf = W.HFS[908]
local real = hf.entity_links.insert
setmetatable(hf.entity_links, {__len = function(self) return self.n end,
  __index = {insert = function(self, pos, x) error('simulated: field not found') end,
             erase = getmetatable(hf.entity_links).__index.erase}})""")
    before = snapshot(env)
    r = replace_manager(env)
    assert r.ok is False and r.restored is True and "put back" in r.error, dict(r)
    assert holders(env)["MANAGER"] == [12] and snapshot(env) == before


@test("L2: a messenger walking to the map's edge (on an army controller) is away; no messenger swap with the missions report unread")
def _():
    env = with_interim()
    env.W.unit(18, 2)
    _run(env, "W.UNITS[13].enemy = {army_controller_id = 5}")
    st = env.messenger_status(None)
    assert st.away and "off the map" in st.away, dict(st)
    r = env.appoint("MESSENGER", False, None, _table(env, {"replace": True, "interim_out": True}))
    assert r.ok is False and r.busy, dict(r)
    for extra in ({"_errors": {"missions": "timeout"}}, {"missions": {"error": "x"}}):
        s = state(INTERIM, HELD, **extra)
        if "missions" not in extra:
            s.pop("missions")
        props = []
        OS._office_swap_rule(s, CFG, props, [], Memory())
        assert not props, (extra, props)


@test("L3: a failed write puts back the very link objects, in their places")
def _():
    env = with_interim()
    env.W.unit(18, 2)
    _run(env, "local L = W.HFS[903].entity_links; for i = 0, L.n - 1 do L[i].tag = 'orig' .. i end")
    before = links_of(env, 903)
    _run(env, "W.BLIND[908] = true")
    r = env.appoint("MESSENGER", False, None, _table(env, {"replace": True, "interim_out": True}))
    assert r.ok is False and r.restored is True, dict(r)
    assert links_of(env, 903) == before, (links_of(env, 903), before)


@test("L5: interim counts the fort's offices only; a swap with no live link adds no former link; the module is version-marked")
def _():
    env = world()
    _run(env, "W.CIV.positions.own:insert('#', W.pos{id = 70, code = 'GENERAL'});"
              " W.CIV.positions.assignments:insert('#', {id = 0, position_id = 70, histfig = 908});"
              " W.unit(18, 9); W.HFS[908].entity_links:insert('#', {assignment_id = 0, entity_id = 40});"
              " local a = W.hold(18, 7)")
    st = env.messenger_status(None)
    assert st.held_by == "Dwarf18" and not st.interim, dict(st)
    # the manager's slot names a figure with no link: swapped, but no former link and no remove event
    env = manager_world(15)
    _run(env, "local L = W.HFS[902].entity_links; while L.n > 0 do L:erase(0) end")
    ev = env.df["global"].hist_event_next_id
    r = replace_manager(env)
    assert r.ok is True and env.W.HFS[902].entity_links.n == 0, dict(r)
    assert env.df["global"].hist_event_next_id == ev + 1          # the new holder's add event only
    src = (ROOT / "lua" / "ai-nobles-swap.lua").read_text(encoding="utf-8")
    assert "PART_VERSIONS = {['ai-nobles-swap'] = '" in src
    hub = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "'ai-nobles-swap'" in hub.split("MARKED_MODULES = ")[1].split("\n")[0]


@test("L5: a waiting swap's note is said once a day, again when its reason changes")
def _():
    m = Memory()
    s = state(dict(INTERIM, away="off the map"), HELD)
    seen = []
    for tick, away in ((10 * DAY, "off the map"), (10 * DAY + 100, "off the map"), (10 * DAY + 200, "with an army"),
                       (11 * DAY + 300, "with an army")):
        s = state(dict(INTERIM, away=away), HELD, tick=tick)
        notes = []
        OS._office_swap_rule(s, CFG, [], notes, m)
        seen.append(len(notes))
    assert seen == [1, 0, 1, 1], seen


# ---- the sources ------------------------------------------------------------------------------------

CHANGED = ["ai-nobles.lua", "ai-nobles-swap.lua", "ai-bridge-actions-works.lua", "ai-bridge.lua"]


@test("every changed Lua file compiles under Lua 5.3 and stays under 60 KB; the swap module is a bridge module")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    check = lua.eval("function(src, name) local f, e = load(src, name, 't', {}); return f ~= nil, e end")
    for n in CHANGED:
        src = (ROOT / "lua" / n).read_text(encoding="utf-8")
        ok, err = check(src, n)
        assert ok, (n, err)
        assert len(src.encode("utf-8")) < 60 * 1024, n
    assert "'ai-nobles-swap'" in (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    works = (ROOT / "lua" / "ai-bridge-actions-works.lua").read_text(encoding="utf-8")
    assert "interim = a.interim == true" in works and "replace = a.replace == true" in works


if __name__ == "__main__":
    finish()
