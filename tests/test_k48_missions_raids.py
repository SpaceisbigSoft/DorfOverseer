"""(0.105.48, K9) Missions, raids and trade, from the audit (A8): switched off
by default until watched live, and the certain bugs fixed so they're right
when turned back on.

  * the defaults: raid_policy 'off', send_missions and send_messenger off; no
    built-in preset turns them on;
  * raids: only sites people live in (never a monument), never the civ the
    messenger is making contact with; retaliation only while still at war
    and never against a trade partner; 0 residents read as unknown;
  * missions: a squad with nobody out (no controller) is never a mission
    out; a member gone from the map doesn't make a squad "not all armed";
    no send (nor pets let out) before DF's World button is known; the World
    button kept for every save on the PC; contact_said stamped only once a
    send went through; the World screen's unattended backstop;
  * trade: the after-check tells a trade answer from a seize's or a gift's;
    a shown place gets the forbidden-word check too;
  * meetings: answered by the planner only unattended; 'small' tribute
    refuses until the sum is seen.

    python tests/test_k48_missions_raids.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
    HAVE_LUPA = True
except ImportError:
    HAVE_LUPA = False

from planner import PLANNER_CONFIG, Memory, Proposal, TICKS_PER_DAY, abs_tick, player_rules, plan  # noqa: E402
import planner as P  # noqa: E402
import planner_missions as PM  # noqa: E402
import planner_raids as PR  # noqa: E402
import planner_world as W  # noqa: E402
import test_r47_raids as TR  # noqa: E402  (its fakes; its tests don't run again)

CFG = PLANNER_CONFIG
LUA_DIR = ROOT / "lua"


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


# --- the defaults ------------------------------------------------------------------------

@test("defaults: raid_policy off, send_missions and send_messenger off (the brain's fallbacks too)")
def _():
    r = player_rules({"settings": {}})
    assert r["raid_policy"] == "off" and r["send_missions"] is False and r["send_messenger"] is False, r
    assert PR.raid_stance({"settings": {}})[0] == "off"
    src = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    assert code_has(src, "raid_policy = 'off',") and code_has(src, "send_missions = false,") \
        and code_has(src, "send_messenger = false,")
    acts = (LUA_DIR / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    i = acts.index("function send_raid_policy()")
    assert "return 'off'" in acts[i:i + 400]


@test("presets: no built-in preset names send_messenger, send_missions or raid_policy (they never turn them on)")
def _():
    src = (LUA_DIR / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    a = src.index("BUILTIN_PRESET_RULES = {")
    block = src[a:src.index("\n}\n", a)]
    for k in ("send_messenger", "send_missions", "raid_policy"):
        assert k not in block, k
    assert block.count("missions = 'all'") == 6


# --- raids --------------------------------------------------------------------------------

def site(sid, civ_id, dist, pop=10, typ="Camp", **kw):
    return TR.site(sid, civ_id, dist, pop=pop, typ=typ, **kw)


@test("raids (A8 #3): the aggressive fort never raids a monument, a lair or an empty site, only where people live")
def _():
    rows = [site(1, 40, 2, pop=0, typ="Monument"), site(2, 41, 3, pop=0, typ="Camp"), site(3, 42, 3, pop=5, typ="LairShrine"),
            site(4, 43, 9, pop=12, typ="Hamlet")]
    p, notes = TR.rule(TR.fort(rows, militarism=150), TR.Mem())
    a = TR.sent(p)
    assert len(a) == 1 and a[0].action["site_id"] == 4, (p, notes)
    words = PR.raid_candidates(TR.fort(rows, militarism=150), memory=TR.Mem())[1]
    assert any("3 site(s) nobody lives in" in n for n in words), words
    # only monuments: nothing at all
    p, _ = TR.rule(TR.fort(rows[:3], militarism=150), TR.Mem())
    assert not TR.sent(p)


@test("raids (A8 #3): never the civ the fort is making contact with (the site named, the messenger out, its last send)")
def _():
    rows = [site(4, 43, 9, pop=12, typ="Hamlet"), site(5, 44, 12, pop=12, typ="Town")]
    s = TR.fort(rows, militarism=150)
    s["missions"]["sites"] = {"nearest": [{"id": 4, "owner_civ": 43, "relation": "unknown", "dist": 9}]}
    s["missions"]["controllers"] = [{"id": 70, "goal": "DIPLOMACY", "site_id": 4, "site": "Site4"}]
    a = TR.sent(TR.rule(s, TR.Mem())[0])
    assert a and a[0].action["site_id"] == 5, a
    assert 43 in PR.contact_civs(s, TR.Mem())
    s2 = TR.fort(rows, militarism=150, send=TR.button({"make_contact": {"goal": "make_contact", "result": "sent",
                                                                        "site_id": 4, "tick": TR.NOW - 10 * TICKS_PER_DAY}}))
    assert TR.sent(TR.rule(s2, TR.Mem())[0])[0].action["site_id"] == 5
    # the site Make contact names now (a messenger home, the site not in contact)
    s3 = TR.fort(rows, militarism=150)
    s3["missions"]["sites"] = {"nearest": [{"id": 4, "owner_civ": 43, "relation": "NoContact", "dist": 9}]}
    s3["offices"] = {"offices": {"MESSENGER": {"held": ["Urist"], "vacant": 0}}}
    assert TR.sent(TR.rule(s3, TR.Mem())[0])[0].action["site_id"] == 5
    # without any of these the nearer one goes (the test can fail)
    assert TR.sent(TR.rule(TR.fort(rows, militarism=150), TR.Mem())[0])[0].action["site_id"] == 4


@test("raids (A8 #4): a reactive fort doesn't retaliate against a civ now at peace, nor a trade partner at war")
def _():
    rows = [site(2, 30, 20, pop=10)]
    sieges = [{"id": 30, "n": 1, "last_year": 147, "last_siege": True, "name": "The Humans"}]
    peace = {"civs": [{"id": 30, "relation": "Peace"}], "sieges": sieges,
             "caravans": [{"civ_id": 30, "civ": "Civ30", "state": "AtDepot"}]}
    p, notes = TR.rule(TR.fort(rows, world=peace))
    assert not TR.sent(p), p
    peace2 = {"civs": [{"id": 30, "relation": "Peace"}], "sieges": sieges}
    p, notes = TR.rule(TR.fort(rows, world=peace2))
    assert not TR.sent(p) and any("is at Peace now: left alone" in n for n in notes), notes
    war = {"civs": [{"id": 30, "relation": "TotalWar"}], "sieges": sieges}
    assert TR.sent(TR.rule(TR.fort(rows, world=war))[0])                  # at war: it goes
    m = TR.Mem()
    m.missions_seen = {"raids": {"traders": {"30": {"n": 3, "last": 1}}}}
    p, notes = TR.rule(TR.fort(rows, world=war), m)
    assert not TR.sent(p) and any("traded with" in n for n in notes), notes


@test("raids (A8 #12): 0 residents at a lived-in type is unknown strength, not 4 x weight")
def _():
    assert PR.site_strength({"pop": 0, "type": "DarkFortress"}) == PR.site_strength({"pop": None, "type": "DarkFortress"})
    assert PR.site_strength({"pop": 0, "type": "DarkFortress"}) > 30
    assert PR.site_strength({"pop": 10, "type": "Camp"}) == (4.0 + 5.0) * 0.8


if HAVE_LUPA:
    ADD_SITES = r"""
local env, G = ...
env.df.world_site_type = {[9] = 'Camp', [11] = 'Monument', [1] = 'DarkFortress'}
local sites = env.df.global.world.world_data.sites
local function S(id, x, y, civ, typ, rc, kw)
  local s = {id = id, pos = {x = x, y = y}, civ_id = civ, cur_owner_id = -1, type = typ, resident_count = rc,
             flag = {HIDDEN = false, RUINED = false}, name = 'Site' .. id, land = 1}
  for k, v in pairs(kw or {}) do s[k] = v end
  sites:insert('#', s)
end
S(20, 50, 52, 21, 11, 0)                                 -- a monument: never a row
S(21, 50, 53, 50, 1, 0, {populace = {inhabitants = G.vec({{count = 30}, {count = 5}}), nemesis = G.vec({1, 2})}})
S(22, 50, 54, 50, 1, 0, {populace = {inhabitants = G.vec({}), nemesis = G.vec({})}})
"""

    @test("ai-raids (A8 #3, #12): raid_sites never lists a monument; resident_count 0 read from the populace, else unknown")
    def _():
        lua, env, G = TR.lua_env()
        lua.execute(ADD_SITES, env, G)
        by = {x.site_id: x for x in lst(env.raid_sites().rows)}
        assert 20 not in by, sorted(by)
        assert by[21].pop == 37 and by[21].type == "DarkFortress", by[21].pop
        assert 22 in by and by[22].pop is None
        assert by[1].pop == 12                       # resident_count read as before


# --- missions -----------------------------------------------------------------------------

@test("missions (A8 #2): a squad 'away' with no controller is never a mission out; a gone member isn't counted unarmed")
def _():
    s = TR.fort([site(5, 50, 6, relation="TotalWar", hostile=True, at_war=True)])
    s["missions"]["squads"][0]["away"] = 1
    assert PM._fort_missions_out(s) == []
    s["missions"]["squads"][0]["controller"] = 77
    assert PM._fort_missions_out(s)
    q = copy.deepcopy(s["military"]["squads"][0])
    q["power"]["armed"] = q["members"] - 1
    away = {q["id"]: {"id": q["id"], "away": 0}}
    assert PM._squad_free(q, away) == "not all armed"
    away[q["id"]]["gone"] = 1
    assert PM._squad_free(q, away) is None


if HAVE_LUPA:
    import test_missions as TM  # noqa: E402

    @test("ai-missions (A8 #2): a member gone from the map counts as away only in a squad with a controller")
    def _():
        env = TM.world(r"""
B.dwarf(1001, 1, {inactive = true})           -- left the map, no army
B.dwarf(1002, 2, {no_unit = true})
B.dwarf(1003, 3)
B.dwarf(1004, 4, {army = 7})                  -- on an army's roll: away whatever
B.squad(1, 'Idle', {1001, 1002, 1003}, nil)
B.squad(2, 'Out', {1001}, 5)
B.squad(3, 'Marching', {1004}, nil)
B.controller{id = 5, entity_id = 200, goal = B.G.SITE_INVASION, site_id = -1, assigned_squads = {2}, data = B.S{}}
""")
        sq = {s.id: s for s in TM.lst(env.report().squads)}
        assert sq[1].away == 0 and sq[1].gone == 2, (sq[1].away, sq[1].gone)
        assert sorted(k for k, v in env.away_units().items() if v) == [1, 4]      # the controller's squad, the army
        assert sq[2].away == 1 and sq[2].gone is None
        assert sq[3].away == 1


@test("missions (A8 #6): no send and no pets let out before DF's World button is known; the Needs you says how")
def _():
    rows = [site(5, 50, 6, relation="TotalWar", hostile=True, at_war=True)]
    pets = {"held": [{"pet_id": 501, "unit_id": 301, "squad_id": 11, "held": "pasture", "ai": True, "zone_id": 900}]}
    send = TR.button()
    send["buttons"] = ["Diplomacy"]
    p, notes = TR.rule(TR.fort(rows, send=send, pets=pets))
    assert not TR.sent(p) and not [x for x in p if x.action.get("type") == "mission_pets"], [x.action for x in p]
    assert any("--here World" in n for n in notes), notes
    p, _ = TR.rule(TR.fort(rows, pets=pets))
    assert [x for x in p if x.action.get("type") == "mission_pets"]      # with the button: let out first


@test("missions (A8 #5): contact_said is stamped when the send went through, not when the site is due")
def _():
    held = {"offices": {"MESSENGER": {"vacant": 0, "held": ["Urist"], "appointable": True}}}
    sites = {"nearest": [{"id": 9, "name": "Cottageflings", "relation": "NoContact", "dist": 5, "owner_civ": 30}]}
    s = TR.fort()
    s["offices"] = held
    s["missions"]["sites"] = sites
    s["settings"]["send_messenger"] = True
    m = Memory()
    W.note_world(s, m)
    assert "contact_said" not in m.world_seen, m.world_seen
    p = Proposal("contact", {"type": "send_mission", "goal": "make_contact", "site_id": 9}, "send", 7)
    W.note_contact_sent(p, {"ok": False, "waiting": True}, s, m)
    assert "contact_said" not in m.world_seen
    assert W._contact_site(s, m) is not None                 # tried again next cycle
    P.record([(p, {"ok": True, "sending": True})], s, m)
    assert m.world_seen["contact_said"] == abs_tick(s)
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += TICKS_PER_DAY
    assert W._contact_site(s2, m) is None                    # named: not again this season
    # the switch off: named for the player, stamped as before
    s3 = copy.deepcopy(s)
    s3["settings"]["send_messenger"] = False
    m3 = Memory()
    W.note_world(s3, m3)
    assert m3.world_seen["contact_said"] == abs_tick(s3)


if HAVE_LUPA:
    import test_mission_send as TS  # noqa: E402

    SB_HOOK = r"""
local env, G, sbsrc = ...
local orig = env.reqscript
local SB
env.reqscript = function(n)
  if n == 'ai-screen-buttons' then
    if not SB then SB = setmetatable({}, {__index = env}); assert(load(sbsrc, 'ai-screen-buttons', 't', SB))() end
    return SB
  end
  return orig(n)
end
"""
    PC_FILE = "/df/dfhack-config/ai-overseer/screen-buttons.json"

    @test("ai-mission-send (A8 #6): the World button shown in any save on this PC serves a new fort; a shown one is shared")
    def _():
        env, G = TS.world()
        TS.LUA.execute(SB_HOOK, env, G, module_src("ai-screen-buttons.lua"))
        assert env.buttons().World is None
        G.files[PC_FILE] = TS.LUA.table_from({"buttons": TS.LUA.table_from({
            "ai-overseer/world-buttons": TS.LUA.table_from({"World": TS.LUA.table_from(
                {"anchor": "left-bottom", "lx": 3, "by": 2})})})})
        b = env.buttons()
        assert b.World and b.World["from"] == "pc" and env.button_at(b.World) == (3, 38)
        assert "World" in lst(env.status().buttons)
        # a save that had it before 0.105.48: copied to the PC's file once
        env2, G2 = TS.world("G.calibrate_all()")
        TS.LUA.execute(SB_HOOK, env2, G2, module_src("ai-screen-buttons.lua"))
        env2.buttons()
        assert G2.files[PC_FILE].buttons["ai-overseer/world-buttons"].World.lx == 3

    @test("ai-mission-send (A8 #1): leave_world presses Esc while the World screen is on top; never under a live run")
    def _():
        env, G = TS.world("G.calibrate_all()")
        assert env.leave_world().ok is False                           # nothing open
        G.screen_new()
        r = env.leave_world(True)
        assert r.ok and r.dry_run and G.screen is not None and len(lst(G.inputs)) == 0
        r = env.leave_world()
        assert r.ok and r.closing and G.screen is None, dict(r)
        assert lst(G.inputs) == ["LEAVESCREEN"]
        # a run under way (not stale) is never cut short
        env, G = TS.world("G.calibrate_all()")
        assert TS.start(env).ok
        G.screen_new()
        r = env.leave_world()
        assert r.ok is False and r.waiting, dict(r)


@test("overseer (A8 #1): the World screen left after WORLD_CLOSE_S unattended, never attended, halted or pinned")
def _():
    import overseer as O
    st = {"in_fort": True, "world_open": True}
    T = O.WORLD_CLOSE_S
    assert O.world_leave_due(st, 0.0, float("-inf"), T, True, True, False, None, False)
    assert not O.world_leave_due(st, 0.0, float("-inf"), T - 1, True, True, False, None, False)
    assert not O.world_leave_due(st, 0.0, float("-inf"), T, False, True, False, None, False)    # attended
    assert not O.world_leave_due(st, 0.0, float("-inf"), T, True, True, True, None, False)      # halted
    assert not O.world_leave_due(st, 0.0, float("-inf"), T, True, True, False, "pin", False)
    assert not O.world_leave_due(st, 0.0, T - 10, T, True, True, False, None, False)          # tried lately
    assert not O.world_leave_due({"in_fort": True}, 0.0, float("-inf"), T, True, True, False, None, False)
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert 'bridge.act({"type": "close_world"})' in src and '"close_world": "leave DF\'s World screen"' in src
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(hub, "close_world = function(a)") and code_has(hub, "BATCH_NEVER.close_world = true")
    assert code_has(hub, "'close_world',") and code_has(hub, "world_open = (function()")
    import bridge
    assert "close_world" in bridge.BATCH_NEVER


# --- trade ----------------------------------------------------------------------------------

if HAVE_LUPA:
    import test_r47_meetings_trade as TMT  # noqa: E402

    ENUM = r"""
local env = ...
local t = env.df.talk_line_type
t[1], t[9], t[10], t[11], t[12] = 'Greet', 'Offer', 'Seize', 'OfferJoke', 'SeizeJoke'
"""

    @test("trade (A8 #9): after_verdict: a trade answer worked; a seize's or gift's line, or goods gone silently, wrong")
    def _():
        lua, env, *_ = TMT.trade_env()
        assert env.after_verdict("Greet", "Trade", False, False) == "worked"
        assert env.after_verdict("Greet", "Haggle", False, False) == "worked"
        assert env.after_verdict("Greet", "Greet", False, True) == "worked"            # a counter-offer
        assert env.after_verdict("Greet", "Seize", True, False) == "wrong"
        assert env.after_verdict("Greet", "Offer", True, False) == "wrong"
        assert env.after_verdict("Greet", "Greet", True, False) == "wrong"
        assert env.after_verdict("Greet", "Greet", False, False) == "none"

    @test("trade (A8 #9): a guess pressed on a screen that opened on Greet and got no answer is a miss, not promoted")
    def _():
        lua, env, B, mf, ff, clicks = TMT.trade_env()
        lua.execute(ENUM, env)
        lua.execute(r"""local env = ...
            local t = env.df.global.game.main_interface.trade
            t.talkline = 1                                  -- the screen opens on Greet
            env.require = function(name)
              if name == 'json' then
                return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
                        encode_file = function(d, p) env.FILES[p] = d end}
              end
              return {simulateInput = function(_, key) if key == 'LEAVESCREEN' then t.open = false end end}
            end""", env)
        TMT.paint(lua, env, 56, 58, "Trade")
        env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
        p = env.press("Trade", None)
        assert p.verdict == "none" and p.answer == "Greet", dict(p)
        f = B.read_file()
        tb = f.buttons["ai-overseer/trade-buttons"] if f.buttons else None
        assert not (tb and tb.Trade), "a miss must not be kept as a known place"
        assert f.misses["ai-overseer/trade-buttons"].Trade == 1
        tr = env.df["global"].game.main_interface.trade
        assert env.is_done(tr.mer)                          # closed: not opened again this visit

    @test("trade (A8 #9): a guess that brought a seize's line is retired at once and the press is not ok")
    def _():
        lua, env, B, mf, ff, clicks = TMT.trade_env()
        lua.execute(ENUM, env)
        lua.execute(r"""local env = ...
            local t = env.df.global.game.main_interface.trade
            t.talkline = 1
            env.require = function(name)
              if name == 'json' then
                return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
                        encode_file = function(d, p) env.FILES[p] = d end}
              end
              return {simulateInput = function(_, key)
                if key == 'LEAVESCREEN' then t.open = false; return end
                t.talkline = 10
                local v = {[0] = t.good[0][6]}
                t.good[0] = setmetatable(v, {__len = function() return 1 end})
                t.goodflag[0] = setmetatable({[0] = {selected = false}}, {__len = function() return 1 end})
              end}
            end""", env)
        TMT.paint(lua, env, 56, 58, "Trade")
        env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
        p = env.press("Trade", None)
        assert p.ok is False and p.verdict == "wrong" and "Seize" in p.error, dict(p)
        assert B.read_file().retired["ai-overseer/trade-buttons"].Trade

    @test("trade (A8 #10): a shown place where the screen now reads Seize is not pressed; unreadable text still is")
    def _():
        lua, env, B, mf, ff, clicks = TMT.trade_env()
        lua.execute("""local env = ...
            env.dfhack.persistent.saveSiteData('ai-overseer/trade-buttons',
                {Trade = {anchor = 'centre-bottom', dx = 0, dy = 5}})""", env)
        TMT.paint(lua, env, 58, 55, "Seize")                 # (60, 55): the shown place
        env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
        p = env.press("Trade", None)
        assert p.ok is False and p.guess_refused == "forbidden" and "Seize" in p.error, dict(p)
        assert all(lst(clicks[i])[2] != "_MOUSE_L" for i in range(1, len(clicks) + 1))


# --- meetings and tribute -------------------------------------------------------------------

@test("meetings (A8 #16): the planner answers DF's meeting screen only unattended; attended it's left to the player")
def _():
    import test_world as TW
    m = {"open": True, "civ": "Elves", "topic": "TreeQuota", "buttons": ["No", "Yes"]}
    s = TW.fort({"meeting": m})
    props, notes = plan(s, Memory())
    assert not TW.by_rule(props, "meeting") and any("left to you" in n for n in notes), notes
    s["unattended"] = True
    assert TW.by_rule(plan(s, Memory())[0], "meeting")
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert 'state["unattended"] = bool(controls.get("unattended") or os.environ.get("DFAI_PIN"))' in src


if HAVE_LUPA:
    @test("tribute (A8 #14): 'small' answers No until the sum asked is seen (the amount read is DF's topic index)")
    def _():
        import test_world as TW
        env, _ = TW.world()
        ctx = TW.LUA.table_from({"amount": 3, "wealth": 10000})
        assert env.decide("TributeAgreement", "small", ctx)[0] == "no"
        assert env.press_guard(TW.LUA.table_from(["TributeAgreement"]), "small") is None
        tribute = TW.MEETING + "df.global.game.main_interface.diplomacy.dipev.topic_list = G.vec({9}); " \
                               "df.global.game.main_interface.diplomacy.dipev.agreement_topic = G.vec({}); " \
                               "df.global.game.main_interface.diplomacy.dipev.topic_parms = G.vec({2})"
        env, G = TW.world(tribute)
        r = env.answer_meeting(TW.LUA.table_from({"dry_run": True}))
        assert r.ok and r.answer == "no", dict(r)


if __name__ == "__main__":
    finish()
