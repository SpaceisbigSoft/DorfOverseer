"""(0.105.41, item 8) War and peace, and the nobles' export bans.

  * lua/ai-diplomacy.lua: a peace proposal (DF's RequestPeace topic)
    answered by the Rules choice `peace` (ai / accept / refuse), the AI
    weighing the sieges, the fort's own attacks and the sliders; the civs
    the fort attacked kept in the save; the world report's civs carry both;
  * the bridge: answer_meeting's new fields checked; send_mission remembers
    whom an offensive mission attacks; the Rules choice in the settings and
    on the Army tab;
  * brain/planner_peace.py: the same weighing, the attacked list kept from
    the fort's missions, the notes, a Needs you when the AI can't press;
  * lua/ai-bans.lua: the export bans read from DF's mandates and matched;
    lua/ai-trade.lua keeping banned goods off the depot;
  * brain/planner_bans.py: the bans said, export orders skipped.

    python tests/test_peace_bans.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # noqa: E402
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import planner_peace as P  # noqa: E402
import planner_bans as B  # noqa: E402
import planner_world as W  # noqa: E402
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def _consts(path: Path, names: tuple) -> dict:
    """String constants of another test file, read without running it."""
    out = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in names:
            out[node.targets[0].id] = ast.literal_eval(node.value)
    return out


# the fake game of tests/test_world.py (ai-diplomacy on a fake DF)
_W = _consts(ROOT / "tests" / "test_world.py", ("FAKE", "MEETING"))
FAKE, MEETING = _W["FAKE"], _W["MEETING"]
SRC = module_src("ai-diplomacy.lua")
LUA = LuaRuntime(unpack_returned_tuples=True)

# the settings the module reads: the Rules' peace and the sliders (effective as the real module's)
SETTINGS = r"""
G.peace, G.traits = nil, {}
G.env.reqscript = function(name)
  if name == 'ai-overseer-settings' then
    return {load_settings = function() return {tribute = G.tribute, peace = G.peace, traits = G.traits} end,
            effective = function(t) local v = t.value or 0; return t.extreme and v * 2 or v end}
  end
  error('reqscript ' .. name)
end
"""

# a peace proposal from the goblins (civ 200), the one topic open
PEACE = SETTINGS + r"""
G.civ(200, 'GOBLIN')
G.relation(200, 'TotalWar')
df.global.game.main_interface.diplomacy = {open = true, taking_requests = false, selecting_land_holder_position = false,
  dipev = {civ_id = 200, topic_list = G.vec({1}), agreement_topic = G.vec({}), topic_parms = G.vec({0}),
           flags = {success = false, failure = false}, cur_step = 3},
  text = {word = G.vec({})}, environment = {dipev = {cur_step = 3}}}
G.focus = 'dwarfmode/Diplomacy/Default'
function G.sieges(n)
  local inv = df.global.plotinfo.invasions.list
  for i = 0, n - 1 do inv[i] = {civ_id = 200, created_year = 110 + i, flags = {active = false}} end
end
"""


def world(setup: str = ""):
    return LUA.execute(FAKE, SRC, setup)


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


def T(d):
    return LUA.table_from(d)


# --- lua/ai-diplomacy.lua: peace ---------------------------------------------------

@test("pure: peace_need from the minimum and the sliders (Militarism up, Caution down), 0-6")
def _():
    env, _ = world()
    assert env.peace_need(2, 0, 0, 50) == 2
    assert env.peace_need(2, 100, 0, 50) == 4
    assert env.peace_need(2, 0, 100, 50) == 0
    assert env.peace_need(2, 200, 0, 50) == 6 and env.peace_need(2, 400, 0, 50) == 6
    assert env.peace_need(2, -200, 0, 50) == 0
    assert env.peace_need(None, None, None, None) == 2           # the defaults
    assert env.peace_need(2, 25, 0, 50) == 3                     # rounds half up, as the brain's
    for mil, cau in ((0, 0), (100, 0), (0, 100), (25, 0), (75, -25), (-125, 60)):
        assert env.peace_need(2, mil, cau, 50) == P.peace_need(PLANNER_CONFIG, mil, cau), (mil, cau)


@test("pure: peace_verdict: accept and refuse as the Rules say; the AI: 2+ sieges and not attacked; "
      "an attacked civ only for a cautious fort")
def _():
    env, _ = world()
    assert env.peace_verdict("accept", T({"attacked": True}))[0] == "yes"
    assert env.peace_verdict("refuse", T({"sieges": 9}))[0] == "no"
    assert env.peace_verdict("ai", T({"sieges": 2}))[0] == "yes"
    assert env.peace_verdict("ai", T({"sieges": 1}))[0] == "no"
    assert env.peace_verdict("ai", T({"sieges": 0}))[0] == "no"
    assert env.peace_verdict("ai", T({"sieges": 5, "attacked": True}))[0] == "no"
    assert env.peace_verdict("ai", T({"sieges": 0, "attacked": True, "caution": 100}))[0] == "yes"
    assert env.peace_verdict("ai", T({"sieges": 3, "militarism": 100}))[0] == "no"     # 4 wanted
    assert env.peace_verdict("ai", T({"sieges": 0, "caution": 100}))[0] == "yes"       # 0 wanted
    # the brain says the same
    for pol, ctx in (("ai", {"sieges": 2}), ("ai", {"sieges": 1}), ("ai", {"sieges": 5, "attacked": True}),
                     ("ai", {"sieges": 3, "militarism": 100}), ("accept", {}), ("refuse", {"sieges": 4}),
                     ("ai", {"attacked": True, "caution": 150, "militarism": 40})):
        traits = {k: ctx[k] for k in ("militarism", "caution") if k in ctx}
        assert env.peace_verdict(pol, T(ctx))[0] == P.peace_verdict(pol, ctx.get("sieges", 0),
                                                                    bool(ctx.get("attacked")), traits)[0], (pol, ctx)


@test("note_attacked / attacked_civs: kept in the save as a list, one entry a civ, the newest 40")
def _():
    env, G = world()
    assert dict(env.attacked_civs()) == {}
    assert env.note_attacked(200, 115) and env.note_attacked(300) and env.note_attacked(200, 119)
    assert dict(env.attacked_civs()) == {300: 120, 200: 119}
    assert not env.note_attacked(-1) and not env.note_attacked("x")
    for i in range(60):
        env.note_attacked(1000 + i, 1)
    kept = dict(env.attacked_civs())
    assert len(kept) == 40 and 1059 in kept and 200 not in kept


@test("the meeting: a peace proposal answered by the AI's weighing (2 sieges: yes, 1: no), the Rules, "
      "a civ the fort attacked, the sliders")
def _():
    def answer(setup, a=None):
        env, G = world(PEACE + setup)
        r = env.answer_meeting(T(dict(a or {}, dry_run=True)))
        return r, env, G
    r, _, _ = answer("G.sieges(2)")
    assert r.ok and r.answer == "yes" and r.topic == "RequestPeace" and r.peace.sieges == 2 \
        and r.peace.policy == "ai", dict(r)
    r, _, _ = answer("G.sieges(1)")
    assert r.ok and r.answer == "no" and "fewer" in r.why, dict(r)
    r, _, _ = answer("G.sieges(5); G.peace = 'refuse'")
    assert r.answer == "no" and r.peace.policy == "refuse"
    r, _, _ = answer("G.sieges(0)", {"peace": "accept"})                 # the brain's choice over the save's
    assert r.answer == "yes"
    r, _, _ = answer("G.sieges(3); G.persist['ai-overseer/attacked-civs'] = {{id = 200, year = 117}}")
    assert r.answer == "no" and r.peace.attacked is True and "attacked" in r.why, dict(r)
    r, _, _ = answer("G.sieges(3)", {"attacked": T([7, 200])})          # the brain's list
    assert r.answer == "no" and r.peace.attacked is True
    r, _, _ = answer("G.sieges(3); G.traits = {militarism = {value = 50, extreme = true}}")   # 100: 4 wanted
    assert r.answer == "no", dict(r)
    r, _, _ = answer("G.sieges(1); G.traits = {caution = {value = 50}}")                      # 1 wanted
    assert r.answer == "yes", dict(r)
    r, _, _ = answer("G.sieges(1)", {"peace_min": 1})                   # the brain's number
    assert r.answer == "yes", dict(r)
    r, _, _ = answer("G.sieges(4); G.peace = 'bogus'")                  # unknown: the AI decides
    assert r.answer == "yes" and r.peace.policy == "ai"


@test("the meeting: a refused peace presses No where the player showed it; other topics as before")
def _():
    env, G = world(PEACE + "G.sieges(1)")
    G.persist[env.BUTTONS_KEY] = T({"Yes": T({"dx": 0, "dy": 0}), "No": T({"dx": 4, "dy": 0})})
    g = getattr(env.df, "global")

    def concluded():
        d = g.game.main_interface.diplomacy.dipev
        d.agreement_topic[0] = 1
        d.flags.failure = True
    G.on_click = concluded
    r = env.answer_meeting(T({}))
    assert r.ok and r.pressed == "No" and r.answer == "no", dict(r)
    assert lst(G.clicks[1]) == [54, 20], lst(G.clicks[1])
    env, G = world(MEETING + SETTINGS)                     # the tree quota: no peace weighed
    r = env.answer_meeting(T({"dry_run": True}))
    assert r.answer == "yes" and r.peace is None, dict(r)


@test("the world report: each civ's sieges, and whether the fort attacked it")
def _():
    env, G = world(PEACE + "G.sieges(3); G.persist['ai-overseer/attacked-civs'] = {{id = 200, year = 117}}")
    r = env.world_report()
    gob = [c for c in lst(r.civs) if c.race == "GOBLIN"][0]
    assert gob.sieges == 3 and gob.attacked is True, dict(gob)


# --- the bridge, the settings, the window -------------------------------------------

ACTIONS = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
SETTINGS_SRC = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
GUI = (LUA_DIR / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
BRIDGE = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")


def _bridge_fn(name: str) -> str:
    i = ACTIONS.index(f"function {name}(")
    return ACTIONS[i:ACTIONS.index("\nend\n", i) + 5]


@test("bridge: answer_meeting checks peace, attacked and the numbers, and hands them on")
def _():
    run = LUA.execute(r"""
local fn_src = ...
local got = {}
local env = setmetatable({}, {__index = _G})
env.reject = function(msg) return {ok = false, rejected = true, error = msg} end
env.int_in = function(v, lo, hi)
  if type(v) ~= 'number' or v ~= math.floor(v) or v < lo or v > hi then return nil end
  return v
end
env.reqscript = function(n)
  assert(n == 'ai-diplomacy')
  return {answer_meeting = function(a) got.a = a; return {ok = true} end}
end
assert(load(fn_src, 'act', 't', env))()
return function(a) got.a = nil; return env.act_answer_meeting(a), got.a end
""", _bridge_fn("act_answer_meeting"))
    r, a = run(T({"peace": "accept", "attacked": T([3, 5]), "peace_min": 3}))
    assert r.ok and a.peace == "accept" and lst(a.attacked) == [3, 5] and a.peace_min == 3, dict(r)
    for bad in ({"peace": "maybe"}, {"attacked": 4}, {"attacked": T(["x"])}, {"peace_step": -1},
                {"attacked": T(list(range(51)))}):
        r, a = run(T(bad))
        assert r.rejected and a is None, bad
    r, a = run(T({}))
    assert r.ok and a.peace is None


@test("bridge: send_mission remembers the civ (and owner) an offensive mission goes against, not on a dry run")
def _():
    fn = _bridge_fn("act_send_mission")
    assert "owner = {h.civ, h.owner}" in fn
    assert "note_attacked(owner[1])" in fn and "not a.dry_run" in fn
    missions = (LUA_DIR / "ai-missions.lua").read_text(encoding="utf-8")
    assert "civ = (c and c >= 0) and int(c) or nil}" in missions


@test("settings: the peace choice (ai, accept, refuse; default ai) saved, sanitized, sent to the AI; "
      "the Army tab's row; the brain's Rules")
def _():
    import test_preset as TP
    TP.reset()
    S = TP.H.settings()
    assert [S.PEACE_CHOICES[i] for i in range(1, 4)] == ["ai", "accept", "refuse"]
    assert S.defaults().peace == "ai" and S.for_ai(S.defaults()).peace == "ai"
    for m in ("ai", "accept", "refuse"):
        assert S.sanitize(TP.t({"peace": m})).peace == m
    assert S.sanitize(TP.t({"peace": "yes"})).peace == "ai"
    assert [S.RULE_CHOICES.peace[i] for i in range(1, 4)] == ["ai", "accept", "refuse"]
    assert "view_id = 'peace'" in GUI and "self.subviews.peace:setOption(" in GUI
    assert "frame = {t = t + 10, l = 56, w = 50}" in GUI
    from planner_core import player_rules
    assert player_rules({"settings": {}})["peace"] == "ai"
    assert player_rules({"settings": {"peace": "refuse"}})["peace"] == "refuse"
    assert player_rules({"settings": {"peace": "x"}})["peace"] == "ai"


# --- brain/planner_peace.py ---------------------------------------------------------

def fort(world_: dict | None = None, **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["world"] = world_ or {}
    s.update(extra)
    return s


WAR = {"civs": [{"id": 200, "name": "Goblins", "race": "GOBLIN", "relation": "TotalWar", "hostile": True},
                {"id": 300, "name": "Elves", "race": "ELF", "relation": "Peace", "peace_offered": True}],
       "sieges": [{"id": 200, "n": 3, "last_year": 118}]}


@test("planner: the civs the fort attacked kept from its offensive missions (and the save's record); never twice; "
      "at most peace_attacked_keep")
def _():
    mem = Memory()
    mem.world_seen = {}
    mem.missions_seen = {"out": {"9": {"goal": "raid", "site_id": 51}, "10": {"goal": "rescue", "site_id": 52}}}
    s = fort(WAR, missions={"targets": [{"goal": "raid", "site_id": 51, "civ_id": 200}],
                            "sites": {"nearest": [{"id": 52, "owner_civ": 400}, {"id": 53, "owner_civ": 500}]},
                            "send": {"last_by_goal": {"pillage": {"result": "sent", "goal": "pillage", "site_id": 53}}}})
    W.note_world(s, mem)
    assert set(mem.world_seen["attacked"]) == {"200", "500"}, mem.world_seen       # the rescue isn't an attack
    first = dict(mem.world_seen["attacked"])
    W.note_world(s, mem)
    assert mem.world_seen["attacked"] == first
    s2 = fort(dict(WAR, civs=WAR["civs"] + [{"id": 600, "attacked": True}]))
    assert P.attacked_civs(s2, mem) == [200, 500, 600]
    mem.world_seen["attacked"] = {str(i): i for i in range(50)}
    P.note_attacks(s, mem, dict(PLANNER_CONFIG, peace_attacked_keep=40))
    assert len(mem.world_seen["attacked"]) == 40 and "200" in mem.world_seen["attacked"]


@test("planner: a peace proposal on the screen: answer_meeting carries the Rules' peace, the numbers and the "
      "attacked civs; other meetings unchanged")
def _():
    m = {"open": True, "civ": "Goblins", "civ_id": 200, "topic": "RequestPeace", "topics": ["RequestPeace"],
         "buttons": ["No", "Yes"]}
    s = fort(dict(WAR, meeting=m))
    s["settings"]["peace"] = "refuse"
    mem = Memory()
    mem.world_seen = {"attacked": {"500": 1}}
    p = [x for x in plan(s, mem)[0] if x.rule == "meeting"]
    a = p[0].action
    assert a["peace"] == "refuse" and a["attacked"] == [500] and a["peace_min"] == PLANNER_CONFIG["peace_min_sieges"]
    assert "peace: no" in p[0].reason, p[0].reason
    s["settings"]["peace"] = "ai"
    p = [x for x in plan(s, Memory())[0] if x.rule == "meeting"]
    assert "peace: yes" in p[0].reason                                  # 3 sieges, not attacked


@test("planner: the notes say what the AI answers each besieger and the civ that offered peace; "
      "a proposal it can't press is a Needs you with its answer")
def _():
    notes = []
    P._peace_notes(fort(WAR), PLANNER_CONFIG, notes, Memory())
    assert any("Goblins" in n and "3 time(s)" in n and "answer yes" in n and "can't offer" in n for n in notes), notes
    assert any("Elves have offered peace" in n and "answers no" in n for n in notes), notes   # never besieged us
    # the brain's sliders: Militarism 100 wants 4 sieges
    s = fort(WAR)
    s["settings"]["traits"] = {"militarism": 100}
    notes = []
    P._peace_notes(s, PLANNER_CONFIG, notes, Memory())
    assert any("Goblins" in n and "answer no" in n for n in notes), notes
    # on the screen, two topics open: a Needs you
    m = {"open": True, "civ": "Goblins", "civ_id": 200, "topic": "TreeQuota", "topics": ["TreeQuota", "RequestPeace"],
         "buttons": ["No", "Yes"]}
    notes = []
    P._peace_notes(fort(dict(WAR, meeting=m)), PLANNER_CONFIG, notes, Memory())
    needs = [n for n in notes if "propose peace" in n]
    assert needs and "YES" in needs[0] and "2 topics" in needs[0], notes
    assert not any("at war with Goblins" in n for n in notes)            # the meeting says it
    # one topic, the buttons known: the AI presses it itself, no Needs you
    notes = []
    P._peace_notes(fort(dict(WAR, meeting=dict(m, topics=["RequestPeace"], topic="RequestPeace"))),
                   PLANNER_CONFIG, notes, Memory())
    assert not any("propose peace" in n for n in notes), notes


# --- lua/ai-bans.lua and lua/ai-trade.lua ---------------------------------------------

BANS_SRC = module_src("ai-bans.lua")

BANS_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function() return #(list or {}) end})
end
local ipairs0 = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.ipairs = ipairs0
env.df = {mandate_type = {Export = 0, Make = 1, [0] = 'Export', [1] = 'Make'},
          item_type = {[1] = 'FIGURINE', [2] = 'AMULET', FIGURINE = 1, AMULET = 2},
          global = {world = {mandates = {all = vec({
             {mode = 0, item_type = 1, item_subtype = -1, mat_type = 0, mat_index = 7,
              timeout_counter = 10, timeout_limit = 3000, unit = {name = 'the baron'}},
             {mode = 1, item_type = 2, item_subtype = -1, mat_type = -1, mat_index = -1,
              timeout_counter = 0, timeout_limit = 3000},
             {mode = 0, item_type = 2, item_subtype = -1, mat_type = -1, mat_index = -1,
              timeout_counter = 3000, timeout_limit = 3000}})}}}}
env.dfhack = {matinfo = {decode = function(t, i) return {toString = function() return 'granite' end} end},
              units = {getReadableName = function(u) return u.name end},
              items = {getContainedItems = function(it) return it.inside or {} end}}
env.reqscript = function(n) error('reqscript ' .. n) end
assert(load(src, 'ai-bans', 't', env))()
return env
"""


@test("ai-bans pure: in force (Export, not timed out); a ban matches type, subtype and material, -1 any")
def _():
    lua = LUA
    env = lua.execute(BANS_FAKE, BANS_SRC)
    assert env.in_force(T({"mode": 0, "timeout_counter": 1, "timeout_limit": 5}), 0)
    assert not env.in_force(T({"mode": 0, "timeout_counter": 5, "timeout_limit": 5}), 0)
    assert not env.in_force(T({"mode": 1}), 0)
    assert env.in_force(T({"mode": "Export"}), None)                   # timer unreadable: in force
    ban = T({"item_type": 1, "item_subtype": -1, "mat_type": 0, "mat_index": 7})
    assert env.matches(ban, T({"item_type": 1, "item_subtype": 3, "mat_type": 0, "mat_index": 7}))
    assert not env.matches(ban, T({"item_type": 1, "item_subtype": 3, "mat_type": 0, "mat_index": 8}))
    assert not env.matches(ban, T({"item_type": 2, "item_subtype": -1, "mat_type": 0, "mat_index": 7}))
    any_mat = T({"item_type": 1, "item_subtype": -1, "mat_type": -1, "mat_index": -1})
    assert env.matches(any_mat, T({"item_type": 1, "item_subtype": 0, "mat_type": 420, "mat_index": 3}))
    assert not env.matches(T({"item_type": 1, "item_subtype": 4}), T({"item_type": 1, "item_subtype": 3}))
    assert not env.matches(None, T({})) and env.banned_by(lua.table(), T({"item_type": 1})) is None


@test("ai-bans read: only the export bans in force, in words; checker: the item or what's inside it")
def _():
    lua = LUA
    env = lua.execute(BANS_FAKE, BANS_SRC)
    bans = lst(env.read())
    assert len(bans) == 1 and bans[0].item == "FIGURINE" and bans[0].material == "granite" \
        and bans[0].by == "the baron" and bans[0].days_left == 24, [dict(b) for b in bans]
    item = lua.eval("""function(t, mat, idx, inside)
        return {getType = function() return t end, getSubtype = function() return -1 end,
                getMaterial = function() return mat end, getMaterialIndex = function() return idx end,
                inside = inside} end""")
    check, _ = env.checker()
    granite_fig, other_fig = item(1, 0, 7, None), item(1, 0, 9, None)
    assert check(granite_fig) and not check(other_fig)
    assert check(item(3, 0, 1, T([other_fig, granite_fig])))             # a bin holding a banned one
    assert not check(item(3, 0, 1, T([other_fig])))
    assert dict(lst(env.summary(env.read()))[0])["item"] == "FIGURINE"
    none, _ = env.checker(lua.table())
    assert not none(granite_fig)


TRADE_BANS = r"""
local trade_src, bans_src = ...
local TYPES = {FIGURINE = 1, AMULET = 2, BIN = 3}
TYPES[1], TYPES[2], TYPES[3] = 'FIGURINE', 'AMULET', 'BIN'
local function item(id, t, idx, extra)
    local it = {id = id, t = t, idx = idx, value = 10, flags = {on_ground = true, in_inventory = false}}
    for k, v in pairs(extra or {}) do it.flags[k] = v end
    it.getType = function(self) return self.t end
    it.getSubtype = function() return -1 end
    it.getMaterial = function() return 0 end
    it.getMaterialIndex = function(self) return self.idx end
    return it
end
-- loose: a granite figurine (banned), a marble figurine, a granite amulet;
-- a bin with a granite figurine inside (kept home whole)
local figs = {item(1, 1, 7), item(2, 1, 9)}
local amulets = {item(3, 2, 7)}
local bin = item(100, 3, 9)
local in_bin = item(4, 1, 7, {on_ground = false, in_inventory = true})
table.insert(figs, in_bin)
local inside = {[100] = {in_bin}}
local marked = {}
local env = setmetatable({}, {__index = _G})
env.df = {item_type = TYPES, mandate_type = {Export = 0},
          global = {world = {items = {other = {FIGURINE = figs, AMULET = amulets}},
                             buildings = {other = {TRADE_DEPOT = {}}},
                             mandates = {all = {{mode = 0, item_type = 1, item_subtype = -1, mat_type = 0,
                                                 mat_index = 7, timeout_counter = 0, timeout_limit = 1000}}}},
                    plotinfo = {caravans = {{entity = 1, trade_state = 1, time_remaining = 100,
                                             flags = {tribute = false}}}}},
          caravan_state = {T_trade_state = {Approaching = 1, AtDepot = 2}},
          historical_entity = {find = function() return nil end}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.dfhack = {items = {getValue = function(it) return it.value end,
                       getPosition = function() return 1, 1, 1 end,
                       getContainer = function(it) if it == in_bin then return bin end end,
                       getContainedItems = function(c) return inside[c.id] or {} end,
                       markForTrade = function(it) table.insert(marked, it.id); return true end},
              maps = {canWalkBetween = function() return true end},
              matinfo = {decode = function() return {toString = function() return 'granite' end} end}}
local benv = setmetatable({}, {__index = env})
env.reqscript = function(n)
    if n == 'ai-bans' then return benv end
    error('reqscript ' .. n)
end
benv.reqscript = function(n) error('reqscript ' .. n) end
assert(load(bans_src, 'ai-bans', 't', benv))()
assert(load(trade_src, 'ai-trade', 't', env))()
local depot = {centerx = 5, centery = 5, z = 1, contained_items = {},
               getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
env.df.global.world.buildings.other.TRADE_DEPOT = {depot}
return env, marked
"""


@test("ai-trade: goods an export ban covers stay home (loose or a bin holding one); the survey says the bans")
def _():
    env, marked = LUA.execute(TRADE_BANS, module_src("ai-trade.lua"), BANS_SRC)
    s = env.survey()
    assert s.goods == 2 and s.banned_kept == 2, dict(s)          # the marble figurine and the amulet
    assert lst(s.bans)[0].item == "FIGURINE" and lst(s.bans)[0].material == "granite"
    r = env.bring(40, False)
    got = sorted(marked[i] for i in range(1, len(marked) + 1))
    assert r.ok and got == [2, 3] and r.banned_kept == 2, (dict(r), got)


@test("ai-trade: the trade screen's offers ask ai-bans first (DFHack's own check only without it)")
def _():
    src = (LUA_DIR / "ai-trade.lua").read_text(encoding="utf-8")
    i = src.index("local function ban_check()")
    body = src[i:src.index("\nend\n", i)]
    assert body.index("ban_checker()") < body.index("internal/caravan/common")
    assert "'ai-bans'" in BRIDGE


# --- brain/planner_bans.py ------------------------------------------------------------

@test("planner: the bans from the trade report, else the mandates' Export ones (timed out left out)")
def _():
    s = fort(trade={"bans": [{"item": "FIGURINE", "material": "granite", "by": "Urist", "days_left": 20}]})
    assert [b["item"] for b in B.export_bans(s)] == ["FIGURINE"] and B.banned_items(s) == {"FIGURINE"}
    s = fort(trade={}, mandates=[{"kind": "Export", "item": "CRAFTS", "days_left": 3},
                                 {"kind": "Export", "item": "RING", "days_left": 0},
                                 {"kind": "Make", "item": "AMULET", "days_left": 9}])
    assert B.banned_items(s) == {"CRAFTS"}


@test("planner: the bans said while a caravan is here, with the goods kept home; none: nothing said")
def _():
    s = fort(trade={"depot": True, "caravans": [{"civ": "Dwarves", "state": "Approaching"}], "banned_kept": 3,
                    "bans": [{"item": "FIGURINE", "material": "granite", "by": "Urist", "days_left": 20}]})
    notes = []
    B._export_bans_notes(s, notes)
    assert notes and "granite figurine (by Urist; 20 days left)" in notes[0] and "3 kept home" in notes[0], notes
    notes = []
    B._export_bans_notes(fort(trade={"depot": True, "caravans": [{"civ": "x"}]}), notes)
    assert notes == []
    s["trade"]["caravans"] = []
    B._export_bans_notes(s, notes)
    assert notes == []


@test("planner: a caravan's well-paid wish isn't made for export while the nobles ban it")
def _():
    mem = Memory()
    s = fort({"wanted": [{"item": "FIGURINE", "pct": 150, "civ": "Elves"}]})
    s["dwarves"]["idle_adults"] = s["dwarves"]["adults"]
    s["orders"] = []
    props = []
    W._export_rule(s, PLANNER_CONFIG, props, [], mem)
    made = [p for p in props if p.rule == "export"]
    s["mandates"] = [{"kind": "Export", "item": "FIGURINE", "days_left": 30}]
    props2 = []
    W._export_rule(s, PLANNER_CONFIG, props2, [], mem)
    assert made and not [p for p in props2 if p.rule == "export"], (made, props2)


@test("Lua: ai-bans, ai-diplomacy, ai-trade and the bridge parts compile (Lua 5.3)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for name in ("ai-bans.lua", "ai-diplomacy.lua", "ai-trade.lua", "ai-bridge-actions.lua",
                 "ai-overseer-settings.lua", "gui/ai-overseer.lua", "ai-missions.lua"):
        f = lua.eval("function(src, name) local f, err = load(src, name, 't'); return err end")
        err = f((LUA_DIR / name).read_text(encoding="utf-8"), name)
        assert err is None, (name, err)
    assert code_has(SETTINGS_SRC, "peace = 'ai',")


if __name__ == "__main__":
    finish()
