"""(0.105.0) Tests for the world outside (phases 12b and 13b): the `world`
report and the meeting screen (lua/ai-diplomacy.lua) on a fake game, the
messenger (lua/ai-nobles.lua), the bridge's wiring, the Rules switches and
the planner's rules (brain/planner_world.py).

    python tests/test_world.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import planner_world as W  # noqa: E402
from planner import Memory, PLANNER_CONFIG, note_cycle, plan  # noqa: E402
from planner_core import player_rules  # noqa: E402

SRC = module_src("ai-diplomacy.lua")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


# --- the Lua module on a fake game ------------------------------------------------

FAKE = r"""
local src, setup = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end})
end
local function zipairs(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    if type(t) == 'table' and getmetatable(t) and getmetatable(t).__len then return function() end end
    return ipairs(t)
end
local function enum(names, first)
    local e = {}
    for i, n in ipairs(names) do e[(first or 0) + i - 1] = n; e[n] = (first or 0) + i - 1 end
    return e
end
local G = {persist = {}, clicks = {}, files = {}, focus = 'dwarfmode/Default', inputs = {}}
local ENTS, RACES = {}, {}
local env = setmetatable({}, {__index = _G})
env.ipairs = zipairs
env.df = {
  diplomacy_state_type = enum({'Peace', 'TotalWar', 'NoContact', 'AcceptingTribute', 'OfferingTribute', 'Skirmishing'}),
  historical_entity_type = enum({'Civilization', 'SiteGovernment'}),
  meeting_topic = enum({'DiscussCurrent', 'RequestPeace', 'TreeQuota', 'BecomeLandHolder', 'PromoteLandHolder',
                        'ExportAgreement', 'ImportAgreement', 'PleasantPlace', 'WorldStatus', 'TributeAgreement'}),
  entity_sell_category = enum({'Leather', 'ClothPlant', 'ClothSilk', 'Crafts', 'Wood', 'MetalBars'}),
  item_type = enum({'BAR', 'CRAFTS', 'FIGURINE', 'GOBLET'}),
  season = enum({'Spring', 'Summer', 'Autumn', 'Winter'}),
  caravan_state = {T_trade_state = enum({'None', 'Approaching', 'AtDepot', 'Leaving', 'Stuck'})},
  historical_entity = {find = function(id) return ENTS[id] end},
  creature_raw = {find = function(id) return RACES[id] end},
  global = {
    plotinfo = {civ_id = 100, caravans = vec(), invasions = {list = vec()}, dip_meeting_info = vec(),
                dipscript_popups = vec(), tasks = {wealth = {total = 10000}}},
    world = {units = {active = vec()}},
    gps = {mouse_x = 50, mouse_y = 20, dimx = 100, dimy = 40, tile_pixel_x = 8, tile_pixel_y = 12},
    game = {main_interface = {diplomacy = {open = false}}},
    cur_year = 120, cur_year_tick = 5,
  },
}
env.dfhack = {
  getDFPath = function() return '/df' end,
  df2utf = function(s) return s end,
  translation = {translateName = function(n) return n.text end},
  persistent = {getSiteData = function(k, d) local v = G.persist[k]; if v == nil then return d end; return v end,
                saveSiteData = function(k, v) G.persist[k] = v end},
  filesystem = {mkdir_recursive = function() end},
  gui = {getCurFocus = function() return {G.focus} end, getDFViewscreen = function() return {} end},
  items = {getSubtypeDef = function() return nil end},
  units = {isDead = function() return false end, isDanger = function(u) return u.danger == true end,
           isInvader = function() return false end},
}
env.require = function(name)
  if name == 'json' then
    return {decode_file = function(p) if G.files[p] then return G.files[p] end error('none') end,
            encode_file = function(d, p) G.files[p] = d end}
  end
  if name == 'gui' then
    return {simulateInput = function(_, key)
      table.insert(G.inputs, key)
      if key == '_MOUSE_L' then
        table.insert(G.clicks, {env.df.global.gps.mouse_x, env.df.global.gps.mouse_y})
        if G.on_click then G.on_click() end
      end
      if key == 'LEAVESCREEN' then env.df.global.game.main_interface.diplomacy.open = false; G.focus = 'dwarfmode/Default' end
    end}
  end
  error('require ' .. name)
end
env.reqscript = function(name)
  if name == 'ai-overseer-settings' then return {load_settings = function() return {tribute = G.tribute} end} end
  error('reqscript ' .. name)
end
function G.civ(id, race, fields)
  RACES[id] = {creature_id = race}
  local e = {id = id, race = id, type = 0, name = {text = race .. ' land'}, relations = {diplomacy = {state = vec()}}}
  for k, v in pairs(fields or {}) do e[k] = v end
  ENTS[id] = e
  return e
end
function G.relation(other, rel, flags)
  local st = ENTS[100].relations.diplomacy.state
  st[#st] = {group_id = other, relation = env.df.diplomacy_state_type[rel], flags = flags or {}, tribute_season = 1}
end
G.vec, G.env = vec, env
G.civ(100, 'DWARF')
assert(load(setup, 'setup', 't', setmetatable({G = G, df = env.df}, {__index = _G})))()
assert(load(src, 'ai-diplomacy', 't', env))()
return env, G
"""

LUA = LuaRuntime(unpack_returned_tuples=True)


def world(setup: str = ""):
    return LUA.execute(FAKE, SRC, setup)


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


@test("pure: the topic asked now is the first not concluded; the answers by topic, tribute by the Rules choice")
def _():
    env, _ = world()
    T = lambda *x: LUA.table_from(list(x))   # noqa: E731
    assert env.current_topic(T("PleasantPlace", "TreeQuota"), T("PleasantPlace")) == "TreeQuota"
    assert env.current_topic(T("TreeQuota", "TreeQuota"), T("TreeQuota")) == "TreeQuota"
    assert env.current_topic(T("TreeQuota"), T("TreeQuota")) is None
    assert env.decide("TreeQuota", "small")[0] == "yes"
    assert env.decide("ExportAgreement", "small")[0] == "requests"
    assert env.decide("DeclareWar", "small")[0] == "no"
    assert env.decide("BecomeLandHolder", "small")[0] is None           # the player's
    ctx = lambda a: LUA.table_from({"amount": a, "wealth": 10000})       # noqa: E731
    assert env.decide("TributeAgreement", "small", ctx(400))[0] == "yes"     # 4% of the wealth: small
    assert env.decide("TributeAgreement", "small", ctx(2000))[0] == "no"     # 20%: large
    assert env.decide("TributeAgreement", "small", LUA.table_from({}))[0] is None   # amount unknown: left
    assert env.decide("TributeAgreement", "pay", ctx(9000))[0] == "yes"
    assert env.decide("TributeAgreement", "refuse", ctx(1))[0] == "no"
    assert env.price_pct(128) == 100 and env.price_pct(192) == 150


@test("pure: the requests' wishes ticked only on wanted tabs, never over the player's own choice")
def _():
    env, _ = world()
    prios = LUA.table_from([LUA.table_from([0, 3, 0]), LUA.table_from([0]), LUA.table_from([0, 0])])
    n = env.tick_wishes(LUA.table_from(["Leather", "Wood", "MetalBars"]), prios, LUA.table_from(["Leather", "MetalBars"]))
    assert n == 4, n
    assert lst(prios[1]) == [2, 3, 2] and lst(prios[2]) == [0] and lst(prios[3]) == [2, 2]


WAR = r"""
G.civ(200, 'GOBLIN'); G.civ(300, 'ELF'); G.civ(400, 'HUMAN'); G.civ(500, 'KOBOLD')
G.relation(200, 'TotalWar'); G.relation(300, 'Peace', {peace_offering_received = false, allies = true})
G.relation(400, 'AcceptingTribute'); G.relation(500, 'NoContact')
local inv = df.global.plotinfo.invasions.list
inv[0] = {civ_id = 200, created_year = 110, flags = {active = false}}
inv[1] = {civ_id = 200, created_year = 118, flags = {active = true}}
inv[2] = {civ_id = -1, created_year = 117, flags = {}}                -- a beast's: no civ
local cars = df.global.plotinfo.caravans
cars[0] = {entity = 200, time_remaining = 100, trade_state = 1, flags = {tribute = false}, buy_prices = nil}
cars[1] = {entity = 300, time_remaining = 100, trade_state = 2, flags = {tribute = false},
           buy_prices = {items = {item_type = G.vec({1, 3}), item_subtype = G.vec({-1, -1})}, price = G.vec({160, 128})}}
cars[2] = {entity = 400, time_remaining = 0, trade_state = 3, flags = {tribute = true}}      -- gone
df.global.world.units.active[0] = {civ_id = 200, danger = false}
df.global.world.units.active[1] = {civ_id = 200, danger = true}
"""


@test("the world report: civs at war or peace, tribute, who besieged the fort, the caravans' agreements, hostile visitors")
def _():
    env, _ = world(WAR)
    r = env.world_report()
    civs = {c.race: c for c in lst(r.civs)}
    assert civs["GOBLIN"].relation == "TotalWar" and civs["GOBLIN"].hostile is True
    assert civs["ELF"].relation == "Peace" and civs["ELF"].allies is True and civs["ELF"].hostile is None
    assert civs["HUMAN"].tribute == "they take" and civs["HUMAN"].tribute_season == "Summer"
    assert civs["KOBOLD"].relation == "NoContact"
    sg = lst(r.sieges)
    assert len(sg) == 1 and sg[0].id == 200 and sg[0].n == 2 and sg[0].last_year == 118 and sg[0].active is True
    cars = lst(r.caravans)
    assert len(cars) == 2 and cars[0].hostile is True and cars[1].wanted == 2, [dict(c) for c in cars]
    wanted = lst(r.wanted)
    assert (wanted[0].item, wanted[0].pct, wanted[0].civ) == ("CRAFTS", 125, "ELF land"), dict(wanted[0])
    assert r.visitors_from_hostile == 1                       # the dangerous one is a threat, not a visitor
    assert r.meeting is None and r.unknown is None, (r.meeting, r.unknown and lst(r.unknown))


MEETING = r"""
G.civ(300, 'ELF')
df.global.game.main_interface.diplomacy = {open = true, taking_requests = false, selecting_land_holder_position = false,
  dipev = {civ_id = 300, topic_list = G.vec({7, 2}), agreement_topic = G.vec({7}), topic_parms = G.vec({0, 0}),
           flags = {success = false, failure = false}, cur_step = 3},
  text = {word = G.vec({})}, environment = {dipev = {cur_step = 3}}}
G.focus = 'dwarfmode/Diplomacy/Default'
"""


@test("the meeting screen: its state, written to the probe file; no button known: nothing pressed, it says which")
def _():
    env, G = world(MEETING)
    st = env.meeting_state()
    assert st.open and st.civ == "ELF land" and st.topic == "TreeQuota" and lst(st.topics) == ["PleasantPlace", "TreeQuota"]
    r = env.answer_meeting(LUA.table_from({}))
    assert not r.ok and r.needs_button == "Yes" and r.answer == "yes" and len(G.clicks) == 0, dict(r)
    probe = G.files[env.PROBE_FILE]
    assert probe and len(probe.samples) == 1 and probe.samples[1].state.topic == "TreeQuota"


@test("the meeting answered through the button shown once: Yes to the tree quota; the screen left when the meeting is done")
def _():
    env, G = world(MEETING)
    G.focus = 'dwarfmode/Diplomacy/Default'
    g = getattr(env.df, "global")
    g.gps.mouse_x, g.gps.mouse_y = 60, 30
    c = env.calibrate("Yes")
    assert c.ok and c.x == 60, dict(c)
    assert not env.calibrate("Maybe").ok

    def concluded():
        d = g.game.main_interface.diplomacy.dipev
        d.agreement_topic[1] = 2
        d.flags.success = True
    G.on_click = concluded
    g.gps.dimx = 120                                  # a wider window: kept from the centre
    r = env.answer_meeting(LUA.table_from({"tribute": "small"}))
    assert r.ok and r.pressed == "Yes" and r.closed is True, dict(r)
    assert lst(G.clicks[1]) == [70, 30], lst(G.clicks[1])
    assert "LEAVESCREEN" in lst(G.inputs)
    nothing = env.answer_meeting(LUA.table_from({}))
    assert not nothing.ok and nothing.rejected                # no meeting open now


@test("the meeting: a barony's holder left to the player; a tribute pressed only when the Rules say pay")
def _():
    env, G = world(MEETING + "df.global.game.main_interface.diplomacy.selecting_land_holder_position = true")
    r = env.answer_meeting(LUA.table_from({}))
    assert not r.ok and r.left_to_player, dict(r)
    tribute = MEETING + "df.global.game.main_interface.diplomacy.dipev.topic_list = G.vec({9}); " \
                        "df.global.game.main_interface.diplomacy.dipev.agreement_topic = G.vec({}); " \
                        "df.global.game.main_interface.diplomacy.dipev.topic_parms = G.vec({%d})"
    # (0.105.0 review) small or refuse: a tribute on the table is left to the player
    env, G = world(tribute % 3000)
    r = env.answer_meeting(LUA.table_from({"dry_run": True}))
    assert not r.ok and r.left_to_player and "tribute" in r.error, dict(r)
    env, G = world(tribute % 3000)
    G.tribute = "pay"                                          # the Rules tab's choice when none is passed
    assert env.answer_meeting(LUA.table_from({"dry_run": True})).answer == "yes"
    # decide() still weighs the tribute (kept for the report)
    assert env.decide("TributeAgreement", "small", LUA.table_from({"amount": 3000, "wealth": 10000}))[0] == "no"


@test("the meeting (0.105.0 review): pressed only with exactly one topic open, never on war or surrender")
def _():
    WENV, _ = world()
    T = lambda *a: LUA.table_from(list(a))   # noqa: E731
    assert lst(WENV.pending_topics(T("PleasantPlace", "TreeQuota"), T("PleasantPlace"))) == ["TreeQuota"]
    assert WENV.press_guard(T("TreeQuota"), "small") is None
    assert "2 topics" in WENV.press_guard(T("TreeQuota", "OpenTrade"), "small")
    assert "left to you" in WENV.press_guard(T(), "small")
    for t in ("DemandSurrender", "DeclareWar", "InduceWar"):
        assert t in WENV.press_guard(T(t), "pay")
    assert "tribute" in WENV.press_guard(T("TributeAgreement"), "small")
    assert WENV.press_guard(T("TributeAgreement"), "pay") is None
    two = MEETING + "df.global.game.main_interface.diplomacy.dipev.agreement_topic = G.vec({})"
    env, G = world(two)
    r = env.answer_meeting(LUA.table_from({"dry_run": True}))
    assert not r.ok and r.left_to_player and "2 topics" in r.error, dict(r)
    import overseer
    import types
    import os
    old = os.environ.pop("DFAI_PIN", None)
    try:
        assert not overseer.meeting_unattended(types.SimpleNamespace(unattended=False))
        assert overseer.meeting_unattended(types.SimpleNamespace(unattended=True))
        os.environ["DFAI_PIN"] = "1"
        assert overseer.meeting_unattended(types.SimpleNamespace(unattended=False))
    finally:
        os.environ.pop("DFAI_PIN", None)
        if old is not None:
            os.environ["DFAI_PIN"] = old


@test("the requests screen: the fort's wishes ticked, then Done (only once shown where Done is)")
def _():
    env, G = world(MEETING + r"""
local d = df.global.game.main_interface.diplomacy
d.taking_requests = true
d.taking_requests_tablist = G.vec({0, 4, 5})
local prio = {}
prio[0] = G.vec({0, 0}); prio[4] = G.vec({0}); prio[5] = G.vec({4, 0, 0})
d.environment.dipev.sell_requests = {priority = prio}
G.focus = 'dwarfmode/Diplomacy/Requests'
""")
    r = env.answer_meeting(LUA.table_from({"wishes": LUA.table_from(["MetalBars", "Leather"])}))
    assert not r.ok and r.needs_button == "Done" and r.wishes_ticked == 4, dict(r)
    dip = getattr(env.df, "global").game.main_interface.diplomacy
    pr = dip.environment.dipev.sell_requests.priority
    assert [pr[0][0], pr[0][1], pr[4][0], pr[5][0], pr[5][1]] == [2, 2, 0, 4, 2]
    G.persist[env.BUTTONS_KEY] = LUA.table_from({"Done": LUA.table_from({"dx": 0, "dy": 5})})
    G.on_click = lambda: setattr(dip, "taking_requests", False)
    r = env.answer_meeting(LUA.table_from({}))
    assert r.ok and r.pressed == "Done", dict(r)


# --- the messenger (lua/ai-nobles.lua) ---------------------------------------------

@test("the messenger: appointed only where the post exists; never a soldier, staff, a patient, the wounded, a mother or an office holder")
def _():
    import test_care as care            # (its helpers; its tests don't run again)
    pos = care.POS + [{"code": "MESSENGER", "id": 9, "by": [1]}]
    folk = [{"id": 1, "hf": 11},                                                # the expedition leader
            {"id": 2, "hf": 12, "skills": [("ORGANIZATION", 9)], "squad": 50},  # a soldier
            {"id": 3, "hf": 13, "skills": [("ORGANIZATION", 9)], "staff": True},
            {"id": 4, "hf": 14, "skills": [("ORGANIZATION", 9)], "patient": True},
            {"id": 7, "hf": 17, "skills": [("ORGANIZATION", 9)], "wounds": True},   # (0.105.24) hurt
            {"id": 5, "hf": 15, "skills": [("ORGANIZATION", 2)]},
            {"id": 6, "hf": 16}]
    a = [{"id": 201, "pos": 1, "hf": 11}, {"id": 209, "pos": 9}]
    env, ent, _ = care.nobles(a, units=folk, positions=pos)
    r = env.appoint("MESSENGER", False)
    assert r.ok and r.name in ("dwarf 5", "dwarf 6"), dict(r)
    env, ent, _ = care.nobles(a, units=[u for u in folk if u["id"] <= 4 or u["id"] == 7], positions=pos)
    r = env.appoint("MESSENGER", False)
    assert not r.ok, dict(r)                                    # only the leader (an office) and key workers
    env, _, _ = care.nobles([{"id": 201, "pos": 1, "hf": 11}], units=folk)
    r = env.appoint("MESSENGER", False)
    assert not r.ok and "no MESSENGER office" in r.error, dict(r)


# --- the bridge, the settings, the panel ----------------------------------------------

@test("the bridge: answer_meeting in the action table, bounded; the world section; probe_meeting and meeting_here")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(src, "answer_meeting = act_answer_meeting,")
    assert code_has(src, "world = function() return safe(function() return reqscript('ai-diplomacy').world_report(txt) end) end,")
    assert code_has(src, "probe_meeting = cmd_probe_meeting,") and code_has(src, "meeting_here = cmd_meeting_here,")
    assert code_has(src, "meeting = meeting_focus() ~= nil or nil,")
    import test_bridge_memory as tbm
    tbm.reset()
    M = tbm.H.module()
    tbm.LUA.execute("""local M, H = ...
      H.calls = {}
      H.scripts = {['ai-diplomacy'] = {answer_meeting = function(a) table.insert(H.calls, a); return {ok = true} end,
                                       world_report = function() return {civs = {}} end}}
    """, M, tbm.H)
    assert tbm.LUA.eval("function(M) return M.ACTIONS.answer_meeting == M.act_answer_meeting end")(M)
    assert M.act_answer_meeting(tbm.t({"tribute": "pay", "dry_run": True})).ok
    c = tbm.H.calls[1]
    assert c.tribute == "pay" and c.dry_run is True
    assert M.act_answer_meeting(tbm.t({"wishes": ["MetalBars"]})).ok and tbm.H.calls[2].wishes[1] == "MetalBars"
    for bad in ({"tribute": "lots"}, {"wishes": "Wood"}, {"wishes": ["a b"]}, {"wishes": [1]},
                {"wishes": ["Wood"] * 21}):
        r = M.act_answer_meeting(tbm.t(bad))
        assert not r.ok and r.rejected, bad
    assert len(tbm.H.calls) == 2
    assert M.SECTIONS.world().civs is not None
    import digest
    assert digest.SECTION_DEFAULTS["world"] == {} and digest.normalize({})["world"] == {}
    import overseer
    assert overseer.short({"type": "answer_meeting"}) == "answer the diplomat's meeting"


@test("the Rules: tribute (small, pay, refuse) and Make contact, saved, sent to the AI, on the panel")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    S = lua.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}},
                               {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(src)
    d = S.defaults()
    assert d.tribute == "small" and d.make_contact is True
    assert S.for_ai(d).tribute == "small" and S.for_ai(d).make_contact is True
    s = S.sanitize(lua.table_from({"tribute": "refuse", "make_contact": False}))
    assert s.tribute == "refuse" and s.make_contact is False and S.for_ai(s).make_contact is False
    assert S.sanitize(lua.table_from({"tribute": "gold"})).tribute == "small"
    assert S.sanitize(lua.table_from({})).make_contact is True
    assert player_rules({"settings": {}})["tribute"] == "small" and player_rules({"settings": {}})["make_contact"]
    assert player_rules({"settings": {"tribute": "pay", "make_contact": False}}) | {} != {}
    assert player_rules({"settings": {"tribute": "pay"}})["tribute"] == "pay"
    assert player_rules({"settings": {"tribute": "x"}})["tribute"] == "small"
    assert player_rules({"settings": {"make_contact": False}})["make_contact"] is False
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    for v in ("tribute", "make_contact"):
        assert code_has(gui, f"view_id = '{v}'") and code_has(gui, f"p:set_field('{v}', v)") and code_has(gui, f"self.subviews.{v}:setOption(")
    ok = lua.eval("function(src) local f, e = load(src, 'gui', 't', {}); return f ~= nil, e end")(gui)
    assert ok[0], ok
    ok = lua.eval("function(src) local f, e = load(src, 'd', 't', {}); return f ~= nil, e end")(SRC)
    assert ok[0], ok


# --- the planner -----------------------------------------------------------------------

def fort(world=None, **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    if world is not None:
        s["world"] = world
    s.update(extra)
    return s


def s_year():
    return BASE["date"]["year"]


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


@test("planner: an open meeting is answered (tribute by the Rules) once the buttons are known; else the Needs-you says how")
def _():
    m = {"open": True, "civ": "Elves", "topic": "TreeQuota", "buttons": ["No", "Yes"]}
    s = fort({"meeting": m})
    s["settings"]["tribute"] = "refuse"
    p = by_rule(plan(s, Memory())[0], "meeting")
    assert p and p[0].action == {"type": "answer_meeting", "tribute": "refuse"} and p[0].priority == 0, p
    s2 = fort({"meeting": dict(m, buttons=[])})
    s2["meetings"] = {"screen": "dwarfmode/Diplomacy/Default"}
    props, notes = plan(s2, Memory())
    assert not by_rule(props, "meeting")
    assert any("probe_meeting.py --here Yes" in n for n in notes), notes
    req = fort({"meeting": dict(m, requests=True, buttons=["Done"])})
    p = by_rule(plan(req, Memory())[0], "meeting")
    assert p and isinstance(p[0].action.get("wishes", []), list), p
    baron = fort({"meeting": dict(m, land_holder=True)})
    props, notes = plan(baron, Memory())
    assert not by_rule(props, "meeting") and any("barony" in n for n in notes)


@test("planner: no trade with a civ at war; trade goes on with a friendly caravan here too")
def _():
    s = fort({"caravans": [{"civ": "Goblins", "hostile": True, "state": "AtDepot"}]})
    s["trade"] = {"depot": True, "goods": 30, "caravans": [{"civ": "Goblins", "state": "AtDepot"}], "trader": {}}
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.action.get("type") in W.TRADE_ACTIONS], [p.action for p in props]
    assert any("at war with the fort: not traded with" in n for n in notes), notes
    s["world"]["caravans"].append({"civ": "Elves", "state": "AtDepot"})
    props, _ = plan(s, Memory())
    assert [p for p in props if p.action.get("type") in W.TRADE_ACTIONS]


@test("planner: what a caravan's agreement pays well for is made for the next one (kept a year); the planner never writes memory")
def _():
    s = fort({"wanted": [{"item": "FIGURINE", "pct": 150, "civ": "Elves"}, {"item": "BAR", "pct": 200}]})
    s["dwarves"]["idle_adults"] = s["dwarves"]["adults"]
    s["orders"] = []
    m = Memory()
    before = json.dumps(m.to_dict(), sort_keys=True, default=str)
    p = by_rule(plan(s, m)[0], "export")
    assert p and p[0].action == {"type": "work_order", "recipe": "stone_crafts", "amount": W.EXPORT_AMOUNT}, p
    assert json.dumps(m.to_dict(), sort_keys=True, default=str) == before, "plan() wrote memory"
    note_cycle(s, m)
    assert m.world_seen["export"]["FIGURINE"]["pct"] == 150
    later = fort({})
    later["dwarves"]["idle_adults"] = later["dwarves"]["adults"]
    later["orders"] = []
    assert by_rule(plan(later, m)[0], "export"), "not remembered"
    later["date"]["year"] += 2
    assert not by_rule(plan(later, m)[0], "export"), "not forgotten"
    busy = copy.deepcopy(s)
    busy["dwarves"]["idle_adults"] = 0
    assert not by_rule(plan(busy, Memory())[0], "export"), "busy"


@test("planner: the grudge list kept from the sieges; Grudge-keepers reads it; war and tribute said")
def _():
    s = fort({"civs": [{"id": 200, "name": "Goblins", "race": "GOBLIN", "relation": "TotalWar", "hostile": True},
                       {"id": 400, "name": "Humans", "race": "HUMAN", "relation": "AcceptingTribute",
                        "tribute": "they take"}],
              "sieges": [{"id": 200, "n": 3, "last_year": s_year(), "name": "Goblins"}],
              "visitors_from_hostile": 2})
    m = Memory()
    note_cycle(s, m)
    assert m.world_seen["grudges"]["200"]["sieges"] == 3
    f = W.grudge_facts(s, m)
    assert f["sieges_on_record"] == 3 and f["years_since_siege_on_record"] == 0 and f["grudge_civs"] == 1, f
    _, notes = plan(s, m)
    assert any(n.startswith("at war with Goblins") for n in notes), notes
    assert any("tribute: Humans they take" in n for n in notes) and any("left alone unless" in n for n in notes)
    import overseer
    m.atlas = {}
    assert overseer.world_facts(s, m)["sieges_on_record"] == 3
    import quirks
    f = quirks.facts({"sieges": 1}, None, s_year(), overseer.world_facts(s, m))
    assert f["sieges"] == 3 and f["years_since_siege"] == 0, f      # Grudge-keepers' own facts


@test("planner 13b: a messenger appointed where the post is vacant (switch on, a grown fort); Make contact named, one at a time")
def _():
    offices = {"offices": {"MESSENGER": {"vacant": 1, "held": [], "appointable": True}}}
    s = fort({}, offices=offices)
    p = by_rule(plan(s, Memory())[0], "messenger")
    assert p and p[0].action == {"type": "appoint", "office": "MESSENGER"}, p
    off = fort({}, offices=offices)
    off["settings"]["make_contact"] = False
    assert not by_rule(plan(off, Memory())[0], "messenger")
    held = {"offices": {"MESSENGER": {"vacant": 0, "held": ["Urist"], "appointable": True}}}
    sites = {"nearest": [{"id": 7, "name": "Far Hall", "relation": "Peace", "dist": 3},
                         {"id": 9, "name": "Cottageflings", "relation": "NoContact", "dist": 5},
                         {"id": 8, "name": "Dark Pits", "relation": "NoContact", "dist": 12}]}
    s = fort({}, offices=held, missions={"controllers": [], "sites": sites})
    m = Memory()
    note_cycle(s, m)
    _, notes = plan(s, m)
    assert any("Make contact (13b)" in n and "Cottageflings" in n for n in notes), notes
    note_cycle(s, m)                                              # said once a season, not every cycle
    s["date"]["tick"] += 1200
    note_cycle(s, m)
    assert not any("Make contact (13b)" in n for n in plan(s, m)[1])
    out = fort({}, offices=held, missions={"controllers": [{"goal": "DIPLOMACY", "site": "Cottageflings",
                                                             "returning": True}], "sites": sites})
    notes = plan(out, Memory())[1]
    assert any("on the way home from Cottageflings" in n for n in notes), notes
    assert not any("Make contact (13b)" in n for n in notes)


@test("planner 13b (0.105.24): with send_messenger on, one send_mission to the nearest site not in contact; waits for the run, "
      "the messenger's return, a stopped run (a year), the World button; off: the site named for the player")
def _():
    held = {"offices": {"MESSENGER": {"vacant": 0, "held": ["Urist"], "appointable": True}}}
    sites = {"nearest": [{"id": 7, "name": "Far Hall", "relation": "Peace", "dist": 3},
                         {"id": 9, "name": "Cottageflings", "relation": "NoContact", "dist": 5},
                         {"id": 8, "name": "Dark Pits", "relation": "NoContact", "dist": 12}]}
    send = {"buttons": ["Diplomacy", "World"], "on": True}

    def mk(send_=send, on=True, controllers=()):
        st = fort({}, offices=held, missions={"controllers": list(controllers), "sites": sites, "send": send_})
        st["settings"]["send_messenger"] = on
        return st

    s = mk()
    m = Memory()
    note_cycle(s, m)
    props, notes = plan(s, m)
    p = by_rule(props, "contact")
    assert p and p[0].action == {"type": "send_mission", "goal": "make_contact", "site_id": 9}, p
    assert "Cottageflings" in p[0].reason and not any("Make contact (13b)" in n for n in notes), notes
    import overseer
    assert "make contact" in overseer.short(p[0].action)
    # the default is off: the site is named for the player instead, the switch mentioned
    assert player_rules({"settings": {}})["send_messenger"] is False
    off = mk(on=False)
    props, notes = plan(off, Memory())
    assert not by_rule(props, "contact")
    assert any("Make contact (13b)" in n and "Send it by the World screen" in n for n in notes), notes
    # an older bridge (no `send` in the report): nothing sent
    assert not by_rule(plan(mk(send_={}), Memory())[0], "contact")
    # the World button never shown: the Needs-you says how, nothing sent
    props, notes = plan(mk(send_={"buttons": [], "on": True}), Memory())
    assert not by_rule(props, "contact")
    assert any("--here World" in n and "--here Diplomacy" in n for n in notes), notes
    # a run under way, or the messenger out: one at a time
    props, notes = plan(mk(send_=dict(send, running={"site_id": 9, "step": "site"})), Memory())
    assert not by_rule(props, "contact") and any("being sent" in n for n in notes), notes
    props, notes = plan(mk(controllers=[{"goal": "DIPLOMACY", "site": "Cottageflings", "returning": False}]), Memory())
    assert not by_rule(props, "contact") and any("away to Cottageflings" in n for n in notes), notes
    # the last run stopped (a step never recorded): said, not tried again for a year
    now = W.abs_tick(s)
    stopped = dict(send, last={"site_id": 9, "site": "Cottageflings", "result": "stopped", "step": "make_contact",
                               "reason": "not_recorded", "why": "never been recorded", "tick": now - 1000,
                               "controller_left": True})
    props, notes = plan(mk(send_=stopped), Memory())
    assert not by_rule(props, "contact")
    assert any("stopped at the World screen's \"make_contact\" step" in n and "army controller was left" in n
               for n in notes), notes
    old = dict(send, last=dict(stopped["last"], tick=now - W.TICKS_PER_YEAR - 1))
    assert by_rule(plan(mk(send_=old), Memory())[0], "contact")
    # sent this season: waits for its controller to show
    sent = dict(send, last={"site_id": 9, "result": "sent", "tick": now - 100})
    assert not by_rule(plan(mk(send_=sent), Memory())[0], "contact")
    # a threat near: not sent
    s = mk()
    s["settings"]["send_messenger"] = True
    import planner_world
    orig = planner_world.reachable_threats
    planner_world.reachable_threats = lambda *a, **k: [{"name": "goblin"}]
    try:
        props, notes = plan(s, Memory())
    finally:
        planner_world.reachable_threats = orig
    assert not by_rule(props, "contact") and any("not while a threat is near" in n for n in notes), notes


@test("(0.105.24) the bridge: send_mission in the action table, checked, to ai-mission-send; mission_here; the switch on the Rules")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(src, "send_mission = act_send_mission,") and code_has(src, "mission_here = cmd_mission_here,")
    assert code_has(src, "reqscript('ai-mission-send').status()") and code_has(src, "send_mission = {'missions'}")
    import test_bridge_memory as tbm
    tbm.reset()
    M = tbm.H.module()
    tbm.LUA.execute("""local M, H = ...
      H.calls = {}
      H.scripts = {['ai-mission-send'] = {start = function(a) table.insert(H.calls, a); return {ok = true, sending = true} end}}
    """, M, tbm.H)
    assert tbm.LUA.eval("function(M) return M.ACTIONS.send_mission == M.act_send_mission end")(M)
    r = M.act_send_mission(tbm.t({"site_id": 42, "goal": "make_contact"}))
    assert r.ok and tbm.H.calls[1].site_id == 42 and tbm.H.calls[1].goal == "make_contact" and tbm.H.calls[1].dry_run is False
    for bad in ({"site_id": -1}, {"site_id": "x"}, {}, {"site_id": 4, "goal": "raid"}):
        r = M.act_send_mission(tbm.t(bad))
        assert not r.ok and r.rejected, bad
    assert len(tbm.H.calls) == 1
    lua = LuaRuntime(unpack_returned_tuples=True)
    ssrc = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    S = lua.eval("""function(src)
      local env = setmetatable({dfhack_flags = {module = true}, dfhack = {getDFPath = function() return '.' end,
                                          isMapLoaded = function() return false end}}, {__index = _G})
      env.require = function(n) if n == 'json' then return {} end return require(n) end
      assert(load(src, 'settings', 't', env))()
      return env end""")(ssrc)
    d = S.defaults()
    assert d.send_messenger is False and S.for_ai(d).send_messenger is False
    s2 = S.sanitize(lua.table_from({"send_messenger": True}))
    assert s2.send_messenger is True and S.for_ai(s2).send_messenger is True
    assert player_rules({"settings": {"send_messenger": True}})["send_messenger"] is True
    gui = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")
    assert code_has(gui, "view_id = 'send_messenger'") and code_has(gui, "p:set_field('send_messenger', v)")
    assert code_has(gui, "self.subviews.send_messenger:setOption(")
    ok = lua.eval("function(src) local f, e = load(src, 'm', 't', {}); return f ~= nil, e end")(
        module_src("ai-mission-send.lua"))
    assert ok[0], ok


if __name__ == "__main__":
    finish()
