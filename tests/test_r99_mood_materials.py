"""(0.105.99, item 9) Strange moods get their materials.

Live 24 Nov 00:35:
- B: Edzul Moerullibad's Secretive mood (FORGE_FURNITURE) waited 41 days and
  died of thirst at 00:18. Its first request (2 iron bars, free in a plain bin
  on a stockpile) read "on hand", so the AI smelted bars five times; the real
  blockers had nothing done: "1 cloth (plant)" counted "other 20" (the probe:
  all 20 the stuck caravan's, flags trader + foreign, 10 in a depot bin and 10
  in a bin a merchant carried; the fort's 15 thread all in the hospital's
  chests, thread_kinds 0), and "1 leather" counted free (a foreign leather in
  a bin: DF takes no foreign item) or forbidden (a foreign leather in a
  forbidden foreign bin). Player orders (MakePants, MakeArmor) took the cloth.
- D: Nil's Fey mood: "1 bar (metal)" with a smelter, coke and ore ("already
  on order": an order not the AI's counted as one), and "1 log" with 19 out of
  the dwarf's walk.

    python tests/test_r99_mood_materials.py
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
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_moods  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
FAKE = re.search(r'FAKE = r"""(.*?)"""', (ROOT / "tests" / "test_moods.py").read_text(encoding="utf-8"),
                 re.S).group(1)


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].update({"Butchers": 1, "Farmers": 1, "Loom": 1, "Tanners": 1})
    s["others_on_map"]["tame_animals"] = 20
    s.setdefault("supplies", {})
    s["supplies"].update({"thread_kinds": {"plant": 0, "silk": 0, "yarn": 0}, "hospital": {"thread": 15, "cloth": 0},
                          "hides": 0})
    return s


BARS = {"item": "BAR", "quantity": 2, "flags": [], "avail": {"free": 2, "reach": 2, "enough": True}}
CLOTH = {"item": "CLOTH", "quantity": 1, "flags": ["plant"], "avail": {"trader": 20}}
LEATHER = {"item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": {"trader": 3}}


def edzul(s, thirst=30000, stalled=41):
    props, notes = [], []
    planner_moods._mood_materials(s, "Edzul", "Secretive", copy.deepcopy([BARS, CLOTH, LEATHER]), 43, props, notes,
                                  CFG, memory=Memory(), unit_id=17169, stalled=stalled, thirst=thirst)
    return props, notes


@test("B's Edzul: the bars on hand are not smelted again while the cloth and leather lack")
def _():
    s = fort()
    s["industry"] = {"ore_stock_by": {"TETRAHEDRITE": {"n": 5, "metals": ["COPPER"]}}}
    s["supplies"]["fuel"] = 50
    s["buildings"].setdefault("furnaces", {})["Smelter"] = 1
    props, notes = edzul(s)
    assert not any(p.action.get("recipe") == "smelt_ore" for p in props), [p.action for p in props]


@test("B's Edzul: the trader's cloth and the hospital's thread are said; thirsty: priority 0, said")
def _():
    s = fort()
    s["orders"] = [{"id": 2421, "recipe": "process_plants", "by_ai": True, "amount_left": 2, "amount_total": 5},
                   {"id": 1898, "job": "MakePants", "by_ai": False, "amount_left": 2, "mat_cats": ["cloth"]},
                   {"id": 1901, "job": "MakeArmor", "by_ai": False, "amount_left": 3, "mat_cats": ["cloth"]},
                   {"id": 2500, "recipe": "cloth_bag", "by_ai": True, "amount_left": 3, "amount_total": 3}]
    props, notes = edzul(s)
    text = " | ".join(notes + [p.reason for p in props])
    assert "a trader's goods" in text, text
    assert "hospital's chests" in text, text
    assert "thirsty" in text and "MakeArmor" in text and "MakePants" in text, text
    # the AI's own cloth-using order goes (the mood urgent), the player's never
    cancels = [p for p in props if p.action.get("type") == "cancel_work_order"]
    assert [p.action["order_id"] for p in cancels] == [2500], [p.action for p in cancels]
    assert all(p.priority == 0 for p in props), [(p.rule, p.priority) for p in props]
    # the leather: a hide tanned or an animal to the butcher (the trader's leather is no leather)
    assert any(p.action.get("type") == "slaughter_one" for p in props), [p.action for p in props]


@test("not thirsty, not long stalled: priority 1 and no cancel of an order nothing holds")
def _():
    s = fort()
    s["orders"] = [{"id": 2500, "recipe": "cloth_bag", "by_ai": True, "amount_left": 3, "amount_total": 3}]
    props, notes = edzul(s, thirst=100, stalled=3)
    assert not any(p.action.get("type") == "cancel_work_order" for p in props)
    assert all(p.priority == 1 for p in props), [(p.rule, p.priority) for p in props]
    assert not any("thirsty" in n for n in notes)


@test("every request on hand and stalled: the first is still made again (0.105.33 kept)")
def _():
    s = fort()
    bone = {"item": "NONE", "quantity": 1, "flags": ["bone"], "avail": {"free": 1, "reach": 1, "enough": True}}
    props, notes = [], []
    planner_moods._mood_materials(s, "Udib", "Possessed", [bone], 40, props, notes, CFG, memory=Memory(),
                                  unit_id=5, stalled=40)
    assert any(p.action.get("type") == "slaughter_one" for p in props), [p.action for p in props]


@test("D's bars: a smelt order not the AI's counts as none once the mood has stalled")
def _():
    s = fort()
    s["industry"] = {"ore_stock_by": {"HEMATITE": {"n": 9, "metals": ["IRON"]}}}
    s["supplies"]["fuel"] = 47
    s["buildings"].setdefault("furnaces", {})["Smelter"] = 1
    s["orders"] = [{"id": 1, "recipe": "smelt_ore", "by_ai": False, "amount_left": 1, "amount_total": 1}]
    bar = {"item": "BAR", "quantity": 1, "flags": ["metal"], "avail": {}}
    acts, why = planner_moods._mood_make(s, bar, "bar", Memory(), CFG, mood={"name": "Nil", "stalled": 30})
    assert [a.get("recipe") for a, _ in acts] == ["smelt_ore"], (acts, why)
    # a fresh mood still waits on whatever is queued
    acts, why = planner_moods._mood_make(s, bar, "bar", Memory(), CFG, mood={"name": "Nil", "stalled": 1})
    assert acts == [] and why is None, (acts, why)


@test("D's log out of the dwarf's walk: one of the fort's own underground trees is felled")
def _():
    s = fort()
    s["forestry"] = {"inside": {"reachable": 4}, "cavern": {"reachable": 0}}
    log = {"item": "WOOD", "quantity": 1, "flags": [], "avail": {"free": 19, "reach": 0}}
    props, notes = [], []
    planner_moods._mood_materials(s, "Nil", "Fey", [log], 41, props, notes, CFG, memory=Memory(), unit_id=19115,
                                  stalled=41)
    fell = [p.action for p in props if p.action.get("type") == "cavern_logging"]
    assert fell == [{"type": "cavern_logging", "limit": 1, "inside_only": True}], [p.action for p in props]
    # no tree inside: the out-of-walk line stays
    s["forestry"] = {"inside": {"reachable": 0}}
    props, notes = [], []
    planner_moods._mood_materials(s, "Nil", "Fey", [log], 41, props, notes, CFG, memory=Memory(), unit_id=19115,
                                  stalled=41)
    assert not any(p.action.get("type") == "cavern_logging" for p in props)
    assert any("can't walk" in n for n in notes), notes


@test("a request on order while the mood stalls is said, not silent")
def _():
    s = fort()
    s["orders"] = [{"id": 2421, "recipe": "process_plants", "by_ai": True, "amount_left": 2, "amount_total": 5}]
    s["supplies"]["thread_plants"] = 48
    props, notes = [], []
    planner_moods._mood_materials(s, "Edzul", "Secretive", [dict(CLOTH, avail={})], 20, props, notes, CFG,
                                  memory=Memory(), unit_id=1, stalled=10)
    assert any("already on order" in n for n in notes) or any(p.action.get("recipe") for p in props), \
        (notes, [p.action for p in props])


@test("the counts and the journal: trader, hospital, part-used apart; thirst in the record")
def _():
    t = planner_moods.mood_counts_text({"item": "CLOTH", "quantity": 1, "flags": ["plant"],
                                        "avail": {"trader": 20, "hospital": 2, "partial": 1}})
    assert "20 a trader's goods" in t and "2 the hospital's" in t and "part-used" in t, t
    s = fort()
    s["moods"] = {"list": [{"unit_id": 17169, "name": "Edzul", "mood": "Secretive", "craft": True, "thirst": 31000,
                            "missing": [CLOTH]}]}
    rec = planner_moods.mood_journal(s, Memory())
    assert rec and rec[0]["thirst"] == 31000 and rec[0]["thirsty"] is True, rec
    assert rec[0]["requests"][0]["avail"] == {"trader": 20}, rec


@test("the bridge: thirst reported with the mood, orders' material categories, files under 60 KB")
def _():
    fort_src = (ROOT / "lua" / "ai-bridge-report-fort.lua").read_text(encoding="utf-8")
    assert "e.thirst = u.counters2.thirst_timer" in fort_src
    orders = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "e.mat_cats = cats" in orders
    moods = (ROOT / "lua" / "ai-moods.lua").read_text(encoding="utf-8")
    assert "function traders_item" in moods and "function out_of_bin" in moods
    for f in ("ai-moods.lua", "ai-bridge-orders.lua", "ai-bridge-report-fort.lua"):
        assert (ROOT / "lua" / f).stat().st_size < 60 * 1024, f


# ---- Lua (lupa: these run on the PC) -----------------------------------------------------

EXTRA = r"""
local W = ...
local env = W.env
env.dfhack.items.getContainer = function(it) return it.cont end
env.dfhack.items.getHolderUnit = function(it) return nil end
env.dfhack.items.moveToGround = function(it, pos) it.cont = nil; it.moved = pos; return true end
"""


def lua_world():
    from lupa.lua53 import LuaRuntime
    L = LuaRuntime(unpack_returned_tuples=True)
    W = L.execute(FAKE, module_src("ai-moods.lua"))
    W.reset()
    W.env.HOSPITAL_CACHE = None
    L.execute(EXTRA, W)
    return L, W


def req(L, *rows):
    return L.table_from([L.table_from({k: (L.table_from(v) if isinstance(v, list) else v) for k, v in r.items()})
                         for r in rows])


@test("Lua: a trader's (or foreign) bar, or one in a trader's bin, counts as `trader`, not free")
def _():
    need_lua()
    L, W = lua_world()
    env = W.env
    j = W.job(req(L, {"t": 4, "kind": 0, "q": 3}), L.table_from([]))
    u = W.unit(7, j)
    W.item(4, 0, 1, L.table_from({"foreign": True}))
    W.item(4, 0, 2, L.table_from({"trader": True}))
    inbin = W.item(4, 0, 3)
    inbin.cont = L.table_from({"flags": L.table_from({"trader": True, "foreign": True})})
    W.item(4, 0, 4)
    a = env.mood_report(j, u)[1].avail
    assert a.trader == 3 and a.free == 1 and a.reach == 1, dict(a)


@test("Lua: a bar in a forbidden bin counts forbidden; free_items sets it on the ground, the bin untouched")
def _():
    need_lua()
    L, W = lua_world()
    env = W.env
    j = W.job(req(L, {"t": 4, "kind": 0, "q": 1}), L.table_from([]))
    W.unit(7, j)
    it = W.item(4, 0, 5)
    binf = L.table_from({"forbid": True})
    it.cont = L.table_from({"flags": binf, "x": 5})
    a = env.mood_report(j, W.units[7])[1].avail
    assert a.forbidden == 1 and a.forbidden_reach == 1, dict(a)
    r = env.free_items(7, False, 5)
    assert r.ok and r.freed == 1, dict(r)
    assert it.moved is not None and it.cont is None and binf.forbid is True


finish()
