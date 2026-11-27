"""(0.105.119 item37) Good meals of meat, cheese and flour.

- meal_cheap: with the meals at their target and good meals few while the
  dwarves want them, the cooks leave the cheap ingredients (plants, growths,
  eggs, fish worth under MEAL_CHEAP_VALUE a unit) alone (kitchen_cheap);
  lifted when the meals fall under half the target or good meals are enough.
- kitchen_cheap (the bridge): bans each cheap kind in stock while enough of
  the worthier ones are left, lets go of its ban when they run out (Lua part:
  needs lupa, run on the PC).

    python tests/test_item37_meals.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import PLANNER_CONFIG, Memory, plan, record  # noqa: E402
import planner_farms  # noqa: E402
import overseer_words  # noqa: E402
from planner_core_base import COOLDOWN_KEYS  # noqa: E402
from hold_classes import _SURVIVAL_RULES, _SURVIVAL_ACTIONS  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG


def fort(wanting: bool = True) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["buildings"].setdefault("workshops", {})["Kitchen"] = 1
    pop = int(s["dwarves"]["total"])
    s["stocks"].update(prepared_meals=pop * CFG["meals_per_dwarf"], drink=500)
    if wanting:      # C, 25 Nov 18:31: 19 want a good meal, 47 of 2,189 servings worth over 20
        s.setdefault("needs", {}).setdefault("needs", {})["EatGoodMeal"] = {"distracted": 20, "badly": 5}
        s.setdefault("supplies", {})["good_meals"] = 0
    return s


def rule(s, m):
    props: list = []
    planner_farms._meal_cheap_rule(s, m, CFG, props)
    return props


@test("meal_cheap: meals at their target, good meals few and wanted: the cheap ingredients kept from the cooks")
def _():
    s = fort()
    pop = int(s["dwarves"]["total"])
    p = rule(s, Memory())
    assert p and p[0].rule == "meal_cheap", p
    a = p[0].action
    assert a["type"] == "kitchen_cheap" and a["ban"] is True and a["min_value"] == planner_farms.MEAL_CHEAP_VALUE, a
    assert a["keep"] == max(20, int(pop * planner_farms.MEAL_CHEAP_KEEP_PD)), a
    assert p[0].priority >= 8 and "meat, cheese" in p[0].reason, p
    # nobody wanting, good meals enough, an older report, meals short: nothing asked
    q = copy.deepcopy(s); q["needs"]["needs"]["EatGoodMeal"]["distracted"] = 0
    assert not rule(q, Memory())
    q = copy.deepcopy(s); q["supplies"]["good_meals"] = CFG["good_meals_pd"] * pop
    assert not rule(q, Memory())
    q = copy.deepcopy(s); q["supplies"].pop("good_meals")
    assert not rule(q, Memory())
    q = copy.deepcopy(s); q["stocks"]["prepared_meals"] = pop * CFG["meals_per_dwarf"] - 1
    assert not rule(q, Memory())
    assert not rule(s, None)
    q = copy.deepcopy(s); q["buildings"]["workshops"].pop("Kitchen")
    assert not rule(q, Memory())
    # in the whole plan too (a glut of plain meals is no reason not to)
    q = copy.deepcopy(s); q["stocks"]["prepared_meals"] = pop * 17
    assert any(x.rule == "meal_cheap" for x in plan(q, Memory())[0])


@test("meal_cheap: banned and the meals under half the target, or good meals enough: lifted")
def _():
    s = fort()
    pop = int(s["dwarves"]["total"])
    target = pop * CFG["meals_per_dwarf"]
    m = Memory()
    m.cheap_cook_ban = True
    s["stocks"]["prepared_meals"] = target - 1
    assert not rule(s, m)                             # between half and the target: kept as it is
    s["stocks"]["prepared_meals"] = int(target * planner_farms.MEAL_DRINK_LIFT) - 1
    p = rule(s, m)
    assert p and p[0].action == {"type": "kitchen_cheap", "ban": False}, p
    s["stocks"]["prepared_meals"] = target * 3
    s["supplies"]["good_meals"] = CFG["good_meals_pd"] * pop
    # (0.105.123 item22) hysteresis: at the line the ban is kept (asked again), lifted at GOOD_MEAL_LIFT times it
    p = rule(s, m)
    assert not p or p[0].action.get("ban") is True, p
    s["supplies"]["good_meals"] = int(CFG["good_meals_pd"] * pop * planner_farms.GOOD_MEAL_LIFT) + 1
    p = rule(s, m)
    assert p and p[0].action == {"type": "kitchen_cheap", "ban": False}, p
    assert not rule(s, Memory())                      # not banned: nothing to lift


@test("meal_cheap: recorded in memory (not when the bridge let go for want of meat); cooldown; words; classes")
def _():
    s = fort()
    m = Memory()
    p = [x for x in plan(copy.deepcopy(s), m)[0] if x.rule == "meal_cheap"]
    assert p, "no meal_cheap"
    record([(p[0], {"ok": True, "banned": 12})], s, m)
    assert m.cheap_cook_ban is True
    m2 = Memory()
    record([(p[0], {"ok": True, "short": True, "lifted": 0})], s, m2)
    assert m2.cheap_cook_ban is False
    d = Memory().to_dict() if hasattr(Memory, "to_dict") else None
    if d is not None:
        assert "cheap_cook_ban" in d
    assert COOLDOWN_KEYS["meal_cheap"] == "needs_meal_cooldown_ticks"
    assert overseer_words.short({"type": "kitchen_cheap", "ban": True}).startswith("keep the cheap ingredients")
    assert overseer_words.short({"type": "kitchen_cheap", "ban": False}) == "let the cooks use the cheap ingredients again"
    assert "meal_cheap" in _SURVIVAL_RULES and "kitchen_cheap" in _SURVIVAL_ACTIONS


@test("kitchen_cheap: in the action table and the dry-run list; meat, cheese and flour never banned")
def _():
    cat = (ROOT / "lua" / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "kitchen_cheap = act_kitchen_cheap" in cat and "'kitchen_cheap'" in cat
    a = (ROOT / "lua" / "ai-bridge-actions-fort.lua").read_text(encoding="utf-8")
    body = a[a.index("local CHEAP_TYPES"):a.index("function act_kitchen_cheap")]
    cheap = re.search(r"CHEAP_TYPES = \{(.*?)\}", body).group(1)
    assert "MEAT" not in cheap and "CHEESE" not in cheap and "POWDER" not in cheap, cheap
    assert "'PLANT_GROWTH'" in cheap and "'EGG'" in cheap and "'FISH'" in cheap


try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

if LuaRuntime is not None:
    LUA_DIR = ROOT / "lua"
    HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                        (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)
    LUA = LuaRuntime(unpack_returned_tuples=True)
    H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    from strict_fakes import install as strict_install
    strict_install(LUA, H)

    @test("kitchen_cheap (Lua, strict fakes): the cheap kinds banned while meat is left; fish too; let go (short) when it runs out")
    def _():
        # (F1b) strict fakes: the old `{flags = {}, mat_type = ...}` answered nil to
        # it.flags.forbidden and fish.mat_type, both of which threw in every fort
        H.scripts = LUA.table()
        env = H.module()
        src = """local env, H, meat_n, fish_n = ...
          local added, removed = {}, 0
          H.dfhack.kitchen = {addExclusion = function(_, t, s, mt, mi) table.insert(added, t .. ':' .. mt); return true end,
                              removeExclusion = function() removed = removed + 1; return true end}
          H.dfhack.persistent = H.dfhack.persistent or {}
          local store = {}
          H.dfhack.persistent.getSiteData = function(k) return store[k] end
          H.dfhack.persistent.saveSiteData = function(k, v) store[k] = v end
          -- strict fakes (tests/strict_fakes.py): a field the df type has not raises, as in
          -- the game; what only the test needs (value, count, edible) lives beside them
          local side = setmetatable({}, {__mode = 'k'})
          H.dfhack.matinfo = H.dfhack.matinfo or {}
          H.dfhack.matinfo.decode = function(it) return {material = {flags = {EDIBLE_COOKED = side[it].edible}}} end
          H.dfhack.items = H.dfhack.items or {}
          H.dfhack.items.getValue = function(it) return side[it].v end
          local function item(tn, n, v, mt, edible)
            local f = {flags = {}}
            if tn ~= 'item_eggst' and tn ~= 'item_fishst' then f.mat_type, f.mat_index = mt, 0 end   -- fish and eggs have none
            local it = H.strict(tn, f)
            side[it] = {n = n, v = v, mt = mt, edible = edible ~= false}
            function it:getStackSize() return side[self].n end
            function it:getSubtype() return -1 end
            function it:getActualMaterial() return side[self].mt end          -- (0.105.121)
            function it:getActualMaterialIndex() return 0 end
            return it
          end
          H.df.item_type = {PLANT = 1, PLANT_GROWTH = 2, SEEDS = 3, EGG = 4, FISH = 5, LIQUID_MISC = 6, GLOB = 7,
                            MEAT = 8, CHEESE = 9, POWDER_MISC = 10}
          local fish = {}
          if fish_n > 0 then fish = {item('item_fishst', fish_n, fish_n, 500)} end
          H.df.global.world.items = {other = {
            PLANT = {item('item_plantst', 10, 20, 100), item('item_plantst', 5, 50, 101),
                     item('item_plantst', 5, 5, 102, false)},
            PLANT_GROWTH = {item('item_plant_growthst', 30, 60, 200)}, SEEDS = {},
            EGG = {item('item_eggst', 4, 8, 300)}, FISH = fish,
            LIQUID_MISC = {}, GLOB = {}, MEAT = {item('item_meatst', meat_n, meat_n * 4, 400)}, CHEESE = {}, POWDER_MISC = {}}}
          local b = env.act_kitchen_cheap({ban = true, min_value = 3, keep = 20})
          local n_added = #added
          local l = env.act_kitchen_cheap({ban = false})
          return b.ok, b.banned, b.short, n_added, l.lifted, b.error
        """
        r = LUA.execute(src, env, H, 30, 0)
        # plant 100 (2 a unit), growth 200 (2), egg 300 (2) banned; plant 101 (10) and meat kept; the inedible not seen
        assert tuple(r)[:5] == (True, 3, None, 3, 3), tuple(r)
        env = H.module()
        r = LUA.execute(src, env, H, 30, 6)       # a fish (1 a unit, no mat_type field): banned as well
        assert tuple(r)[:5] == (True, 4, None, 4, 4), tuple(r)
        env = H.module()
        r = LUA.execute("""local env, H = ...
          H.df.global.world.items.other.MEAT = {}
          local b = env.act_kitchen_cheap({ban = true, min_value = 3, keep = 20})
          return b.ok, b.short, b.kept
        """, env, H)
        assert tuple(r) == (True, True, 5), tuple(r)

    @test("strict fakes (Lua): an item fake raises on a field its df type has not, as DFHack does")
    def _():
        r = LUA.execute("""local H = ...
          local egg = H.strict('item_eggst', {flags = {}})
          local a = {pcall(function() return egg.mat_type end)}
          local b = {pcall(function() return egg.flags.forbidden end)}
          return a[1], tostring(a[2]), b[1], tostring(b[2]), egg.flags.forbid
        """, H)
        r = tuple(r)
        assert r[0] is False and "Cannot read field item_eggst.mat_type: not found." in r[1], r
        assert r[2] is False and "Cannot read field item_flags.forbidden: not found." in r[3], r
        assert r[4] is False, r


if __name__ == "__main__":
    finish()
