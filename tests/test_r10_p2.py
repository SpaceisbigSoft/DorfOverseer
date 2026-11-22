"""(r10 p2, Phase 13b) A messenger's post, so missions can be sent.

No fort had a messenger (21 Nov audit B2): the sender stopped at "the fort
has no messenger's post". lua/ai-nobles.lua now finds the post by its code or
its duty (DELIVER_MESSAGES), says why nobody carries the fort's word
(`offices.messenger.why`, `missions.messenger.why`), never writes a post DF
hasn't given, and appoints a suitable citizen once the post is there.

    python tests/test_r10_p2.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import PLANNER_CONFIG  # noqa: E402
import planner_world  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG

# A fort: the expedition leader (held), a manager (held by dwarf 13, the best
# talker), and per test a messenger's post (or none) and the civilisation's
# lists. Citizens: 11 a soldier (good talker), 12 a civilian talker, 13 the
# manager, 14 a child, 15 a poor talker. `setup` (Lua) shapes the world.
FAKE = r"""
local src, setup = ...
local env = setmetatable({}, {__index = _G})
local function ivec(t)       -- a 0-based vector
  local v = {n = #t}
  for i, x in ipairs(t) do v[i - 1] = x end
  return setmetatable(v, {__len = function(self) return self.n end,
    __index = {insert = function(self, pos, x) self[self.n] = x; self.n = self.n + 1 end,
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
local DUTY = 40
local function pos(t)
  t.appointed_by = t.appointed_by or ivec({}); t.flags = t.flags or {}; t.responsibilities = t.responsibilities or {}
  t.number = t.number or 1; t.requires_population = t.requires_population or 0
  return t
end
local LEADER = pos{id = 1, code = 'EXPEDITION_LEADER'}
local MANAGER = pos{id = 2, code = 'MANAGER', appointed_by = ivec({1})}
local FORT = {id = 50, positions = {own = ivec({LEADER, MANAGER}), site = ivec({}),
              assignments = ivec({{id = 0, position_id = 1, histfig = 900, flags = {active = true}, squad_id = -1},
                                  {id = 1, position_id = 2, histfig = 903, flags = {active = true}, squad_id = -1}}),
              next_assignment_id = 2}, assignments_by_type = ivec({})}
local CIV = {id = 40, positions = {own = ivec({}), site = ivec({})}, entity_raw = {positions = ivec({})}}
local HFS, UNITS, CITS = {}, {}, {}
local SK = {PERSUASION = 1, NEGOTIATION = 2, CONVERSATION = 3, JUDGING_INTENT = 4}
local function unit(id, talk, kw)
  kw = kw or {}
  local hf = {id = 890 + id, unit_id = id, entity_links = ivec({}), name = 'Dwarf' .. id}
  HFS[hf.id] = hf
  local u = {id = id, hist_figure_id = hf.id, military = {squad_id = kw.squad or -1}, mood = -1,
             status = {current_soul = {skills = ivec({{id = 1, rating = talk}, {id = 2, rating = talk}})}},
             child = kw.child, occupations = ivec({}), body = {wounds = ivec({})}, health = nil,
             relationship_ids = {Mother = -1}, flags1 = {}, flags2 = {}}
  UNITS[id] = u; table.insert(CITS, u)
  return u, hf
end
unit(11, 18, {squad = 5}); unit(12, 9); unit(13, 20); unit(14, 15, {child = true}); unit(15, 2)
-- the leader's and the manager's figures (900: not a citizen; 903: dwarf 13)
HFS[900] = {id = 900, unit_id = -1, entity_links = ivec({}), name = 'Leader'}
local MGR_HF = HFS[903]
MGR_HF.entity_links:insert('#', {assignment_id = 1, entity_id = 50})
local W = {FORT = FORT, CIV = CIV, HFS = HFS, UNITS = UNITS, CITS = CITS, DUTY = DUTY, pos = pos, ivec = ivec}
env.W = W
env.df = {global = {cur_year = 256, cur_year_tick = 0, hist_event_next_id = 1, world = {history = {events = ivec({})}},
                    plotinfo = {group_id = 50, civ_id = 40, site_id = 1}},
          historical_entity = {find = function(id) if id == 50 then return FORT elseif id == 40 then return CIV end end},
          job_skill = SK, entity_position_responsibility = {DELIVER_MESSAGES = DUTY},
          entity_position_assignment = {new = function() return {flags = {}} end},
          histfig_entity_link_positionst = {is_instance = function(l) return l.assignment_id ~= nil end},
          history_event_add_hf_entity_linkst = {}, histfig_entity_link_type = {POSITION = 1},
          historical_figure = {find = function(id) return HFS[id] end},
          unit = {find = function(id) return UNITS[id] end}}
local function position_of(id) for _, p in ipairs0(FORT.positions.own) do if p.id == id then return p end end end
env.dfhack = {units = {getNoblePositions = function(u)
                  local hf = HFS[u.hist_figure_id]; local out = {}
                  for _, l in ipairs0(hf.entity_links) do
                    for _, a in ipairs0(FORT.positions.assignments) do
                      if a.id == l.assignment_id and a.histfig == hf.id then table.insert(out, {position = position_of(a.position_id)}) end
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
return env
"""

# the fort's own messenger's post (AS_NEEDED: no slot yet), appointed by the leader
POST = "W.FORT.positions.own:insert('#', W.pos{id = 7, code = 'MESSENGER', appointed_by = W.ivec({1}), number = -1})"


def world(setup: str = ""):
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(FAKE, module_src("ai-nobles.lua"), setup)


def snapshot(env) -> tuple:
    a = env.W.FORT.positions.assignments
    links = tuple(env.W.HFS[k].entity_links.n for k in sorted(env.W.HFS.keys()))
    return (a.n, env.W.FORT.positions.next_assignment_id, tuple(a[i].histfig for i in range(a.n)), links,
            env.df["global"].hist_event_next_id)


# ---- post absent: the why ------------------------------------------------------------------------

@test("absent: the civilisation's site template needs 20 dwarves, the fort has 5: 'no post until population 20 (now 5)'")
def _():
    env = world("W.CIV.positions.site:insert('#', W.pos{id = 30, code = 'MESSENGER', requires_population = 20})")
    st = env.messenger_status(None)
    assert st.post == "civ_site" and st.why == "no post until population 20 (now 5)", dict(st)
    r = env.survey(None)
    assert r.messenger.position is False and r.messenger.why == st.why and r.offices.MESSENGER is None, dict(r.messenger)
    before = snapshot(env)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False and a.rejected and a.why == st.why, dict(a)
    assert snapshot(env) == before                 # nothing written: no post is ever made


@test("absent: a template whose population is reached, DF's raws only, the civilisation's own post, or none: each said")
def _():
    env = world("W.CIV.positions.site:insert('#', W.pos{id = 30, code = 'MESSENGER', requires_population = 4})")
    st = env.messenger_status(None)
    assert st.post == "civ_site" and "DF has not given it to this fort" in st.why and "population 4" in st.why, st.why
    # found by its duty in the raws (another code)
    env = world("local r = W.pos{code = 'COURIER', requires_population = 30}; r.responsibilities[W.DUTY] = true;"
                "W.CIV.entity_raw.positions:insert('#', r)")
    st = env.messenger_status(None)
    assert st.post == "raw" and st.code == "COURIER" and st.why == "no post until population 30 (now 5)", dict(st)
    env = world("W.CIV.positions.own:insert('#', W.pos{id = 31, code = 'MESSENGER'})")
    st = env.messenger_status(None)
    assert st.post == "civ" and "civilisation's post" in st.why, dict(st)
    env = world()
    st = env.messenger_status(None)
    assert st.post == "none" and st.why == "no post: this civilisation has no messenger position", dict(st)


@test("absent: the planner says why in a note and proposes nothing")
def _():
    s = {"settings": {"make_contact": True, "appoint_nobles": True, "send_messenger": False},
         "dwarves": {"total": 40}, "stocks": {"drink": 2000, "prepared_meals": 2000},
         "buildings": {"other": {"FarmPlot": 4}},
         "offices": {"offices": {}, "messenger": {"position": False, "post": "civ_site",
                                                  "why": "no post until population 20 (now 5)"}},
         "date": {"year": 256, "tick": 1000}}
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert not props and any("no post until population 20 (now 5)" in n for n in notes), notes
    # the missions report's why when the offices carry none
    s["offices"] = {"offices": {}}
    s["missions"] = {"messenger": {"why": "no post: this civilisation has no messenger position"}}
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert not props and any("this civilisation has no messenger position" in n for n in notes), notes


@test("absent: a post in the fort's list that DF hasn't opened (population 30 not met) is not filled")
def _():
    env = world("W.FORT.positions.own:insert('#', W.pos{id = 7, code = 'MESSENGER', appointed_by = W.ivec({1}),"
                " number = -1, requires_population = 30, flags = {HAS_MET_POP_REQ = false}})")
    st = env.messenger_status(None)
    assert st.post == "fort" and st.appointable is False and st.why == "no post until population 30 (now 5)", dict(st)
    r = env.survey(None)
    assert r.offices.MESSENGER.appointable is False and "population 30" in r.offices.MESSENGER.not_why
    before = snapshot(env)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False and "population 30" in a.error, dict(a)
    assert snapshot(env) == before


# ---- post present and empty: appointed ------------------------------------------------------------

@test("present, empty: 'post exists, nobody appointed'; the civilian talker appointed (soldier, manager, child skipped)")
def _():
    env = world(POST)
    st = env.messenger_status(None)
    assert st.post == "fort" and st.slots == 0 and st.appointable is True and st.why == "post exists, nobody appointed", dict(st)
    assert list(st.appointed_by.values()) == ["EXPEDITION_LEADER"], dict(st)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is True and a.unit_id == 12 and a.slot_added is True, dict(a)
    fp = env.W.FORT.positions
    assert fp.assignments.n == 3 and fp.assignments[2].histfig == 902 and fp.assignments[2].position_id == 7
    assert env.W.HFS[902].entity_links.n == 1 and env.W.HFS[902].entity_links[0].assignment_id == fp.assignments[2].id
    st = env.messenger_status(None)
    assert st.why is None and st.held_by == "Dwarf12", dict(st)


@test("present, empty: a post found by its duty (DELIVER_MESSAGES) under another code is read and filled as MESSENGER")
def _():
    env = world("local p = W.pos{id = 8, code = 'COURIER', appointed_by = W.ivec({1}), number = -1};"
                "p.responsibilities[W.DUTY] = true; W.FORT.positions.own:insert('#', p)")
    r = env.survey(None)
    assert r.messenger.position is True and r.messenger.code == "COURIER" and r.offices.MESSENGER.no_slot, dict(r.messenger)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is True and a.unit_id == 12, dict(a)
    assert env.W.FORT.positions.assignments[2].position_id == 8


@test("present, empty: nobody suitable (only the soldier, the manager and the child): said, nothing written")
def _():
    env = world(POST + "; W.UNITS[12].military.squad_id = 6; W.UNITS[15].occupations:insert('#', {id = 1})")
    st = env.messenger_status(None)
    assert st.why.startswith("post exists, nobody suitable to appoint"), st.why
    before = snapshot(env)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False, dict(a)
    assert snapshot(env) == before


@test("present, empty: dry run names the dwarf and changes nothing")
def _():
    env = world(POST)
    before = snapshot(env)
    d = env.appoint("MESSENGER", True, None)
    assert d.ok is True and d.dry_run is True and d.unit_id == 12, dict(d)
    assert snapshot(env) == before
    env.survey(None)
    env.messenger_status(None)
    assert snapshot(env) == before                 # the reads write nothing either


@test("present: the planner proposes the appointment (Make contact on); (r10 p3) the sending switches on by default")
def _():
    s = {"settings": {"make_contact": True, "appoint_nobles": True},
         "dwarves": {"total": 40}, "stocks": {"drink": 2000, "prepared_meals": 2000},
         "buildings": {"other": {"FarmPlot": 4}},
         "offices": {"offices": {"MESSENGER": {"vacant": 0, "held": [], "slots": 0, "no_slot": True, "appointable": True}},
                     "messenger": {"position": True, "slots": 0, "post": "fort", "why": "post exists, nobody appointed"}},
         "date": {"year": 256, "tick": 1000}}
    props, notes = [], []
    planner_world._messenger_rule(s, CFG, props, notes)
    assert props and props[0].action == {"type": "appoint", "office": "MESSENGER"}, (props, notes)
    st = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    # (r10 p3, the player 22 Nov: every fort makes initial contact) on by default now
    assert re.search(r"^\s*send_messenger = true,", st, re.M) and re.search(r"^\s*send_missions = true,", st, re.M)


# ---- held: nothing --------------------------------------------------------------------------------

@test("held: no why, the holder named; appoint refuses and writes nothing")
def _():
    env = world(POST + "; W.FORT.positions.assignments:insert('#', {id = 2, position_id = 7, histfig = 905, flags = {},"
                " squad_id = -1}); W.FORT.positions.next_assignment_id = 3;"
                " W.HFS[905].entity_links:insert('#', {assignment_id = 2, entity_id = 50})")
    st = env.messenger_status(None)
    assert st.why is None and st.held_by == "Dwarf15" and st.holder_hf == 905, dict(st)
    before = snapshot(env)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False and "already held" in a.error, dict(a)
    assert snapshot(env) == before


# ---- the sources --------------------------------------------------------------------------------

CHANGED = ["ai-nobles.lua", "ai-mission-send-run.lua", "ai-missions-report.lua", "probes/probe-messenger.lua"]


@test("every changed Lua file compiles under Lua 5.3 and stays under 60 KB")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    check = lua.eval("function(src, name) local f, e = load(src, name, 't', {}); return f ~= nil, e end")
    for n in CHANGED:
        src = (ROOT / "lua" / n).read_text(encoding="utf-8")
        ok, err = check(src, n)
        assert ok, (n, err)
        assert len(src.encode("utf-8")) < 60 * 1024, n


@test("the probe only reads: no assignment, insert, erase, delete or write in it")
def _():
    src = (ROOT / "lua" / "probes" / "probe-messenger.lua").read_text(encoding="utf-8")
    code = "\n".join(l.split("--")[0] for l in src.splitlines())
    for bad in (":insert(", ":erase(", ":delete(", "encode_file", "io.open", "appoint(", "write_appointment",
                "add_slot", "dfhack.run_command"):
        assert bad not in code, bad
    # a statement that sets a field: only of the probe's own output tables
    for line in code.splitlines():
        m = re.match(r"\s*([\w.\[\]'\"]+)\s*=[^=]", line)
        if m and "." in m.group(1):
            assert m.group(1).split(".")[0] in ("out", "o"), line
    assert "messenger_status" in code and "entity_raw.positions" in code and "positions.site" in code


@test("the sender finds the post by its duty too and says the nobles' why; the missions report carries messenger")
def _():
    run = (ROOT / "lua" / "ai-mission-send-run.lua").read_text(encoding="utf-8")
    assert "position_by_code(ent, 'MESSENGER')" in run and "messenger_status(nil, ent)" in run
    rep = (ROOT / "lua" / "ai-missions-report.lua").read_text(encoding="utf-8")
    assert "messenger = messenger," in rep and "messenger_status(" in rep


# ---- (r10 v12) the verifier's cases ---------------------------------------------------------------

@test("v12: an ELECTED messenger's vacant slot is not filled")
def _():
    env = world("W.FORT.positions.own:insert('#', W.pos{id = 7, code = 'MESSENGER', appointed_by = W.ivec({1}),"
                " number = -1, flags = {ELECTED = true}})\n"
                "W.FORT.positions.assignments:insert('#', {id = 2, position_id = 7, histfig = -1, flags = {active = true},"
                " squad_id = -1})\nW.FORT.positions.next_assignment_id = 3")
    before = snapshot(env)
    a = env.appoint("MESSENGER", False, None)
    assert a.ok is False and "not the fort's to fill" in str(a.error), dict(a)
    assert snapshot(env) == before


@test("v12: another post with the messenger's duty is never filled in its place")
def _():
    env = world("W.FORT.positions.own:insert('#', W.pos{id = 9, code = 'DIPLOMAT', appointed_by = W.ivec({1}),"
                " flags = {ELECTED = true}, responsibilities = {[W.DUTY] = true}})\n"
                "W.FORT.positions.assignments:insert('#', {id = 2, position_id = 9, histfig = -1, flags = {active = true},"
                " squad_id = -1})\nW.FORT.positions.next_assignment_id = 3\n" + POST)
    a = env.appoint("MESSENGER", False, None)
    fa = env.W.FORT.positions.assignments
    for i in range(fa.n):
        if fa[i].position_id == 9:
            assert fa[i].histfig == -1, "the DIPLOMAT slot was filled"
    if a.ok:
        assert any(fa[i].position_id == 7 and fa[i].histfig != -1 for i in range(fa.n)), dict(a)


@test("v12: population needed but neither the count nor DF's flag readable: wait")
def _():
    env = world("")
    assert env.pop_gate(20, None, None) is not None
    assert env.pop_gate(0, None, None) is None and env.pop_gate(20, 25, True) is None


if __name__ == "__main__":
    finish()
