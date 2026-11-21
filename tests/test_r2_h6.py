"""(r2h6) Round 2, group h6: the causes of C's years of 40-50% unhappiness,
and the lost seeds (run2/R-CE.md finding 3 and its C section; audit A1 row 4b).

 1. ai-util fort_remains kept every body of the fort's civ, any race, as the
    fort's own dead: tame animals carry the fort's civ, so their bodies were
    never dumped (C: Miasma 117-126 citizens, SawDeadBody 94-126,
    miasma_clear "kept: own_dead 24 / 29"). Only a pet's body (DF buries
    pets) is kept now.
 2. The seed reserve: plump helmet seed 0-7 in every fort, A with 1,082
    plump helmets in store and 1 seed. A low crop's plant and seed are kept
    from the cooks (seed_reserve: DF's kitchen exclusions), a few brewed.
 3. Cups a tavern keeps were counted free: "37 citizens drank without a cup
    lately and 41 cups are free: make 1 stone mugs".
 4. Crisis mode held petition_answer: four guildhall petitions lapsed
    ("The guildhall petition by The Sienna Guild has been ignored", 07:36-
    07:44 16 Nov) and IgnoredGuildhallPetition (16-65 citizens) topped the
    stress from that hour; it never showed before. Answers now always go; in
    a crisis a petition that needs a new hall is declined.

    python tests/test_r2_h6.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_farms as PF  # noqa: E402
import planner_society as PS  # noqa: E402
import planner_locations as PL  # noqa: E402
import crisis  # noqa: E402
import hold_classes as HC  # noqa: E402

CFG = PLANNER_CONFIG
LUA = ROOT / "lua"
UTIL = (LUA / "ai-util.lua").read_text(encoding="utf-8")
SYND = (LUA / "ai-syndromes.lua").read_text(encoding="utf-8")
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))

# ---- 1. the dead animals' bodies --------------------------------------------------

# the fort's race 1, civ 7, group 70; unit 30 a duckling (race 50) of the fort's
# civ, unit 31 a cat that is a dwarf's pet (PetOwner set), unit 11 a citizen
UTIL_FAKE = r"""
local util_src, units, hfs = ...
local env = setmetatable({}, {__index = _G})
local LINK = {[0] = 'MEMBER', [1] = 'FORMER_MEMBER'}
env.df = {global = {plotinfo = {race_id = 1, civ_id = 7, group_id = 70},
                    world = {items = {other = {CORPSE = {}, CORPSEPIECE = {}}}}},
          item_type = setmetatable({}, {__index = function(_, k) return k end}),
          histfig_entity_link_type = LINK,
          unit_relationship_type = {PetOwner = 1},
          unit = {find = function(id) return units[id] end},
          historical_figure = {find = function(id)
              local h = hfs[id]
              if not h then return nil end
              local links = {}
              for i, l in ipairs(h) do links[i] = {entity_id = l[1], getType = function() return l[2] end} end
              return {entity_links = links}
          end}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end},
              items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
                       getOwner = function(it) return nil end},
              units = {isDead = function(u) return true end}}
assert(load(util_src, 'ai-util', 't', env))()
function env.item(kind, race, unit_id)
    return {kind = kind, race = race, unit_id = unit_id, hist_figure_id = -1,
            pos = {x = 125, y = 153, z = 169}, flags = {forbid = true, on_ground = true},
            getType = function(self) return self.kind end}
end
return env
"""


def util_env():
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(d):
        if isinstance(d, dict):
            return lua.table_from({k: lt(v) for k, v in d.items()})
        if isinstance(d, (list, tuple)):
            return lua.table_from([lt(v) for v in d])
        return d
    units = {
        11: {"civ_id": 7, "hist_figure_id": 111, "flags1": {}, "flags2": {}, "relationship_ids": {1: -1}},
        30: {"civ_id": 7, "hist_figure_id": -1, "flags1": {}, "flags2": {}, "relationship_ids": {1: -1}},
        31: {"civ_id": 7, "hist_figure_id": -1, "flags1": {}, "flags2": {}, "relationship_ids": {1: 11}},
        32: {"civ_id": 7, "hist_figure_id": -1, "flags1": {}, "flags2": {}},      # nothing to read: no pet
        40: {"civ_id": 9, "hist_figure_id": -1, "flags1": {}, "flags2": {}, "relationship_ids": {1: -1}},
    }
    hfs = {111: [[70, 0]]}
    env = lua.execute(UTIL_FAKE, UTIL, lt(units), lt(hfs))
    return lua, env


@test("1. fort_remains: a tame duckling's body (the fort's civ, another race) is no longer the fort's own (was: kept to rot)")
def _():
    need_lua()
    lua, env = util_env()
    ctx = env.forbid_context()
    duck = env.item("CORPSE", 50, 30)
    assert not env.fort_remains(duck, "CORPSE", ctx)
    assert not env.fort_remains(env.item("CORPSEPIECE", 50, 30), "CORPSEPIECE", ctx)   # a butchered duck's hide
    assert not env.fort_remains(env.item("CORPSE", 50, 32), "CORPSE", ctx)
    assert tuple(env.forbidden_reason(duck, ctx)) == ("other_dead", "other")
    # a wild animal's (another civ) as before
    assert not env.fort_remains(env.item("CORPSE", 50, 40), "CORPSE", ctx)


@test("1. fort_remains: a pet's body waits for its tomb (DF buries pets); citizens, unread race and DF's flag still kept")
def _():
    need_lua()
    lua, env = util_env()
    ctx = env.forbid_context()
    assert env.corpse_was_pet(env.item("CORPSE", 51, 31)) is True
    assert env.corpse_was_pet(env.item("CORPSE", 50, 30)) is False
    assert env.fort_remains(env.item("CORPSE", 51, 31), "CORPSE", ctx)         # a dwarf's cat
    assert env.fort_remains(env.item("CORPSE", 1, 11), "CORPSE", ctx)          # a citizen
    assert env.fort_remains(env.item("CORPSE", 2, 11), "CORPSE", ctx)          # another race, a member
    assert env.fort_remains(env.item("CORPSE", None, 30), "CORPSE", ctx)       # race unread: kept
    flagged = env.item("CORPSE", 50, 30)
    flagged.flags.dead_dwarf = True
    assert env.fort_remains(flagged, "CORPSE", ctx)


@test("1. the miasma clearing and the dump ask fort_remains: a tame animal's body is now theirs to move")
def _():
    assert "if U.fort_remains(it, e.kind, ctx) then return 'own_dead' end" in SYND
    assert "and corpse_was_pet(it)" in UTIL


# ---- 2. the seed reserve ------------------------------------------------------------

def farm_fort(crops, held=None, orders=None) -> dict:
    s = copy.deepcopy(BASE)
    s["farms"] = {"plots": 12, "plots_underground": 6, "plots_dead": 3, "crops": crops,
                  "season": "summer", "plot_list": []}
    if held is not None:
        s["farms"]["seed_bans"] = held
    s["orders"] = orders or []
    return s


# fort A's last state (audit evidence A/state-last.json): its underground crops
A_CROPS = {
    "MUSHROOM_HELMET_PLUMP": {"name": "plump helmet", "seeds": 1, "stock": 1082, "planted": 6, "brews": "plant",
                              "seed": True, "underground": True, "seasons": ["spring", "summer", "autumn", "winter"]},
    "GRASS_TAIL_PIG": {"name": "pig tail", "seeds": 3, "stock": 188, "planted": 0, "brews": "plant", "seed": True,
                       "underground": True, "seasons": ["spring", "summer", "autumn", "winter"]},
    "BUSH_QUARRY": {"name": "quarry bush", "seeds": 1, "stock": 33, "planted": 0, "seed": True,
                    "underground": True, "seasons": ["spring", "summer", "autumn", "winter"]},
    "BLACKBERRY": {"name": "blackberry bush", "seeds": 288, "stock": 562, "planted": 1, "brews": "growth",
                   "seed": True, "underground": False, "seasons": ["spring", "summer", "autumn", "winter"]},
    "ASPARAGUS": {"name": "asparagus", "seeds": 13, "stock": 0, "planted": 0, "seed": True,
                  "underground": False, "seasons": ["spring", "summer", "autumn", "winter"]},
}


def seed_rule(s, memory=None):
    props, notes = [], []
    PF._seed_reserve_rule(s, memory or Memory(), CFG, props, notes)
    return props, notes


@test("2. fort A (1 plump helmet seed, 1,082 in store): plump helmet and its seed kept from the cooks, 10 brewed")
def _():
    props, _ = seed_rule(farm_fort(A_CROPS, held=[]))
    sr = [p for p in props if p.rule == "seed_reserve"]
    assert len(sr) == 1, props
    a = sr[0].action
    assert a["type"] == "seed_reserve" and a["ban"][0] == "MUSHROOM_HELMET_PLUMP", a
    assert set(a["ban"]) == {"MUSHROOM_HELMET_PLUMP", "GRASS_TAIL_PIG", "BUSH_QUARRY"}, a   # not unsown surface crops
    assert a["target"] == CFG["h6_seed_reserve"] and "lift" not in a
    assert sr[0].priority == 3
    br = [p for p in props if p.rule == "seed_brew"]
    assert br and br[0].action == {"type": "work_order", "recipe": "brew_drink", "amount": 10}, br
    assert HC.RULE_CLASS["seed_reserve"] == HC.SURVIVAL and HC.RULE_CLASS["seed_brew"] == HC.SURVIVAL


@test("2. the plan itself asks for the seed reserve (the rule is wired in)")
def _():
    props, _ = plan(farm_fort(A_CROPS, held={}), Memory())
    assert any(p.rule == "seed_reserve" and "MUSHROOM_HELMET_PLUMP" in p.action.get("ban", []) for p in props), \
        [p.rule for p in props]


@test("2. held bans aren't asked again; lifted once the seed is back; no brew while one is queued; old bridge: silent")
def _():
    crops = copy.deepcopy(A_CROPS)
    props, _ = seed_rule(farm_fort(crops, held=["MUSHROOM_HELMET_PLUMP", "GRASS_TAIL_PIG", "BUSH_QUARRY"],
                                   orders=[{"id": 1, "recipe": "brew_drink", "amount_left": 5, "by_ai": True}]))
    assert not props, props
    crops["MUSHROOM_HELMET_PLUMP"]["seeds"] = CFG["h6_seed_lift"]
    props, _ = seed_rule(farm_fort(crops, held=["MUSHROOM_HELMET_PLUMP"]))
    sr = [p for p in props if p.rule == "seed_reserve"]
    assert sr and sr[0].action.get("lift") == ["MUSHROOM_HELMET_PLUMP"], sr
    assert not seed_rule(farm_fort(A_CROPS))[0]          # no seed_bans in the report


HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)


@test("2. bridge seed_reserve: the plant and its seed excluded from cooking, recorded, lifted; seedwatch kept in line")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(HARNESS, (LUA / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA))
    env = H.module()
    r = lua.execute("""local env, H = ...
      local calls, cmds = {}, {}
      H.dfhack.kitchen = {addExclusion = function(j, t, s, mt, mi)
                              table.insert(calls, (j.Cook and 'cook+' or '?+') .. t .. ':' .. mt .. ':' .. mi); return true end,
                          removeExclusion = function(j, t, s, mt, mi)
                              table.insert(calls, (j.Cook and 'cook-' or '?-') .. t .. ':' .. mt .. ':' .. mi); return true end}
      H.df.item_type = {PLANT = 53, SEEDS = 52}
      H.df.global.world.raws.plants = {all = {
          {id = 'MUSHROOM_HELMET_PLUMP', material = {{id = 'STRUCTURAL'}},
           material_defs = {type = {seed = 420}, idx = {seed = 21}}}}}
      H.dfhack.matinfo.find = function(p, m) return {type = 419, index = 21} end
      H.dfhack.run_command_silent = function(...) table.insert(cmds, table.concat({...}, ' ')); return '', 0 end
      env.plugin_enabled = function(name) return name == 'seedwatch' end
      local b = env.act_seed_reserve({ban = {'MUSHROOM_HELMET_PLUMP', 'NO_SUCH'}, target = 30})
      local again = env.act_seed_reserve({ban = {'MUSHROOM_HELMET_PLUMP'}})
      local held = env.seed_bans_held()
      local l = env.act_seed_reserve({lift = {'MUSHROOM_HELMET_PLUMP'}})
      local none = env.act_seed_reserve({})
      return b.ok, #b.banned, b.seedwatch, again.ok, held[1], l.ok, #l.lifted, none.ok,
             table.concat(calls, ','), table.concat(cmds, ',')
    """, env, H)
    r = tuple(r)
    assert r[:8] == (True, 1, 1, False, "MUSHROOM_HELMET_PLUMP", True, 1, False), r
    assert r[8] == "cook+53:419:21,cook+52:420:21,cook-53:419:21,cook-52:420:21", r[8]
    assert r[9] == "seedwatch MUSHROOM_HELMET_PLUMP 30", r[9]


@test("2. the farms report gives the held seed bans (seed_bans)")
def _():
    farms = (LUA / "ai-builder-farms.lua").read_text(encoding="utf-8")
    assert "out.seed_bans = okb and held or nil" in farms and "'ai-overseer/kitchen-seeds'" in farms
    bridge = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "seed_reserve = act_seed_reserve" in bridge and "'seed_reserve'" in bridge


# ---- 3. cups -------------------------------------------------------------------------

def cup_fort(free=41, location=41, cupless=37, citizens=126) -> dict:
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = citizens
    s["needs"] = {"clothing": {"citizens": citizens, "without": {"shoes": 0}, "free_shoes": 50, "free_cups": free,
                               "free_cups_detail": {"n": free, "why": {"location": location},
                                                    "why_locations": {"INN_TAVERN": location}, "place": {}}},
                  "stress_causes": {"days": 28, "causes": [{"thought": "DrinkWithoutCup", "citizens": cupless}]}}
    s["orders"] = []
    return s


@test("3. C's 41 'free' cups were the tavern's: 20 stone mugs made (was: 1)")
def _():
    props, notes = [], []
    PS._comfort_rules(cup_fort(), CFG, props, notes)
    mugs = [p for p in props if p.action.get("recipe") in ("stone_mugs", "wooden_cups")]
    assert mugs and mugs[0].action["amount"] == CFG["cups_batch"], [(p.action, p.reason) for p in props]
    assert "41 more are a tavern's" in mugs[0].reason, mugs[0].reason
    # cups free off the tavern: as before
    props = []
    PS._comfort_rules(cup_fort(free=45, location=0), CFG, props, [])
    assert not [p for p in props if p.action.get("recipe") in ("stone_mugs", "wooden_cups")]


# ---- 4. the guildhall petitions ----------------------------------------------------

GUILDS_C = [{"id": 10, "type": "GUILDHALL", "profession": "FARMER", "tier": 1, "value": 4000},
            {"id": 11, "type": "GUILDHALL", "profession": "CRAFTSMAN", "tier": 1, "value": 3000}]


def petition_fort(pending) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {"craftsmanship": 40, "industriousness": 20, "welfare": 20}
    s["petitions"] = {"pending": pending, "agreed": []}
    s["locations"] = {"count": {"GUILDHALL": 2}, "list": GUILDS_C}
    s["projects"] = {"open": [], "max_open": 4}
    s["date"]["year"] = 255
    return s


def pet(pid, prof, days=0):
    return {"id": pid, "type": "Location", "loc": "GUILDHALL", "profession": prof, "tier": 1, "days": days,
            "applicant": {"entities": 1}}


def answers(s, memory):
    props, notes = [], []
    PL._location_petition_rules(s, CFG, props, notes, {"answer_locations": True, "levels": {}}, memory)
    return [p for p in props if p.rule == "petition_answer"]


@test("4. in a crisis the petition is still answered (was: held, lapsed, the guild upset): agreed where the hall stands")
def _():
    m = Memory()
    m.crisis = {"since": 1, "why": ["41% unhappy"]}
    got = answers(petition_fort([pet(2581, "FARMER")]), m)
    assert got and got[0].action["accept"] is True, got
    notes: list = []
    out = crisis.apply(list(got), ["41% unhappy"], notes)
    assert out == got, notes                          # not held
    assert HC.RULE_CLASS["petition_answer"] == HC.SURVIVAL and HC.RULE_CLASS["petition_build"] == HC.EXPANSION


@test("4. in a crisis (or a recovery) a petition that needs a new hall is declined, not promised; out of one, agreed")
def _():
    for k in ("crisis", "recovery"):
        m = Memory()
        setattr(m, k, {"since": 1, "why": ["x"]})
        got = answers(petition_fort([pet(2673, "MINER")]), m)
        assert got and got[0].action["accept"] is False and "crisis" in got[0].reason, (k, got)
    got = answers(petition_fort([pet(2673, "MINER")]), Memory())
    assert got and got[0].action["accept"] is True, got


if __name__ == "__main__":
    finish()
