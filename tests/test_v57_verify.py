"""(v57 verify) Independent proofs against the round-2 merge (0.105.57 RC).

Each test here demonstrates a defect found in review and FAILS on the code
as merged (141739b). They are proofs, not fixes: a test passes once its bug
is fixed. See /home/claude/verify-v57.md for the findings (W1...).

    python tests/test_v57_verify.py
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402

import digest  # noqa: E402
import planner_slots as SL  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG, abs_tick, TICKS_PER_DAY  # noqa: E402
import json  # noqa: E402

LUA = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


class H3:
    """test_r2_h3's fort and furnishing level (copied: that file runs its tests on import)."""

    @staticmethod
    def fort() -> dict:
        s = copy.deepcopy(BASE)
        s["date"] = {"year": 259, "tick": 259313, "season": "autumn", "month": "Sandstone", "day": 21}
        s["orders"] = []
        return s

    @staticmethod
    def furnish_level(id_, kind, waiting, days, **kw):
        sig = ",".join(sorted(f"{k}:{n}" for k, n in waiting.items()))
        p = {"id": id_, "kind": kind, "phase": "furnish", "started": {"year": 252, "tick": 51324},
             "furnish": {"placed": 3, "done": 1, "waiting": dict(waiting), "days": days, "sig": sig}}
        p.update(kw)
        return p


# --- W1: h3's dig check cancels a landmark level h8 keeps for 336 days ---------------------------

@test("W1 _dig_check_rule: a landmark's lower level (0 dug, reached only once the level above is dug) "
      "is not given up at 21 days (h8 keeps it h8_landmark_dig_days)")
def _():
    s = H3.fort()
    lvl = {"id": 44, "kind": "landmark", "phase": "dig", "params": {"landmark_id": 3},
           "started": {"year": 259, "tick": 100},
           "dig": {"digging": 0, "dug": 0, "marked": 0, "stuck": 0, "total": 180,
                   "waiting": ["x60 y80 z120: Dig, no worker (priority 4), beside ground the dwarves can't reach"]}}
    s["projects"] = {"open": [lvl]}
    m = Memory()
    m.dig_seen = {"44": {"dug": 0, "tick": abs_tick(s) - (CFG["h3_dig_check_days"] + 2) * TICKS_PER_DAY}}
    props, notes = [], []
    SL._dig_check_rule(digest.normalize(s), m, CFG, props, notes)
    cancels = [p.action for p in props if p.action.get("type") == "cancel_project"]
    assert CFG["h8_landmark_dig_days"] > CFG["h3_dig_check_days"]
    assert not cancels, (f"a landmark level was given up {CFG['h3_dig_check_days'] + 2} days in "
                         f"(h8 keeps it {CFG['h8_landmark_dig_days']}): {cancels}")


# --- W2: the seed reserve's ban is lifted by kitchen_brewables -------------------------------------

HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)


@test("W2 seed_reserve: a plump helmet the brewables ban already kept from the cooks stays kept "
      "when kitchen_brewables lifts its own ban (drink recovered, seeds still low)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(HARNESS, (LUA / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA))
    env = H.module()
    r = lua.execute("""local env, H = ...
      local ex = {}       -- DF's kitchen exclusion list (Cook): one entry per key
      local function k(t, mt, mi) return t .. ':' .. mt .. ':' .. mi end
      H.dfhack.kitchen = {
        addExclusion = function(j, t, s, mt, mi)
          if ex[k(t, mt, mi)] then return false end; ex[k(t, mt, mi)] = true; return true end,
        removeExclusion = function(j, t, s, mt, mi)
          if not ex[k(t, mt, mi)] then return false end; ex[k(t, mt, mi)] = nil; return true end}
      H.df.item_type = {PLANT = 53, SEEDS = 52}
      H.df.global.world.raws.plants = {all = {
          {id = 'MUSHROOM_HELMET_PLUMP', material = {{id = 'STRUCTURAL'}},
           material_defs = {type = {seed = 420}, idx = {seed = 21}}}}}
      H.dfhack.matinfo.find = function(p, m) return {type = 419, index = 21} end
      H.dfhack.run_command_silent = function(...) return '', 0 end
      env.plugin_enabled = function() return false end
      -- drink short: the brewable plump helmet kept from the cooks (0.105.33)
      env.brewable_cook_keys = function() return {{t = 53, s = -1, mt = 419, mi = 21}} end
      local b1 = env.act_kitchen_brewables({ban = true})
      -- seeds low: the seed reserve bans the plant and its seed (r2h6)
      local sr = env.act_seed_reserve({ban = {'MUSHROOM_HELMET_PLUMP'}, target = 30})
      -- drink recovers: the brewables ban lifted (the seeds are still low)
      local b2 = env.act_kitchen_brewables({ban = false})
      return sr.ok, ex['53:419:21'] == true, table.concat(env.seed_bans_held(), ',')
    """, env, H)
    ok, still_banned, held = tuple(r)
    assert ok and held == "MUSHROOM_HELMET_PLUMP"
    assert still_banned, ("the AI says it holds the plump helmet's seed ban, but the kitchen cooks the plant "
                          "again: kitchen_brewables lifted the exclusion the seed reserve counted on")


# --- W3: a parked level's pieces outside a fixed list dropped at once ------------------------------

@test("W3 _park_rule: an archery range's targets (built from any boulder or log) are not taken off "
      "the day the level is parked as 'nothing in the fort makes ArcheryTarget'")
def _():
    s = H3.fort()
    lvl = H3.furnish_level(31, "archery", {"ArcheryTarget": 2}, 31, parked=True, parked_days=1)
    s["projects"] = {"open": [lvl]}
    m = Memory()
    m.furnish_seen = {"31": {"sig": lvl["furnish"]["sig"], "tick": abs_tick(s) - 31 * TICKS_PER_DAY}}
    props, notes = [], []
    SL._park_rule(digest.normalize(s), m, CFG, props, notes)
    drops = [p.action for p in props if p.action.get("type") == "finish_project"]
    assert not drops, (f"the archery range's targets were dropped 1 day after it was parked "
                       f"(h3_park_drop_days is {CFG['h3_park_drop_days']}): {drops}")


# --- W4: the crossbow squad's lone Bowyer's holds an ordinary slot once it is open -----------------

BUILDER_HARNESS = re.search(r'HARNESS = r"""(.*?)"""', (ROOT / "tests" / "test_builder.py").read_text(encoding="utf-8"),
                            re.S).group(1)


@test("W4 slot_cap: the lone `crossbows` Bowyer's level 'takes no slot' after it starts too "
      "(an ordinary level still fits beside MAX_OPEN_PROJECTS - 1 others)")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().LUA_DIR = str(LUA)
    B, W = lua.execute(BUILDER_HARNESS, (LUA / "ai-layouts.lua").read_text(encoding="utf-8"),
                       (LUA / "ai-builder.lua").read_text(encoding="utf-8"))
    n = int(B.MAX_OPEN_PROJECTS) - 1
    levels = lua.eval("function(n) local t = {} for i = 1, n do t[i] = {id = i, kind = 'bedrooms', phase = 'dig'} end "
                      "t[n + 1] = {id = 99, kind = 'workshops', phase = 'dig', crossbows = true, "
                      "params = {shops = {'Bowyers'}, crossbows = true}} return t end")(n)
    B.open_projects = lambda data: levels
    t = lua.table()
    t.kind, t.rooms, t.room_size = "bedrooms", 4, 3
    r = B.start_project(t, lua.table(), True)
    assert "unfinished building projects" not in str(r.error), (
        f"slot_cap {B.slot_cap(levels)} with {n} ordinary levels and the Bowyer's open: the Bowyer's holds "
        f"an ordinary slot once started ({dict(r)})")


# --- W5: the stuck sweep closes a level h3 parked ----------------------------------------------------

@test("W5 _stuck_rule: a level the slot rules parked (waiting apart for its bed and box, h3_park_drop_days "
      "not reached) is not closed by the stuck sweep at stuck_sweep_project_days")
def _():
    import planner_stuck as ST
    s = H3.fort()
    now = abs_tick(s)
    lvl = H3.furnish_level(66, "bedrooms", {"Bed": 1, "Box": 1}, 120, parked=True, parked_days=90)
    s["projects"] = {"open": [lvl]}
    t0 = now - 120 * TICKS_PER_DAY
    s["stuck"] = {"list": [{"kind": "project", "id": 66, "what": "bedrooms", "state": "furnish",
                            "progress": "1/3", "since": t0, "moved": t0}]}
    m = Memory()
    props, notes = [], []
    ST._stuck_rule(digest.normalize(s), m, CFG, props, notes)
    shut = [p.action for p in props if p.action.get("project_id") == 66]
    assert CFG["h3_park_drop_days"] > 120
    assert not shut, (f"the stuck sweep gives up a parked level at {CFG['stuck_sweep_project_days']} days "
                      f"(h3 keeps it waiting {CFG['h3_park_drop_days']}): {shut}")


if __name__ == "__main__":
    finish()
