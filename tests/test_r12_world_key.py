"""(r12) DF's World screen opened by its own interface key (D_WORLD) when the
World button's place was never shown (every fresh fort: live 22 Nov, all six
asked the player to show the World button before initial contact could go).

On test_mission_send's fake World screen, here D_WORLD opens it:
  * a run with no calibrated World button opens the screen by the key and goes
    on as a click would (the recorded Make contact steps);
  * the report lists World as known (so the planner proposes the send);
  * a key that doesn't open the screen stops the run at `open`, marks the key
    failed for the DF session, and the old needs_button ask returns;
  * a calibrated button is still clicked (the key unused);
  * no D_WORLD in this DF: needs_button, as before.

    python tests/test_r12_world_key.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

try:
    import lupa  # noqa: F401
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_mission_send as M  # noqa: E402  (its tests don't run on import)

# D_WORLD in df.interface_key; the fake's simulateInput opens the World screen on it
KEY = """
G.env.df.interface_key = {D_WORLD = 1}
local gui = G.env.require('gui')
local orig = gui.simulateInput
G.key_opens = (G.key_opens == nil) and true or G.key_opens
G.env.require = function(name)
  if name == 'gui' then
    return {simulateInput = function(v, key)
      if key == 'D_WORLD' then
        table.insert(G.inputs, key)
        if G.key_opens and not G.screen then G.screen_new() end
        return
      end
      return orig(v, key)
    end}
  end
  error('require ' .. name)
end
"""


def world(setup=""):
    env, G = M.world(setup)
    M.LUA.execute("local G, src = ...; assert(load(src, 'key', 't', setmetatable({G = G}, {__index = _G})))()",
                  G, KEY)
    return env, G


def inputs(G):
    return M.lst(G.inputs)


@test("no World button shown: the run opens the World screen by DF's key and goes on")
def _():
    env, G = world()
    r = M.start(env)
    assert r.ok and r.sending, dict(r)
    G.pump()
    assert "D_WORLD" in inputs(G), inputs(G)
    clicks = [tuple(M.lst(c)) for c in M.lst(G.clicks)]
    assert (3, 38) not in clicks, clicks                       # the World button never clicked blind
    assert inputs(G)[0] == "D_WORLD", inputs(G)
    last = env.status().last
    # past `open` and `site` (the fake has no readable text: Diplomacy's word
    # can't be read here, so the run stops at the goal step, as without the key)
    assert last.step == "goal" and last.reason == "needs_button" and "Diplomacy" in last.why, dict(last)
    assert env.WORLD_KEY_FAILED is False


@test("the report lists World as known by the key (the planner proposes the send)")
def _():
    env, G = world()
    assert "World" in M.lst(env.status().buttons), M.lst(env.status().buttons)


@test("a key that doesn't open the World screen: marked failed, no outcome booked (no year's block), the ask returns")
def _():
    env, G = world("G.key_opens = false")
    r = M.start(env)
    assert r.ok and r.sending, dict(r)
    G.pump()
    assert env.WORLD_KEY_FAILED is True
    assert env.status().last is None, dict(env.status().last)      # nothing for the planner to block on
    assert "World" not in M.lst(env.status().buttons)
    r = M.start(env)
    assert not r.ok and r.needs_button == "World", dict(r)


@test("a key that opens another panel: it is shut once, the key marked failed")
def _():
    env, G = world("G.key_opens = false; G.overlay = nil")
    M.LUA.execute("local G = ...; local sim = G.env.require('gui').simulateInput; "
                  "G.env.require = function(n) return {simulateInput = function(v, k) "
                  "if k == 'D_WORLD' then table.insert(G.inputs, k); G.overlay = 'dwarfmode/Squads' return end "
                  "if k == 'LEAVESCREEN' and G.overlay then table.insert(G.inputs, k); G.overlay = nil return end "
                  "return sim(v, k) end} end", G)
    assert M.start(env).ok
    G.pump()
    assert env.WORLD_KEY_FAILED is True and G.overlay is None, (env.WORLD_KEY_FAILED, G.overlay)
    assert "LEAVESCREEN" in inputs(G), inputs(G)


@test("a halt or the player taking over at open doesn't mark the key failed")
def _():
    env, G = world("G.key_opens = false")
    assert M.start(env).ok
    G.pump(1)                                   # the open step acts: the key pressed
    run = env.RUN
    assert run is not None and run.world_via_key is True, run
    env.stop(run, "stopped", "player_busy")
    G.pump()
    assert env.WORLD_KEY_FAILED is False


@test("a calibrated World button is still clicked; the key unused")
def _():
    env, G = world("G.calibrate_all()")
    assert M.start(env).ok
    G.pump()
    assert "D_WORLD" not in inputs(G), inputs(G)
    clicks = [tuple(M.lst(c)) for c in M.lst(G.clicks)]
    assert clicks[0] == (3, 38), clicks


@test("no D_WORLD in this DF: needs_button, as before")
def _():
    env, G = M.world()
    r = M.start(env)
    assert not r.ok and r.needs_button == "World", dict(r)
    assert "World" not in M.lst(env.status().buttons)


@test("a dry run presses nothing (no key)")
def _():
    env, G = world()
    r = M.start(env, dry_run=True)
    assert r.ok and r.dry_run and not inputs(G) and len(G.queue) == 0, dict(r)


# ---- (r12) the site's click: hovered first, clicked again, a miss retried tomorrow ----

@test("site: a first click DF ignores is followed by a second; the run goes on")
def _():
    env, G = world("G.calibrate_all()")
    M.LUA.execute("""local G = ...; local react = G.react; G.ignored = 0
      G.react = function(x, y)
        if G.screen and G.screen.view_mode == G.MODES.NORMAL and G.ignored == 0 then G.ignored = 1; return end
        return react(x, y)
      end""", G)
    assert M.start(env).ok
    G.pump()
    last = env.status().last
    assert last.step != "site", dict(last)           # past the site (stops later: Make contact not recorded here)


@test("site: DF never takes the click: 'click_missed' (tried tomorrow), a surprise after 3 a session")
def _():
    env, G = world("G.calibrate_all()")
    M.LUA.execute("""local G = ...; local react = G.react
      G.react = function(x, y)
        if G.screen and G.screen.view_mode == G.MODES.NORMAL then return end
        return react(x, y)
      end""", G)
    reasons = []
    for _ in range(4):
        assert M.start(env).ok
        G.pump()
        reasons.append(env.status().last.reason)
    assert reasons == ["click_missed"] * 3 + ["unexpected"], reasons


@test("planner: a missed click (and 0.105.68's record of it) retries the next day, no Needs you")
def _():
    sys.path.insert(0, str(ROOT / "brain"))
    import planner_missions as PM
    from planner_core import TICKS_PER_DAY, TICKS_PER_YEAR
    new = {"result": "stopped", "step": "site", "reason": "click_missed",
           "why": "still on world/NORMAL after the click (40 frames) (miss 1 this DF session)"}
    old = {"result": "stopped", "step": "site", "reason": "unexpected",
           "why": "still on world/NORMAL after the click (40 frames)"}
    third = dict(old, why="still on world/NORMAL after the click (40 frames) (miss 4 this DF session)")
    assert PM.click_missed(new) and PM.click_missed(old) and not PM.click_missed(third)
    assert PM.retry_ticks(new, TICKS_PER_YEAR) == TICKS_PER_DAY
    assert PM.retry_ticks(old, TICKS_PER_YEAR) == TICKS_PER_DAY
    assert PM.retry_ticks(third, TICKS_PER_YEAR) == TICKS_PER_YEAR


if __name__ == "__main__":
    finish()
