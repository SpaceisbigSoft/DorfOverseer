"""(item4) Idle miners and the Deep mine's depth (brain/planner_prospect.py,
planner_industry_stone's vein rule, planner_descent.by_character):

- D, the Hermit hold (26 Nov: 12 miners, 0 tiles to dig, 73 bars, 257 ore
  boulders, 4 rough gems, 25-35% idle): exploratory mining, gems once the
  dug ore is over its Mining line; nothing at Mining -50 or lower (the
  Garden fort), with digging waiting, under threat, a young fort, or too soon;
- E, the Deep mine (Mining 150: 20 miners, 247 tiles waiting, 78 bars, 54
  ore): the vein rule no longer waits for under 50 tiles of digging, paced
  by Mining (2.5 days) where D waits a week; the crossing past Cavern1 on by
  its character (Verticality 120, Mining 150), not for any other preset;
- the wiring: the label, the hold class, the plan() call, the bridge's 'GEM'.

    python tests/test_item4_mining.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
import hold_classes as hc  # noqa: E402
import planner_descent as PD  # noqa: E402
import planner_prospect as PP  # noqa: E402
from design_rules import PRESET_SLIDERS  # noqa: E402
from overseer_words import short as describe_action  # noqa: E402
from planner import Memory, PLANNER_CONFIG, Proposal  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_industry_stone import _industry_rules  # noqa: E402

CFG = PLANNER_CONFIG


def fort(preset="Hermit hold", miners=12, dig=0, ore_stock=257, gems=4, bars=73, threats=0, pop=54, ores=None):
    by = {"HEMATITE": {"metals": ["IRON"], "n": 60}, "TETRAHEDRITE": {"metals": ["COPPER", "SILVER"], "n": 54},
          "CASSITERITE": {"metals": ["TIN"], "n": 9}}
    return {"settings": {"traits": dict(PRESET_SLIDERS[preset]), "preset": preset},
            "dwarves": {"total": pop}, "date": {"year": 258, "tick": 100000},
            "labor": {"miners": miners, "dig": dig},
            "industry": {"ore_stock": ore_stock, "ore_stock_by": by,
                         "ores": ores if ores is not None else
                         {"IRON": {"ore": "HEMATITE", "tiles": 1005}, "COPPER": {"ore": "TETRAHEDRITE", "tiles": 343},
                          "TIN": {"ore": "CASSITERITE", "tiles": 12}, "ADAMANTINE": {"ore": "RAW_ADAMANTINE", "tiles": 5}}},
            "stocks": {"rough_gems": gems}, "military": {"gear": {"bars": {"IRON": bars}}},
            "others_on_map": {"threats_that_can_reach_dwarves": threats},
            "buildings": {"furnaces": {"Smelter": 1, "WoodFurnace": 1}, "workshops": {"MetalsmithsForge": 1}},
            "supplies": {}, "projects": {"open": []}, "orders": [], "stone_use": {}}


def prospect(s, memory=None):
    m = memory if memory is not None else Memory()
    props, notes = [], []
    PP._prospect_rule(s, m, CFG, props, notes)
    return props, notes


@test("D (Hermit hold, 12 idle miners, nothing to dig, ore over its line): a gem vein through safe rock")
def _():
    props, _ = prospect(fort())
    assert len(props) == 1 and props[0].rule == "prospect", props
    a = props[0].action
    assert a == {"type": "mine_ore", "metal": "GEM", "count": 30, "prospect": True}, a
    assert "12 miners" in props[0].reason and "4 rough gems" in props[0].reason, props[0].reason


@test("ore first while the dug ore is under the Mining line: the metal least in store; never adamantine")
def _():
    props, _ = prospect(fort(ore_stock=20))
    assert props and props[0].action["metal"] == "TIN", props            # 9 boulders of tin, iron 60
    s = fort(ore_stock=20, ores={"ADAMANTINE": {"ore": "RAW_ADAMANTINE", "tiles": 9}})
    props, _ = prospect(s)
    assert props and props[0].action["metal"] == "GEM", props


@test("a refused metal waits out its back-off and the next is tried; all in store enough: nothing dug, no note")
def _():
    m = Memory()
    s = fort(ore_stock=20)
    now = abs_tick(s)
    from planner_core import refusal_key
    p = Proposal("prospect", {"type": "mine_ore", "metal": "TIN"}, "", 5)
    m.refusals = {refusal_key(p): {"until": now + 3 * TICKS_PER_DAY, "at": now}}
    props, _ = prospect(s, m)
    assert props and props[0].action["metal"] != "TIN", props
    props, notes = prospect(fort(gems=40))
    assert not props and not notes, (props, notes)


@test("nothing with digging waiting, no miners, under threat, a young fort, too soon, or Mining -50 and lower")
def _():
    assert not prospect(fort(dig=30))[0]                     # 12 miners x 2 x1: 24
    assert prospect(fort(dig=20))[0]
    assert not prospect(fort(miners=0))[0]
    assert not prospect(fort(threats=1))[0]
    assert not prospect(fort(pop=10))[0]                     # young: nothing fed in the stub
    assert not prospect(fort(preset="Garden fort"))[0]       # Mining -60: no veins at all
    m = Memory()
    s = fort()
    m.last_fired["prospect"] = abs_tick(s) - 2 * TICKS_PER_DAY
    assert not prospect(s, m)[0]                             # every 3 days at Mining 0
    m.last_fired["prospect"] = abs_tick(s) - 4 * TICKS_PER_DAY
    assert prospect(s, m)[0]
    other = [Proposal("ore", {"type": "mine_ore", "metal": "IRON"}, "", 5)]
    PP._prospect_rule(fort(), Memory(), CFG, other, [])
    assert len(other) == 1                                   # the vein rule's own this cycle


@test("the pace by Mining: the Deep mine every day (3 / 2.83, at least 1) and more tiles; less with digging waiting")
def _():
    deep = fort(preset="Deep mine", miners=20, dig=50, ore_stock=54, gems=3)
    m = Memory()
    m.last_fired["prospect"] = abs_tick(deep) - int(1.1 * TICKS_PER_DAY)
    props, _ = prospect(deep, m)
    assert props and props[0].action["count"] == 80, props          # 30 x 2.83 = 84, at most 80
    assert props[0].action["metal"] == "TIN", props[0].action        # 54 ore under 84: ore, the least in store
    assert prospect(fort(preset="Deep mine", miners=20, dig=120, ore_stock=54))[0] == []   # 20 x 2 x 2.83 = 113


@test("E: the vein rule takes a vein with 247 tiles waiting (20 miners x 5 x 2.83), paced 2.5 days; D waits a week")
def _():
    e = fort(preset="Deep mine", miners=20, dig=247, ore_stock=54, bars=78)
    assert PP.vein_dig_cap(e, CFG) == 282
    assert PP.vein_dig_cap(fort(), CFG) == 60
    assert PP.vein_dig_cap(fort(preset="Garden fort", miners=5), CFG) == 50      # never under the old 50
    props, notes = [], []
    _industry_rules(e, Memory(), CFG, 97, props, notes)
    ore = [p for p in props if p.rule == "ore"]
    assert ore and ore[0].action["metal"] == "IRON" and ore[0].action["count"] == 80, props
    m = Memory()
    m.last_fired["ore"] = abs_tick(e) - 3 * TICKS_PER_DAY
    props = []
    _industry_rules(e, m, CFG, 97, props, [])
    assert [p for p in props if p.rule == "ore"], "2.5 days at Mining 150"
    d = fort(bars=10, ore_stock=20)
    m = Memory()
    m.last_fired["ore"] = abs_tick(d) - 3 * TICKS_PER_DAY
    props = []
    _industry_rules(d, m, CFG, 54, props, [])
    assert not [p for p in props if p.rule == "ore"], "a week at Mining 0"
    props = []
    _industry_rules(fort(preset="Deep mine", miners=20, dig=300, ore_stock=54, bars=78), Memory(), CFG, 97, props, [])
    assert not [p for p in props if p.rule == "ore"], "over 282 tiles waiting"
    assert CFG["ore_cooldown_ticks"] <= CFG["ore_days"] * TICKS_PER_DAY / 2.83


@test("the crossing past Cavern1 on by the Deep mine's character alone; the switches as before")
def _():
    on = {p: PD.descent_on({"settings": {"traits": dict(t), "deep_descent": False}}, CFG)
          for p, t in PRESET_SLIDERS.items()}
    assert on == {p: p == "Deep mine" for p in PRESET_SLIDERS}, on
    assert not PD.descent_on({"settings": {"traits": {"verticality": 120, "mining": 60}}}, CFG)
    assert not PD.descent_on({"settings": {"traits": {"verticality": 60, "mining": 150}}}, CFG)
    off = dict(CFG, deep_descent_by_character=False)
    assert not PD.descent_on({"settings": {"traits": dict(PRESET_SLIDERS["Deep mine"])}}, off)
    assert PD.descent_on({"settings": {"deep_descent": True}}, off)
    assert CFG["deep_descent"] is False and not PD.descent_on({"settings": {}}, CFG)


@test("wiring: the label, an expansion step, plan() calls the rule, the bridge mines 'GEM' veins")
def _():
    assert describe_action({"type": "mine_ore", "metal": "GEM", "count": 30, "prospect": True}).startswith("dig for gems")
    assert describe_action({"type": "mine_ore", "metal": "IRON", "prospect": True}) == "dig for ore: mine a vein of iron ore"
    assert describe_action({"type": "mine_ore", "metal": "IRON"}) == "mine a vein of iron ore"
    assert hc.step_class(Proposal("prospect", {"type": "mine_ore", "metal": "GEM"}, "", 6)) == hc.EXPANSION
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert "_guard(_prospect_rule, s, memory, cfg, proposals, notes)" in src
    lua = (ROOT / "lua" / "ai-industry.lua").read_text(encoding="utf-8")
    assert "inorg.material.flags.IS_GEM" in lua and lua.count("end, metal == 'GEM')") == 2
    assert "metal == 'GEM' and 'gems'" in lua
    for f in ("ai-industry.lua", "ai-bridge-actions-works.lua"):
        assert (ROOT / "lua" / f).stat().st_size < 60_000, f
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


if __name__ == "__main__":
    finish()
