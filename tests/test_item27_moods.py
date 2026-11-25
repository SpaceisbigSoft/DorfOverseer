"""(0.105.116 item27) The first year's failed moods of the 25 Nov fresh start.

A, 13:26-13:41: Minkot's fey mood waited 30 days on "1 bar (metal)" (no named
metal) with 11 bars in the caravan at the depot: mood_trade_wants gave no key
for a bar of no named metal, the deal bought food and no bar, Minkot went
berserk and a recruit struck him down. A, B, D: a year in with 44-129 ore
stones and no smelter until the mood's first day; three fey moods failed for
one or two bars. B: Såkzul, a possessed weaponsmith, waited for a forge with
no anvil in the fort. A, B, D, E: the mood reserve asked for a spare animal
10-13 times in 2.5 hours, refused each time ("no spare tame animal (three or
more of a kind, adult, no pet or war animal)").

    python tests/test_item27_moods.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

import planner_moods  # noqa: E402
import planner_trade  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"


def av(**kw):
    a = {"free": 0, "reach": 0, "forbidden": 0, "forbidden_reach": 0, "dump": 0, "job": 0, "other": 0,
         "held": 0, "trader": 0, "hospital": 0}
    a.update(kw)
    return a


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Tanners": 1})
    s["others_on_map"]["tame_animals"] = 23
    s.setdefault("supplies", {})
    return s


BAR_ANY = {"index": 1, "item": "BAR", "quantity": 1, "flags": ["metal"], "avail": av(trader=11)}


def mood(missing, **kw):
    m = {"unit_id": 17004, "name": "Minkot", "mood": "Fey", "craft": True, "skill": "LEATHERWORK",
         "workshop": "Leatherworks", "items_have": 2, "items_needed": 3, "missing": missing}
    m.update(kw)
    return m


# ---- 1. a bar of no named metal is bought from the caravan ------------------------------------

@test("1 brain: a mood's bar of no named metal is the caravan want BAR:METAL, first on the trade list")
def _():
    s = fort()
    s["moods"] = {"list": [mood([dict(BAR_ANY)])]}
    assert planner_moods.mood_trade_wants(s) == [{"key": "BAR:METAL", "count": 1}]
    wants = planner_trade.trade_wants(s, CFG, 22)
    assert wants[0] == {"key": "BAR:METAL", "count": 1}, wants[:3]
    # a named metal keeps its own key
    s["moods"]["list"][0]["missing"] = [dict(BAR_ANY, material="silver")]
    assert planner_moods.mood_trade_wants(s) == [{"key": "BAR:SILVER", "count": 1}]
    # a bar within the dwarf's walk: no want
    s["moods"]["list"][0]["missing"] = [dict(BAR_ANY, avail=av(free=1, reach=1))]
    assert planner_moods.mood_trade_wants(s) == []


@test("1 lua: want_matches BAR:METAL takes any metal bar, never coal, potash or ash")
def _():
    src = (LUA / "ai-trade.lua").read_text(encoding="utf-8")
    body = re.search(r"\nfunction want_matches\(.*?\nend\n", src, re.S).group(0)
    assert "key == 'BAR:METAL'" in body and "'COAL'" in body and "'POTASH'" in body
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        print("    (lupa not installed: the Lua half skipped)")
        return
    L = LuaRuntime(unpack_returned_tuples=True)
    L.execute(body + re.search(r"\nfunction pick_buys\(.*?\nend\n", src, re.S).group(0))
    g = L.globals()
    c = lambda **kw: L.table_from(kw)  # noqa: E731
    for cat in ("BAR:IRON", "BAR:COPPER", "BAR:SILVER", "BAR:STEEL"):
        assert g.want_matches("BAR:METAL", c(cat=cat)), cat
    for cat in ("BAR:COAL", "BAR:POTASH", "BAR:PEARLASH", "BAR:ASH", "CLOTH", "BOULDER:ORE_IRON"):
        assert not g.want_matches("BAR:METAL", c(cat=cat)), cat
    assert not g.want_matches("BAR:IRON", c(cat="BAR:COPPER"))
    cands = L.table_from([c(idx=1, cat="BAR:COAL", n=1, value=3), c(idx=2, cat="BAR:IRON", n=1, value=30),
                          c(idx=3, cat="BAR:COPPER", n=1, value=20)])
    picks, spent = g.pick_buys(cands, L.table_from([c(key="BAR:METAL", count=1)]), 1000)
    assert [p.idx for p in picks.values()] == [3] and spent == 20      # the cheapest metal bar


# ---- 2. a smelter and a forge kept standing ----------------------------------------------------

@test("2: a smelter is a mood shop kept standing while ore stones lie about; a forge too with an anvil")
def _():
    s = fort()
    s["buildings"]["furnaces"] = {}
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["buildings"]["workshops"].pop("MagmaForge", None)
    s["industry"] = {"ore_stock_by": {"HEMATITE": {"metals": ["IRON"], "n": 22}}}
    s["supplies"]["anvils"] = 1
    miss = planner_moods.mood_shops_missing(s)
    assert "Smelter" in miss and "MetalsmithsForge" in miss, miss
    s["supplies"]["anvils"] = 0
    miss = planner_moods.mood_shops_missing(s)
    assert "Smelter" in miss and "MetalsmithsForge" not in miss, miss     # a forge stands on an anvil
    s["buildings"]["furnaces"] = {"MagmaSmelter": 1}
    assert "Smelter" not in planner_moods.mood_shops_missing(s)
    s["buildings"]["furnaces"] = {}
    s["industry"] = {"ore_stock_by": {}}
    assert "Smelter" not in planner_moods.mood_shops_missing(s)


@test("2: a metalsmith's mood with no forge and no anvil asks the caravan for an anvil")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["buildings"]["workshops"].pop("MagmaForge", None)
    s["supplies"]["anvils"] = 0
    s["moods"] = {"list": [mood([{"index": 0, "item": "BAR", "quantity": 2, "flags": [], "avail": av()}],
                                name="Såkzul", mood="Possessed", skill="FORGE_WEAPON", workshop=None)]}
    assert {"key": "ANVIL", "count": 1} in planner_moods.mood_trade_wants(s)
    s["supplies"]["anvils"] = 1
    assert {"key": "ANVIL", "count": 1} not in planner_moods.mood_trade_wants(s)


# ---- 3. the reserve's slaughter only while an animal qualifies --------------------------------

HERD_A = [  # A's herd at 14:18: no kind with three adults that are nobody's pet
    {"name": "SHEEP", "n": 4, "f": 2, "m": 0, "kids": 2, "protected": 3, "marked": 0, "caged": 0},
    {"name": "HORSE", "n": 2, "f": 1, "m": 1, "kids": 0, "protected": 0, "marked": 0, "caged": 0},
    {"name": "YAK", "n": 2, "f": 1, "m": 1, "kids": 0, "protected": 0, "marked": 0, "caged": 0},
]


@test("3: spare_tame_kinds counts kinds with three adults to spare; None from an older bridge")
def _():
    s = fort()
    s["herd"] = {"kinds": copy.deepcopy(HERD_A)}
    assert planner_moods.spare_tame_kinds(s) == 0
    s["herd"]["kinds"].append({"name": "GOAT", "n": 5, "f": 3, "m": 1, "kids": 1, "protected": 1})
    assert planner_moods.spare_tame_kinds(s) == 1
    s["herd"] = {}
    assert planner_moods.spare_tame_kinds(s) is None


@test("3: the reserve's bones/leather slaughter is not proposed while no animal qualifies")
def _():
    s = fort()
    s["herd"] = {"kinds": copy.deepcopy(HERD_A), "marked": 0, "marked_waiting": 0}
    acts: list = []
    assert planner_moods._mood_slaughter(s, Memory(), CFG, acts, "its bones") is False and acts == []
    assert "three or more adults" in planner_moods._slaughter_why(s, Memory(), CFG, None)
    # a mood's own slaughter (any spare animal, young too) is still asked
    acts = []
    assert planner_moods._mood_slaughter(s, Memory(), CFG, acts, "its bones",
                                         mood={"name": "Minkot", "unit_id": 17004}) is True
    assert acts and acts[0][0].get("mood") is True
    # a kind that qualifies: proposed
    s["herd"]["kinds"].append({"name": "GOAT", "n": 5, "f": 3, "m": 1, "kids": 1, "protected": 1})
    acts = []
    assert planner_moods._mood_slaughter(s, Memory(), CFG, acts, "its bones") is True
    assert acts[0][0] == {"type": "slaughter_one"}


# ---- 4. a mood's shop placed as one building, past the project cap ----------------------------

import planner_core  # noqa: E402
import planner_mood_help as MH  # noqa: E402


def bar_fort():
    s = fort()
    s["buildings"]["furnaces"] = {}
    s["industry"] = {"ore_stock_by": {"HEMATITE": {"metals": ["IRON"], "n": 22}}}
    s["projects"] = {"open": []}
    return s


def refuse(m, rule, kind, s):
    p = planner_core.Proposal(rule, {"type": "place_mood_shop", "kind": kind}, "", 0)
    now = planner_core.abs_tick(s)
    m.refusals[planner_core.refusal_key(p)] = {"n": 1, "at": now, "until": now + 5 * 1200}


@test("4: a bar mood and no smelter: one smelter placed on free floor (no level); placed: coming; refused: the level")
def _():
    s = bar_fort()
    m = Memory()
    who = {"name": "Minkot", "unit_id": 17004}
    acts, why = planner_moods._mood_make(s, dict(BAR_ANY, avail=av()), "bar", m, CFG, mood=who)
    assert why is None and [a for a, _ in acts] == [{"type": "place_mood_shop", "kind": "Smelter"}], acts
    # the placement went through: recorded, and the smelter counts as coming (nothing again)
    MH.note_mood_help(planner_core.Proposal("mood", acts[0][0], "", 0), {"ok": True}, s, m, planner_core.abs_tick(s))
    assert planner_moods.shop_placed(s, m, "Smelter")
    acts, why = planner_moods._mood_make(s, dict(BAR_ANY, avail=av()), "bar", m, CFG, mood=who)
    assert why is None and acts == [], acts
    # placement refused (no free floor): the urgent level past the cap
    m2 = Memory()
    refuse(m2, "mood", "Smelter", s)
    acts, why = planner_moods._mood_make(s, dict(BAR_ANY, avail=av()), "bar", m2, CFG, mood=who)
    a = [a for a, _ in acts]
    assert a == [{"type": "start_project", "kind": "workshops", "shops": ["Smelter"], "urgent": True, "mood": True,
                  "mood_unit": 17004}], a


@test("4: a mood with no workshop to claim (Såkzul's forge): placed as one building at priority 0")
def _():
    s = fort()
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["buildings"]["workshops"].pop("MagmaForge", None)
    s["projects"] = {"open": []}
    s["moods"] = {"list": [{"unit_id": 17194, "name": "Såkzul", "mood": "Possessed", "craft": True,
                            "skill": "FORGE_WEAPON"}]}
    m = Memory()
    m.moods_seen = {"17194": planner_core.abs_tick(s)}
    props, notes = [], []
    planner_moods._mood_rules(s, m, CFG, props, notes)
    pl = [p for p in props if p.action.get("type") == "place_mood_shop"]
    assert [p.action for p in pl] == [{"type": "place_mood_shop", "kind": "MetalsmithsForge"}] and pl[0].priority == 0, \
        [p.action for p in props]
    assert not [p for p in props if p.action.get("type") == "start_project"]


@test("4: the kept-standing shops: each placed as one building; refused: one level past the cap (`mood`)")
def _():
    s = bar_fort()
    s["supplies"]["anvils"] = 0
    s["dwarves"]["total"] = 30
    props: list = []
    assert planner_moods._mood_shops_step(s, CFG, props, Memory())
    assert {"type": "place_mood_shop", "kind": "Smelter"} in [p.action for p in props], [p.action for p in props]
    m = Memory()
    for k in planner_moods.mood_shops_missing(s):
        refuse(m, "mood_reserve", k, s)
    props = []
    planner_moods._mood_shops_step(s, CFG, props, m)
    sp = [p.action for p in props if p.action.get("type") == "start_project"]
    assert sp and "Smelter" in sp[0]["shops"] and sp[0]["mood"] is True and not sp[0].get("urgent"), sp
    assert not [p for p in props if p.action.get("type") == "place_mood_shop"]


@test("4 wiring: place_mood_shop in the bridge's actions and dry runs, a label, a hold class")
def _():
    cat = (LUA / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "    place_mood_shop = function(a)" in cat and "'place_mood_shop'," in cat
    sg = (LUA / "ai-siege.lua").read_text(encoding="utf-8")
    assert "function place_mood_shop(kind, dry_run)" in sg and "do_now = true" in sg
    import overseer
    import hold_classes
    assert "place_mood_shop" in overseer.SHORT_WORDS
    assert "place_mood_shop" in hold_classes.ACTION_SETS[hold_classes.SURVIVAL]


if __name__ == "__main__":
    finish()
