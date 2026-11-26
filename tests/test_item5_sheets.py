"""(item5) Paper sheets stuck where they were made. Fort A (26 Nov): 2 sheets
held by the screw press, 65 stockpiles and none taking sheets (DF 53 keeps
them in their own group, stockpile_group_set.sheet), every make_quire order
stuck at "2 left" for 28 days and cancelled. Checked here:

  * the brain: the free sheets a quire job can reach (sheets_usable: less
    those held by a workshop), the stall said (sheet_stall), a sheet pile
    put beside the workshop holding them (rule paper_pile: feeder_pile), the
    kiln rule's make_quire sized by the reachable sheets only (none: said,
    no order), the stuck-order cancel saying why, the feeder rule not asking
    twice;
  * the bridge: the screw press's feeder is a sheet pile (Quickfort S),
    place_feeder takes any workshop holding sheets, the storage survey counts
    sheets, ai-paper's report says where the sheets lie (lupa: a fake game);
  * DF's names: the sheet group and its paper/parchment fields.

    python tests/test_item5_sheets.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish, need_lua, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

import planner_paper as PP  # noqa: E402
import digest  # noqa: E402
from planner import Memory, Proposal, PLANNER_CONFIG, abs_tick, TICKS_PER_DAY  # noqa: E402
from planner_industry_stone import _kiln_rules  # noqa: E402
from planner_industry_crafts import _feeder_rule  # noqa: E402
from planner_orders import _stuck_orders_rule  # noqa: E402

test = make_test()
CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"
PRESS_ID = 1155


def fort(sheets=5, stuck=2, piles=0, shop="ScrewPress", have=0, want=10) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["locations"]["list"] = [{"id": 7, "type": "LIBRARY", "have": {"paper": have}, "want": {"paper": want},
                               "jobs": {}, "zones": [70], "chests": 1, "flags": ["VISITORS_ALLOWED"]}]
    s["supplies"].update(sheets=sheets, blank_quires=0, gypsum=0, calcium_carbonate=0, empty_bags=0)
    s["buildings"]["workshops"] = {"Craftsdwarfs": 1, "ScrewPress": 1, "Carpenters": 1, "Quern": 1, "Kitchen": 2,
                                   "Still": 2}
    p = {"reactions": {"slurry": {"code": "MAKE_SLURRY_FROM_PLANT", "shops": ["Quern"], "inputs": 0},
                       "press": {"code": "PRESS_PLANT_PAPER", "shops": ["ScrewPress"], "inputs": 0},
                       "scroll": {"code": "MAKE_SCROLL", "shops": ["Craftsdwarfs"]},
                       "codex": {"code": "BIND_BOOK", "shops": ["Craftsdwarfs"]}},
         "quires_blank": 0, "quires_written": 9, "scrolls_blank": 0, "scrolls_written": 0, "codices": 11,
         "rollers": 0, "bindings": 0, "sheets": sheets, "thread": 100,
         "sheets_in_shops": stuck, "sheet_piles": piles}
    if stuck:
        p.update(sheets_shop=shop, sheets_shop_id=PRESS_ID)
    s["paper"] = p
    s["orders"] = [o for o in s["orders"] if o.get("recipe") not in PP.PAPER_RECIPES + PP.KILN_PAPER]
    return digest.normalize(s)


def run_paper(s):
    props, notes = [], []
    PP._paper_rule(s, CFG, props, notes, Memory())
    return props, notes


# --- the brain ------------------------------------------------------------------------------

@test("sheets_usable: the sheets held by a workshop don't count; sheet_stall says where and why")
def _():
    s = fort(sheets=5, stuck=2)
    assert PP.sheets_usable(s) == 3
    why = PP.sheet_stall(s)
    assert "2 sheet(s)" in why and "the screw press" in why and "no stockpile takes sheets" in why, why
    s = fort(sheets=5, stuck=2, piles=1)
    assert "waiting to be hauled to the sheet pile" in PP.sheet_stall(s)
    s = fort(sheets=4, stuck=0)
    assert PP.sheets_usable(s) == 4 and PP.sheet_stall(s) is None
    s = fort(sheets=2, stuck=2)
    del s["paper"]
    assert PP.sheets_usable(s) == 2 and PP.sheet_stall(s) is None      # an older bridge: as before


@test("rule paper_pile: sheets in the screw press, no sheet pile: a feeder pile beside the press")
def _():
    s = fort(sheets=2, stuck=2)
    props, notes = run_paper(s)
    piles = [p for p in props if p.rule == "paper_pile"]
    assert len(piles) == 1, [(p.rule, p.action) for p in props]
    assert piles[0].action == {"type": "feeder_pile", "building_id": PRESS_ID}
    assert "screw press" in piles[0].reason and "no stockpile takes sheets" in piles[0].reason
    # the library's quires wait for them: said, no more paper made meanwhile
    assert not [p for p in props if p.rule == "paper"], [(p.rule, p.action) for p in props]
    assert any("sit in the screw press" in n for n in notes), notes


@test("rule paper_pile: not with a sheet pile, nor when the feeder survey has one or no room beside the press")
def _():
    assert not [p for p in run_paper(fort(sheets=2, stuck=2, piles=1))[0] if p.rule == "paper_pile"]
    s = fort(sheets=2, stuck=2)
    s["logistics"] = {"feeders": [{"id": PRESS_ID, "kind": "ScrewPress", "has": True}]}
    assert not [p for p in run_paper(s)[0] if p.rule == "paper_pile"]
    s["logistics"] = {"feeders": [{"id": PRESS_ID, "kind": "ScrewPress", "has": False, "room": False}]}
    props, notes = run_paper(s)
    assert not [p for p in props if p.rule == "paper_pile"] and any("no room beside it" in n for n in notes), notes


@test("rule paper_pile: a parchment sheet left at the tanner's gets the pile there too (any workshop holding sheets)")
def _():
    s = fort(sheets=1, stuck=1, shop="Tanners")
    p = [x for x in run_paper(s)[0] if x.rule == "paper_pile"]
    assert p and "tanner's shop" in p[0].reason, [x.reason for x in p]


@test("the kiln rule: make_quire sized by the reachable sheets; none reachable: said, no order")
def _():
    s = fort(sheets=5, stuck=2)
    s["supplies"]["gypsum"] = 1         # the kiln rule runs only with the supplies' kiln fields
    props, notes = [], []
    _kiln_rules(s, CFG, props, notes)
    q = [p for p in props if p.action.get("recipe") == "make_quire"]
    assert q and q[0].action["amount"] == 3, [(p.rule, p.action) for p in props]
    s = fort(sheets=2, stuck=2)
    s["supplies"]["gypsum"] = 1
    props, notes = [], []
    _kiln_rules(s, CFG, props, notes)
    assert not [p for p in props if p.action.get("recipe") == "make_quire"], [p.action for p in props]
    assert any("quires wait" in n and "screw press" in n for n in notes), notes


@test("a stuck make_quire order's cancel says the sheets sit in the press; another recipe's doesn't")
def _():
    for recipe, hint in (("make_quire", True), ("stone_blocks", False)):
        s = fort(sheets=2, stuck=2)
        s["orders"] = [{"id": 1312, "recipe": recipe, "job": "CustomReaction", "amount_left": 2, "amount_total": 5,
                        "repeats": False, "by_ai": True, "validated": True, "active": True}]
        m = Memory()
        since = abs_tick(s) - (CFG["order_stuck_you_days"] + 1) * TICKS_PER_DAY
        m.order_watch = {"1312": {"what": recipe, "left": 2, "since": since, "by_ai": True}}
        p = []
        _stuck_orders_rule(s, m, CFG, p)
        assert p and p[0].action["order_id"] == 1312, [x.reason for x in p]
        assert ("no stockpile takes sheets" in p[0].reason) == hint, p[0].reason


@test("the feeder rule doesn't ask again for a workshop the paper rule asked a pile for")
def _():
    s = fort()
    s["date"]["year"] = max(int(s["date"].get("year") or 0), 5)
    s["logistics"] = {"feeders": [{"id": PRESS_ID, "kind": "ScrewPress", "what": "paper sheets", "has": False,
                                   "room": True, "x": 1, "y": 2}]}
    props = [Proposal("paper_pile", {"type": "feeder_pile", "building_id": PRESS_ID}, "x", 6)]
    _feeder_rule(s, CFG, props)
    assert len(props) == 1, [(p.rule, p.action) for p in props]
    props = []
    _feeder_rule(s, CFG, props)
    assert [p.action for p in props] == [{"type": "feeder_pile", "building_id": PRESS_ID}], props


@test("paper_pile is classified with the feeder rule (hold classes) and has a theme")
def _():
    src = (ROOT / "brain" / "hold_classes.py").read_text(encoding="utf-8")
    assert '"feeder", "paper_pile"' in src
    from planner_core import AGENDA_THEMES
    assert AGENDA_THEMES.get("paper_pile")


# --- the bridge -----------------------------------------------------------------------------

@test("ai-builder-rooms: the screw press's feeder is a sheet pile (S); place_feeder takes a workshop holding sheets")
def _():
    src = module_src("ai-builder-rooms.lua")
    assert code_has(src, "ScrewPress = {key = 'S', flag = 'sheet', what = 'paper sheets'},")
    assert code_has(src, "SHEET_FEEDER = {key = 'S', flag = 'sheet', what = 'paper sheets'}")
    assert code_has(src, "if not f and b and holds_sheets(b) then f = SHEET_FEEDER end")
    assert code_has(src, "if n == 'Custom' then n = workshop_name(b) end")
    assert code_has(src, "sheet = {'SHEET'},")


@test("ai-paper: the report says where the sheets lie (sheets_held)")
def _():
    src = module_src("ai-paper.lua")
    assert code_has(src, "pcall(function() sheets_held(out) end)")
    assert "sp.settings.flags.sheet" in src and "SHEET_USERS = {Craftsdwarfs = true}" in src


@test("DF 53's names: the stockpile group 'sheet' with paper and parchment; Quickfort S is Sheets")
def _():
    names = json.loads((ROOT / "tests" / "fixtures" / "df-names.json").read_text(encoding="utf-8"))["types"]
    assert "sheet" in names["stockpile_group_set"]["v"]
    assert set(names["stockpile_parameter_sheetst"]["f"]) == {"paper", "parchment"}
    assert names["stockpile_settings"]["f"]["sheet"] == "stockpile_parameter_sheetst"


@test("the Lua files stay under 60 KB")
def _():
    for name in ("ai-paper.lua", "ai-builder-rooms.lua"):
        assert (LUA / name).stat().st_size < 60_000, name
    assert (ROOT / "brain" / "planner.py").stat().st_size < 92_000


@test("ai-paper (lua): sheets held by the screw press counted, the craftsdwarf's not; sheet piles counted")
def _():
    need_lua()
    import test_paper as TP
    lua, env, g = TP.game()
    lua.execute("""
        local env, G = ...
        local press = {id = 1155, type = 14, custom_type = 99, getType = function() return 1 end}
        local crafts = {id = 7, type = 13, getType = function() return 1 end}
        local held = {}
        env.dfhack.items.getHolderBuilding = function(it) return held[it] end
        held[G.item('SHEET', 3, 1)] = press
        held[G.item('SHEET', 3, 1)] = press
        held[G.item('SHEET', 3, 1)] = crafts
        G.item('SHEET', 3, 1)
        held[G.item('SHEET', 3, 1, {flags = {in_job = true}})] = press
        env.df.global.world.buildings = {other = {STOCKPILE = {
            {settings = {flags = {sheet = false}}}, {settings = {flags = {finished_goods = true}}}}}}
    """, env, g)
    q = lua.execute("local env, G = ...; return env.report()", env, g)
    assert q["sheets"] == 4 and q["sheets_in_shops"] == 2, (q["sheets"], q["sheets_in_shops"])
    assert q["sheets_shop"] == "ScrewPress" and q["sheets_shop_id"] == 1155 and q["sheet_piles"] == 0
    lua.execute("local env, G = ...; env.df.global.world.buildings.other.STOCKPILE[1].settings.flags.sheet = true",
                env, g)
    assert lua.execute("local env, G = ...; return env.report()", env, g)["sheet_piles"] == 1


finish()
