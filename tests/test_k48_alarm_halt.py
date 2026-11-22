"""(0.105.48, K3) Alarm, burrows and halt (audits A1, A7, A9):

  1. the loop guard and the refusal back-off keyed a release with its
     confine (calm_burrow / calm_burrow release): the release now has its own
     key and is never loop-held;
  2. the game keeps the AI's alarm ownership: a stand-down (halted: at once;
     the overseer away or stopping: no enemy in sight, or the brain away three
     days) lowers only the AI's own alarm, and lets out the AI's own burrows;
  3. ai-status: halting stands the AI down at once; the away watcher stands it
     down with no status call for AWAY_TICKS;
  4. halted, the gate watcher only releases; the shaft and well watches and
     the mission screen driver do nothing;
  5. the bridge lets the undoing steps through the halt (alarm lowered,
     burrows emptied, the way out's leave), never the confining ones;
  6. train_cook keeps ONE kitchen for its trainee, and a trainee moody,
     waiting for treatment or kept in a burrow is not free to cook.

    python tests/test_k48_alarm_halt.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_core as PC  # noqa: E402
from planner_core import Memory, Proposal, TICKS_PER_DAY  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

LUA_DIR = ROOT / "lua"


def _fake(file: str, name: str) -> str:
    tree = ast.parse((ROOT / "tests" / file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


# --- 1. the loop guard and the refusals: a release keyed apart ------------------------

@test("loop guard: a burrow's release has its own key, is never loop-held, and the confine's refusals don't back it off")
def _():
    now = 50 * PC.TICKS_PER_YEAR
    confine = Proposal("calm_burrow", {"type": "calm_burrow", "max": 6, "days": 3}, "a tantrum", 5)
    release = Proposal("calm_burrow", {"type": "calm_burrow", "release": True}, "let out", 5)
    assert PC.refusal_key(confine) != PC.refusal_key(release)
    m = Memory()
    m.action_log = {PC.refusal_key(confine): [now - 100 * i for i in range(1, 100)],
                    PC.refusal_key(release): [now - 100 * i for i in range(1, 100)]}
    assert PC._loop_count(m, confine, now) is not None          # the confine: held as a loop, as before
    assert PC._loop_count(m, release, now) is None              # the release: never
    m.refusals = {}
    for _ in range(6):
        PC.note_refusal(m, confine, {"ok": False, "error": "no free bedroom"}, now)
    assert PC._refused_wait(m, confine, now) is not None
    assert PC._refused_wait(m, release, now + TICKS_PER_DAY) is None
    # the alarm and the near-gates switch likewise: on and off apart
    on = Proposal("near_gates", {"type": "near_gates", "on": True}, "", 5)
    off = Proposal("near_gates", {"type": "near_gates", "on": False}, "", 5)
    assert PC.refusal_key(on) != PC.refusal_key(off)
    assert PC.is_release(off.action) and not PC.is_release(on.action)
    m.action_log = {PC.refusal_key(off): [now - 100 * i for i in range(1, 100)]}
    assert PC._loop_count(m, off, now) is None


# --- 2. ai-society: the AI's alarm, and standing down ---------------------------------------

SOC_EXTRA = r"""
local env = ...
env.df.global.plotinfo.alerts = {civ_alert_idx = 0, list = {}}
DANGERS = {}
CLEARED = 0
SOC_SCRIPTS = {
  ['gui/civ-alert'] = {clear_alarm = function() CLEARED = CLEARED + 1; env.df.global.plotinfo.alerts.civ_alert_idx = 0 end},
  ['ai-gates'] = {visible_dangers = function() return DANGERS end},
}
env.dfhack.gui = {showAnnouncement = function() end}
env.COLOR_GREEN = 2
"""


def soc():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("reqscript = function(n) if SOC_SCRIPTS and SOC_SCRIPTS[n] then return SOC_SCRIPTS[n] end "
                "error('no module ' .. tostring(n)) end")
    env, units, assigned, ntiles, g = lua.execute(_fake("test_society.py", "FAKE"), module_src("ai-society.lua"))
    lua.execute(SOC_EXTRA, env)
    return lua, env, assigned


if LuaRuntime:
    @test("ai-society: the AI's alarm booked; lowered by a stand-down with no enemy in sight, kept with one "
          "(lowered all the same when halted or the brain away three days); the player's alarm never")
    def _():
        lua, env, _ = soc()
        al = getattr(env.df, "global").plotinfo.alerts
        # the player's alarm: no booking, never lowered, even halted
        al.civ_alert_idx = 1
        r = env.stand_down(lua.eval("{halted = true}"))
        assert r.alarm is None and al.civ_alert_idx == 1
        # the AI's: booked, an invader in sight keeps it while the brain is away a little
        env.note_ai_alarm(True)
        assert env.ai_alarm_mine() is True
        lua.execute("DANGERS = {{pos = {x = 1, y = 1, z = 1}, invader = true}}")
        r = env.stand_down(lua.eval("{away_ticks = 2500}"))
        assert r.alarm == "kept" and al.civ_alert_idx == 1
        r = env.stand_down(lua.eval("{away_ticks = 3 * 1200}"))           # away three days: lowered anyway
        assert r.alarm == "lowered" and al.civ_alert_idx == 0 and env.ai_alarm_mine() is False
        # halted: lowered at once, enemy or not
        al.civ_alert_idx = 1
        env.note_ai_alarm(True)
        r = env.stand_down(lua.eval("{halted = true}"))
        assert r.alarm == "lowered" and al.civ_alert_idx == 0
        # stopping with nothing in sight: lowered; a dry run changes nothing
        lua.execute("DANGERS = {{pos = {x = 1, y = 1, z = 1}}}")           # a wild animal: no enemy
        al.civ_alert_idx = 1
        env.note_ai_alarm(True)
        r = env.stand_down(lua.eval("{stopping = true, dry_run = true}"))
        assert r.alarm == "lowered" and al.civ_alert_idx == 1
        r = env.stand_down(lua.eval("{stopping = true}"))
        assert r.alarm == "lowered" and al.civ_alert_idx == 0

    @test("ai-society: the alarm found off forgets the booking; the player's alarm raised after it is never lowered")
    def _():
        lua, env, _ = soc()
        al = getattr(env.df, "global").plotinfo.alerts
        al.civ_alert_idx = 1
        env.note_ai_alarm(True)
        al.civ_alert_idx = 0                         # the player lowered it
        assert env.ai_alarm_mine() is False
        al.civ_alert_idx = 1                         # and raised their own
        r = env.stand_down(lua.eval("{halted = true}"))
        assert r.alarm is None and al.civ_alert_idx == 1, dict(r)

    @test("ai-society stand_down: the AI's burrows let out (the weather keep-in's and the recreation burrow's "
          "own members); the player's shelter members stay; nothing kept: nothing done")
    def _():
        lua, env, assigned = soc()
        lua.execute("""local env = ...
            local b = {id = 9, name = 'AI shelter', units = {}}
            B9 = b
            -- (0.105.48 merge, K3 shelter group) the keep-in's shelter check: a well-stocked one here
            env.shelter_for_keep_in = function(force) return {tiles = 30, redrawn = force} end
            env.df.global.plotinfo.burrows.list[#env.df.global.plotinfo.burrows.list] = b
            env.dfhack.burrows.listBlocks = function() return {1, 2} end""", env)
        r = env.stand_down(lua.eval("{}"))
        assert r.burrows is None, dict(r)
        lua.execute("local env = ...; env.df.unit.find(2).burrows = {9}; B9.units = {2}", env)   # the player's own member (0.105.48 merge: the burrow's own list, no listUnits)
        r = env.weather_keep_in(True, False)
        assert r.added == 5 and not assigned[2], dict(r)
        assigned[2] = True
        rec = lua.eval("{members = {['7'] = 1}, out = {}}")
        env.dfhack.persistent.saveSiteData("ai-overseer/recreation", rec)
        lua.execute("""local env = ...
            local rb = {id = 11, name = 'AI recreation'}
            env.df.global.plotinfo.burrows.list[#env.df.global.plotinfo.burrows.list] = rb""", env)
        r = env.stand_down(lua.eval("{away_ticks = 2500}"))
        assert r.burrows.weather == 5 and r.burrows.recreation == 1, dict(r.burrows)
        assert assigned[2] is True and not any(assigned[i] for i in (1, 4, 5, 6, 7)), dict(assigned)
        assert env.weather_keep_in_status().members == 0
        assert env.stand_down(lua.eval("{}")).burrows is None             # emptied: nothing more


# --- 3. ai-status: the halt and the away watcher --------------------------------------------

STATUS = r"""
local src = ...
local save = {}
CALLS = {}
NOWT = 10 * 403200 + 1000
_G.SC_MAP_UNLOADED = 99
_G.df = {global = {cur_year = 10, cur_year_tick = 1000}}
_G.dfhack = {isMapLoaded = function() return true end, onStateChange = {},
  persistent = {getSiteData = function(k, d) return save[k] or d end,
                saveSiteData = function(k, v) save[k] = v end},
  gui = {showAnnouncement = function() end}}
_G.COLOR_LIGHTRED, _G.COLOR_LIGHTGREEN = 12, 10
local soc = {stand_down = function(o) table.insert(CALLS, o); return {alarm = 'lowered'} end,
             ai_alarm_mine = function() MINE_LOOKS = (MINE_LOOKS or 0) + 1; return false end}
_G.reqscript = function(n) if n == 'ai-society' then return soc end error(n) end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-status', 't', env))()
return env
"""

if LuaRuntime:
    @test("ai-status: halting stands the AI down at once (halted, even paused); resuming does not")
    def _():
        L = LuaRuntime(unpack_returned_tuples=True)
        M = L.execute(STATUS, (LUA_DIR / "ai-status.lua").read_text(encoding="utf-8"))
        M.set_halted(True)
        calls = lst(L.eval("CALLS"))
        assert len(calls) == 1 and calls[0].halted is True
        M.set_halted(False)
        assert len(lst(L.eval("CALLS"))) == 1

    @test("ai-status away watcher: a status call keeps the AI attended; none for AWAY_TICKS: stood down "
          "(how long away given); one look per AWAY_LOOK_TICKS; halted: stood down as halted")
    def _():
        L = LuaRuntime(unpack_returned_tuples=True)
        M = L.execute(STATUS, module_src("ai-status.lua"))
        M.mark_seen()
        assert M.away_check(True) is None and len(lst(L.eval("CALLS"))) == 0
        away = int(M.AWAY_TICKS) + 1                      # (round 2) ai-util's brain_away: five days
        M.LAST_SEEN = -1000                               # the last poll long ago in real time too
        L.execute(f"df.global.cur_year_tick = 1000 + {away}")
        assert M.away_check(True) is not None
        calls = lst(L.eval("CALLS"))
        assert len(calls) == 1 and not calls[0].halted and calls[0].away_ticks == away
        L.execute(f"df.global.cur_year_tick = 1000 + {away + 49}")
        assert M.away_check() is None                      # within AWAY_LOOK_TICKS of the last look
        M.mark_seen()                                      # the brain back
        L.execute(f"df.global.cur_year_tick = 1000 + {away + 200}")
        assert M.away_check() is None and len(lst(L.eval("CALLS"))) == 1
        # a reload with no brain at all: counted from the first look
        L2 = LuaRuntime(unpack_returned_tuples=True)
        M2 = L2.execute(STATUS, module_src("ai-status.lua"))
        assert M2.away_check(True) is None
        L2.execute(f"df.global.cur_year_tick = 1000 + {away + 100}")
        assert M2.away_check(True) is not None
        # halted: as halted
        L3 = LuaRuntime(unpack_returned_tuples=True)
        M3 = L3.execute(STATUS, module_src("ai-status.lua"))
        M3.mark_seen()
        L3.execute("dfhack.persistent.saveSiteData('ai-overseer/halt', {halted = true})")
        M3.away_check(True)
        assert lst(L3.eval("CALLS"))[0].halted is True

    @test("ai-overlay starts the away watcher (the panel runs with no overseer)")
    def _():
        src = (LUA_DIR / "ai-overlay.lua").read_text(encoding="utf-8")
        i = src.index("function AIStatusOverlay:overlay_onupdate()")
        assert "away_watch_start" in src[i:src.index("\nend\n", i)]


# --- 4. the in-game timers while halted -------------------------------------------------------

def watch_world(halted=True, dist=100):
    L = LuaRuntime(unpack_returned_tuples=True)
    M = L.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    L.execute(_fake("test_r47_way_out.py", "WATCH"), M)
    L.execute("""M, halted = ...
      M.reqscript = function(name)
        if name == 'ai-mission-way' then return {mission_held = function() return false end} end
        if name == 'ai-status' then return {is_halted = function() return HALTED end} end
        error(name)
      end
      HALTED = halted""", M, halted)
    M.DIST = dist
    return L, M


if LuaRuntime:
    @test("gate watcher halted: never shuts (a danger at the gate), never pulls a held gate back shut, opens what "
          "it holds once nothing is within 2 x IMMINENT for UNATTENDED_CLEAR looks")
    def _():
        L, M = watch_world(dist=3)
        L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
        L.execute("B[7].door_flags.closed = false")
        M.GATES.closed[1] = None
        M.check()
        assert not M.GATES.closed[1] and lst(L.eval("PULLS")) == [] and M.GATES.halted is True
        # unhalted: the same look shuts it (the test fails on the old watcher too)
        L2, M2 = watch_world(halted=False, dist=3)
        L2.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
        L2.execute("B[7].door_flags.closed = false")
        M2.GATES.closed[1] = None
        M2.check()
        assert M2.GATES.closed[1] is True
        # held, found open with a danger near: left open (not pulled back)
        L, M = watch_world(dist=40)
        L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}}}; B[7].door_flags.closed = false")
        M.check()
        assert lst(L.eval("PULLS")) == [] and not M.GATES.closed[1]
        # held and shut, an invader far off: opened after UNATTENDED_CLEAR looks
        L, M = watch_world(dist=100)
        L.execute("DANGERS = {{pos = {x = 0, y = 0, z = 0}, invader = true}}")
        for _ in range(int(M.UNATTENDED_CLEAR)):
            M.check()
        assert not M.GATES.closed[1] and lst(L.eval("PULLS")) == [90]

    @test("timers halted: the shaft watch, the well-safety watch, the mission screen driver and the depot click "
          "ask ai-status first; the link watch waits")
    def _():
        for f, marker in (("ai-builder-wells-watch.lua", "local function shaft_watch_tick()"),
                          ("ai-well-safety.lua", "local function tick()"),
                          ("ai-mission-send-run.lua", "local function tick(run)"),
                          ("ai-gates-watch.lua", "local function link_watch_tick()")):
            src = (LUA_DIR / f).read_text(encoding="utf-8")
            i = src.index(marker)
            body = src[i:src.index("\nend\n", i)]
            assert "ai_halted()" in body or "is_halted()" in body, f
        tr = (LUA_DIR / "ai-trade.lua").read_text(encoding="utf-8")
        i = tr.index("dfhack.timeout(3, 'frames', function()")
        j = tr.index("local okc, err = pcall(click, x, y)", i)
        assert "is_halted()" in tr[i:j]


# --- 5. the bridge: the undoing steps pass the halt -------------------------------------------

if LuaRuntime:
    BL = LuaRuntime(unpack_returned_tuples=True)
    BH = BL.execute(_fake("test_hygiene_bridge.py", "HARNESS"), (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"),
                    str(LUA_DIR))
    BM = BH.module()

    @test("bridge halted: civ_alert off, weather_burrow off, the burrows' releases and way_out_leave go through "
          "(only their undoing step); raising the alarm or moving dwarves in is refused")
    def _():
        BH.halted = True
        calls = BL.execute("""H = ...
          CALLS = {}
          H.df.global.plotinfo.alerts.civ_alert_idx = 1
          H.scripts['gui/civ-alert'] = {clear_alarm = function() H.df.global.plotinfo.alerts.civ_alert_idx = 0 end,
                                        can_sound_alarm = function() return true end, sound_alarm = function() end}
          H.scripts['ai-society'] = {
            note_ai_alarm = function(on) table.insert(CALLS, 'note ' .. tostring(on)) end,
            weather_keep_in = function(on) table.insert(CALLS, 'weather ' .. tostring(on)); return {ok = true} end,
            recreation_tick = function(_, _, _, _, _, _, rel) table.insert(CALLS, 'rec ' .. tostring(rel)); return {ok = true} end,
            hospital_burrow_tick = function(_, _, _, _, _, rel) table.insert(CALLS, 'hosp ' .. tostring(rel)); return {ok = true} end,
            calm_burrow_tick = function(_, _, _, _, rel) table.insert(CALLS, 'calm ' .. tostring(rel)); return {ok = true} end}
          H.scripts['ai-way-out'] = {leave = function() table.insert(CALLS, 'leave'); return {ok = true} end}
          return CALLS""", BH)

        def act(d):
            return BM.run_action(BL.table_from(d))
        r = act({"type": "civ_alert", "on": True})
        assert not r.ok and r.halted
        r = act({"type": "civ_alert", "on": False})
        assert r.ok and getattr(BH.df, "global").plotinfo.alerts.civ_alert_idx == 0, dict(r)
        for bad in ({"type": "weather_burrow", "on": True}, {"type": "recreation"}, {"type": "hospital_burrow"},
                    {"type": "calm_burrow"}):
            r = act(bad)
            assert not r.ok and r.halted, (bad, dict(r))
        for good in ({"type": "weather_burrow", "on": False}, {"type": "recreation", "release": True},
                     {"type": "hospital_burrow", "release": True}, {"type": "calm_burrow", "release": True},
                     {"type": "way_out_leave"}):
            r = act(good)
            assert r.ok, (good, dict(r))
        assert lst(calls) == ["note false", "weather false", "rec true", "hosp true", "calm true", "leave"], lst(calls)
        r = act({"type": "work_order", "recipe": "brew_drink", "amount": 5})
        assert not r.ok and r.halted                     # anything else: refused as before
        BH.halted = False

    @test("bridge: act_civ_alert books the AI's alarm when it raises it, not when the alarm was already on")
    def _():
        calls = BL.execute("""H = ...
          CALLS = {}
          H.df.global.plotinfo.alerts.civ_alert_idx = 0
          H.scripts['gui/civ-alert'] = {clear_alarm = function() H.df.global.plotinfo.alerts.civ_alert_idx = 0 end,
                                        can_sound_alarm = function() return true end,
                                        sound_alarm = function() H.df.global.plotinfo.alerts.civ_alert_idx = 1 end}
          H.scripts['ai-society'] = {note_ai_alarm = function(on) table.insert(CALLS, on) end,
                                     refresh_shelter_due = function() return {} end}
          return CALLS""", BH)
        r = BM.run_action(BL.table_from({"type": "civ_alert", "on": True}))
        assert r.ok and r.on and lst(calls) == [True], (dict(r), lst(calls))
        r = BM.run_action(BL.table_from({"type": "civ_alert", "on": True}))
        assert r.already_on and lst(calls) == [True]


# --- 6. train_cook: one kitchen ----------------------------------------------------------------

def welfare():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(_fake("test_r47_welfare.py", "FAKE"), module_src("ai-welfare.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


if LuaRuntime:
    @test("train_cook keeps ONE kitchen for the trainee; the others stay open to every cook; an older save's "
          "extra kitchens opened again; a player's kitchen untouched")
    def _():
        lua, env, w = welfare()
        w.citizen(T(lua, {"id": 3, "nm": "Urist", "cook": 1}))
        w.citizen(T(lua, {"id": 4, "nm": "Kib", "cook": 0}))
        k1, k2, k3 = w.kitchen(50), w.kitchen(51), w.kitchen(52, T(lua, [4]))
        r = env.train_cook(False, False)
        assert r.ok and r.unit_id == 3 and r.kitchen_id == 50 and r.open_kitchens == 1, dict(r)
        assert list(k1.profile.permitted_workers.values()) == [3]
        assert len(k2.profile.permitted_workers) == 0 and list(k3.profile.permitted_workers.values()) == [4]
        env.train_cook(False, False)                        # again: the same one kitchen
        assert list(k1.profile.permitted_workers.values()) == [3] and len(k2.profile.permitted_workers) == 0
        # a save from before: both kitchens the AI's, both locked to the cook
        lua.execute("local k = ...; k.profile.permitted_workers:insert('#', 3)", k2)
        w.site["ai-overseer/welfare"].cook.kitchens = T(lua, {"50": True, "51": True})
        r = env.train_cook(False, False)
        assert r.reopened == 1 and len(k2.profile.permitted_workers) == 0, dict(r)
        assert list(k1.profile.permitted_workers.values()) == [3]

    @test("train_cook: a trainee in a strange mood, waiting for treatment or kept in a burrow isn't free to cook "
          "(the report says so, the next best takes the kitchen)")
    def _():
        for setup in ("u.mood = 1", "u.health = {flags = {needs_healthcare = true, rq_surgery = true}}",
                      "u.burrows = {12}"):
            lua, env, w = welfare()
            w.citizen(T(lua, {"id": 3, "nm": "Urist", "cook": 1}))
            w.citizen(T(lua, {"id": 4, "nm": "Kib", "cook": 0}))
            k1 = w.kitchen(50)
            assert env.train_cook(False, False).unit_id == 3
            assert env.report().cook.free is True
            lua.execute("local u = ...; " + setup, w.byid[3])
            assert env.report().cook.free is False, setup
            assert env.train_cook(False, False).unit_id == 4, setup
            assert list(k1.profile.permitted_workers.values()) == [4]


if __name__ == "__main__":
    finish()
