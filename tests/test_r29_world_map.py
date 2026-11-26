"""(R29, Phase 13b) The World screen past the site's click, on test_r47's
fake World screen (the 14 Nov recording): DF's "The World" help window
hidden and closed; the site's click repeated with the site written in the
click's own frame; New mission's words read again until DF has drawn them;
each step's result kept for the journal; a World screen Esc won't shut
dismissed; other entities' new controllers not counted as left behind.

Live (25 Nov, 0.105.121, mission-send.json of all six forts): B-F stopped at
the site ("still on world/NORMAL after the click", miss 4-6 a session); A, C,
E and D reached New mission and stopped at the goal, "none of Diplomacy /
Attack is on New mission": the rows read in that same frame held the fort's
view, or DF's help window "The World ... Don't show again ... Okay" over the
buttons (POPUP_WORLD never seen in A, B, C, E, F); D and F left "closed":
false.

    python tests/test_r29_world_map.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-mission-send.lua")
# test_r47's fake World screen (the recorded states), shared, not copied
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_r47_mission_send.py").read_text(encoding="utf-8"),
                 re.S).group(1)

# DF's help window and the save's tutorial lists, as df-structures 53.x has them
HELP = r"""
local function ivec(list)
  local v = G.vec(list)
  v.insert = function(self, pos, x) self[self._n] = x; self._n = self._n + 1 end
  return v
end
local H = {POPUP_WORLD = 20, [20] = 'POPUP_WORLD', POPUP_SQUADS = 19, [19] = 'POPUP_SQUADS',
           WORLD_GEN_MESSAGE = 0, [0] = 'WORLD_GEN_MESSAGE'}
G.env.df.help_context_type = H
G.env.df.global.plotinfo.tutorial_seen = ivec(G.seen0 or {})
G.env.df.global.plotinfo.tutorial_hide = ivec({})
G.help = {open = false, context = 0}
G.env.df.global.game = {main_interface = {help = G.help}}
local ow = G.open_world
G.open_world = function()
  ow()
  -- DF opens its help window the first time unless the save has it seen
  local seen = false
  local v = G.env.df.global.plotinfo.tutorial_seen
  for i = 0, #v - 1 do if v[i] == 20 then seen = true end end
  if not seen or G.popup_anyway then G.help.open = true; G.help.context = 20 end
end
-- the help window over the World screen takes the clicks and hides New mission's buttons
local react, labels = G.react, G.labels
G.react = function(x, y)
  if G.screen and G.help.open then G.popup_clicks = (G.popup_clicks or 0) + 1; return end
  return react(x, y)
end
G.labels = function()
  if G.screen and G.help.open then return {{61, 7, 'The World'}, {79, 21, "Don't show again"}, {87, 26, 'Okay'}} end
  return labels()
end
"""


def world(setup: str = ""):
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, G = lua.execute(FAKE, SRC, HELP + setup)
    return lua, env, G


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def send(lua, env, G, **kw):
    a = {"site_id": 59, "goal": "make_contact"}
    a.update(kw)
    if "squad_ids" in a:
        a["squad_ids"] = lua.table_from(a["squad_ids"])
    r = env.start(lua.table_from(a))
    G.pump()
    return r, env.status().last


def results(last):
    return [(x.step, x.result) for x in lst(last.results)]


@test("DF's help window 'The World': marked seen and hidden in the save before the World screen opens "
      "(DFHack's hide-tutorials); Make contact then goes end to end")
def _():
    lua, env, G = world()
    r, last = send(lua, env, G)
    assert r.ok and last.result == "sent", dict(last)
    pi = getattr(env.df, "global").plotinfo
    assert pi.tutorial_seen._n == 1 and pi.tutorial_seen[0] == 20 and pi.tutorial_hide[0] == 20
    assert last.popup == "hidden" and not G.popup_clicks, (last.popup, G.popup_clicks)


@test("the help window shows anyway: closed (help.open false) before the site's click; the run goes on")
def _():
    lua, env, G = world("G.popup_anyway = true")
    r, last = send(lua, env, G)
    assert last.result == "sent", dict(last)
    assert last.popup_closed == "POPUP_WORLD" and G.help.open is False and not G.popup_clicks


@test("each step's result kept with the outcome (journal): open, site, goal, make_contact, messenger, confirm ok")
def _():
    lua, env, G = world()
    r, last = send(lua, env, G)
    assert results(last) == [(s, "ok") for s in ("open", "site", "goal", "make_contact", "messenger",
                                                 "confirm")], results(last)
    assert lst(last.results)[1].clicks == 1, dict(lst(last.results)[1])


@test("New mission's words not drawn yet (the fort's view still in the rows): read again until they show, "
      "Diplomacy then pressed; the goal step says how many reads")
def _():
    lua, env, G = world("""
local labels = G.labels; G.reads = 0
G.labels = function()
  if G.screen and G.MODES[G.screen.view_mode] == 'NEW_MISSION' and G.reads < 150 * 66 * 3 then
    G.reads = G.reads + 1
    return {{18, 0, 'Niledan'}, {23, 46, 'AI Overseer'}}
  end
  return labels()
end""")
    r, last = send(lua, env, G)
    assert last.result == "sent", dict(last)
    goal = [x for x in lst(last.results) if x.step == "goal"][0]
    assert goal.result == "ok" and goal.tries >= 3, dict(goal)


@test("New mission's words never show: stopped at the goal after READ_WAIT_FRAMES, the screen kept, how many reads said")
def _():
    lua, env, G = world("""
local labels = G.labels
G.labels = function()
  if G.screen and G.MODES[G.screen.view_mode] == 'NEW_MISSION' then return {{23, 46, 'AI Overseer'}} end
  return labels()
end""")
    r, last = send(lua, env, G)
    assert last.step == "goal" and last.reason == "goal_unread" and "read " in last.why, dict(last)
    assert results(last)[-1][0] == "goal" and results(last)[-1][1].startswith("stop: "), results(last)
    assert G.screen is None and last.closed is True


@test("the site's click: DF ignores two, takes the third (each with the site written in the click's frame)")
def _():
    lua, env, G = world("""
local react = G.react; G.ignored = 0
G.react = function(x, y)
  if G.screen and G.screen.view_mode == G.MODES.NORMAL and G.ignored < 2 then G.ignored = G.ignored + 1; return end
  return react(x, y)
end""")
    r, last = send(lua, env, G)
    assert last.result == "sent", dict(last)
    site = [x for x in lst(last.results) if x.step == "site"][0]
    assert site.result == "ok" and site.clicks == 3, dict(site)


@test("the site's click never taken: SITE_CLICKS clicks, then 'click_missed' with the count in why; the screen shut")
def _():
    lua, env, G = world("""
local react = G.react
G.react = function(x, y)
  if G.screen and G.screen.view_mode == G.MODES.NORMAL then return end
  return react(x, y)
end""")
    r, last = send(lua, env, G)
    assert last.step == "site" and last.reason == "click_missed", dict(last)
    assert ("after %d click(s)" % env.SITE_CLICKS) in last.why, last.why
    assert G.screen is None


@test("a World screen Esc won't shut: Esc CLOSE_TRIES times, each given frames to go, then DFHack's dismiss")
def _():
    lua, env, G = world("""
G.env.dfhack.screen.dismiss = function(scr) G.dismissed = true; G.screen = nil end
G.no_esc = true
local req = G.env.require
G.env.require = function(name)
  local m = req(name)
  if name == 'gui' then
    local sim = m.simulateInput
    return {simulateInput = function(s, key)
      if key == 'LEAVESCREEN' and G.no_esc then table.insert(G.inputs, key); return end
      return sim(s, key)
    end}
  end
  return m
end
G.allowed = {DIPLOMACY = 'INACCESSIBLE'}""")
    r, last = send(lua, env, G)
    assert last.reason == "inaccessible", dict(last)
    assert lst(G.inputs).count("LEAVESCREEN") == env.CLOSE_TRIES, lst(G.inputs)
    assert G.dismissed and last.dismissed is True and last.closed is True, dict(last)


@test("another entity's army controller appearing during the run is not 'left behind'")
def _():
    lua, env, G = world("""
local react = G.react
G.react = function(x, y)
  if G.screen and G.screen.view_mode == G.MODES.NORMAL then
    G.push(G.controllers, {id = 99001, goal = G.GOALS.CAMP, entity_id = 3160, site_id = -1,
                           assigned_squads = G.vec(), assigned_epp_epp_id = G.vec(), data = {}})
  end
  return react(x, y)
end""")
    r, last = send(lua, env, G)
    assert last.result == "sent" and last.controller_left is None and last.left_ids is None, dict(last)


if __name__ == "__main__":
    finish()
