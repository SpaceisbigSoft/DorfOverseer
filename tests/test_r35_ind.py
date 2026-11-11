"""(0.105.35, ind) Nothing waits for the player, in planner_industry,
planner_trade and planner_labor: the supply and hospital shortages, the
forbidden items of no game reason, the pastures, the mandates' footwear and
the underground depot's wagons are notes of what the AI does; nobody able to
dig gets a pick forged; the one Needs you kept (the trade screen the AI
can't open) says what the AI does meanwhile. Fake reports, no Lua.

    python tests/test_r35_ind.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import Memory, plan, PLANNER_CONFIG  # noqa: E402
from planner_core import NEEDS_YOU  # noqa: E402
import planner_industry  # noqa: E402
import planner_labor  # noqa: E402
import planner_trade  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
SRC = {m: Path(m.__file__).read_text(encoding="utf-8") for m in (planner_industry, planner_labor, planner_trade)}


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def you(notes):
    return [n for n in notes if n.startswith(NEEDS_YOU)]


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


@test("sources: one ask_player left in the three files (the trade screen), no 'yourself', no Rules-tab errand")
def _():
    n = sum(src.count("ask_player(") for src in SRC.values())
    assert n == 1 and "ask_player(" in SRC[planner_trade], n
    for m, src in SRC.items():
        assert "NEEDS_YOU +" not in src, m.__name__
        assert "yourself" not in src.replace("you set yourself", ""), m.__name__
        assert "in the Rules tab" not in src, m.__name__


@test("containers: no wood or stone to make them -> a note of what the AI does, no Needs you")
def _():
    s = fort()
    s["supplies"].update(empty_barrels=0, empty_pots=0)
    s["stocks"].update(wood=0, boulders=0)
    p, notes = plan(s, Memory())
    assert not by_rule(p, "containers"), p
    n = [x for x in notes if "too little wood or stone" in x]
    assert n and "the AI makes them as soon as there is" in n[0] and not n[0].startswith(NEEDS_YOU), notes


@test("hospital: no wood for splints, no soap, no thread while patients wait -> notes, never a Needs you")
def _():
    s = fort()
    s["orders"] = []
    s["stocks"].update(wood=0, thread=0, cloth=0)
    s["dwarves"]["needs_medical_care"] = 2
    s["supplies"].update(thread_plants=0, shearable=0, soap=0, tallow=0, fat=0, ash=0, lye=0, splints=0)
    s["health"] = {"patients": [{"id": 1, "needs": ["suture", "immobilize"]}], "infected": 2}
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1}
    p, notes = plan(s, Memory())
    hosp = [n for n in notes if "hospital" in n or "sutures" in n or "soap" in n]
    assert any("no wood to make them" in n and "the AI makes them" in n for n in hosp), notes
    assert any("wait for sutures" in n for n in hosp), notes
    assert any("no soap for the hospital" in n and "buys soap" in n for n in hosp), notes
    # (planner_health's infected-wounds line is another group's)
    assert not [n for n in you(notes) if "no wood to make" in n or "sutures" in n or "soap for the hospital" in n
                or "keeps less than it should" in n or "thread and cloth" in n], you(notes)


@test("forbidden items of no game reason: a note that the AI leaves them (the Rules switch stays the player's)")
def _():
    notes = []
    s = fort()
    rules = dict(planner_industry.player_rules(s))
    rules["disposal_player_items"] = False
    m = Memory()
    s["disposal"] = {"siege": False, "smelters": 0, "dump_zones": []}
    m.census = {"tick": planner_industry.abs_tick(s), "items": {"forbidden": {
        "total": 500, "corpses": {}, "by_reason": {"unknown": 500}, "unknown_reachable": 500,
        "unknown_where": {"surface": 500}}}}
    props = []
    planner_industry._disposal_rules(s, dict(PLANNER_CONFIG), props, notes, m, rules)
    n = [x for x in notes if "500 items lie forbidden" in x]
    assert n and not n[0].startswith(NEEDS_YOU) and "leaves them" in n[0], notes
    assert not any("unknown" in _l for p in props for _l in (p.action.get("reasons") or [])), props


@test("pastures: an older bridge (no grass figures) -> a pasture by a guess; a failure -> a note, tried again")
def _():
    s = fort()
    s["society"] = {"vacant": [], "grazers_unpastured": 4, "pastures": 0}
    m = Memory()
    props, notes = [], []
    planner_industry._pasture_rule(s, m, {}, dict(PLANNER_CONFIG), props, notes)
    assert props and props[0].action == {"type": "make_pasture", "tiles": 100}, props      # 4 x 20 x 1.25
    assert not you(notes), notes
    m.pasture_failure = "no living grass near the fort's surface entrances"
    props, notes = [], []
    planner_industry._pasture_rule(s, m, {}, dict(PLANNER_CONFIG), props, notes)
    assert props and props[0].rule == "new_pasture", props
    assert notes and "tries again" in notes[0] and not you(notes), notes


@test("mandates' footwear short of leather or cloth, or of a kind with no recipe: notes, no Needs you")
def _():
    for sub, st in (("ITEM_SHOES_SOCKS", {"cloth": 0}), ("ITEM_SHOES_BOOTS_LOW", {"leather": 0}),
                    ("ITEM_SHOES_SHOES", {"leather": 0, "cloth": 0}), ("ITEM_SHOES_SANDAL", {})):
        notes = []
        r = planner_industry._shoes_recipe({"subtype": sub, "remaining": 3}, st, notes)
        assert r is None and len(notes) == 1 and not you(notes), (sub, notes)
        assert "yourself" not in notes[0], notes
    notes = []
    assert planner_industry._shoes_recipe({"subtype": "ITEM_SHOES_SOCKS", "remaining": 3}, {"cloth": 5}, notes) \
        == "cloth_socks" and notes == []


@test("nobody can dig, a forge and bars: the AI forges 2 picks itself; none queued twice; no forge: a note")
def _():
    def lab(**kw):
        jobs = {j: {"doing": 0, "candidates": 4, "mode": "OnlySelectedDoesThis"}
                for j in ("mining", "woodcutting", "gathering", "fishing", "farming")}
        lb = {"miners": 0, "picks": 0, "soldier_picks": 1, "dig": 40, "want": 0, "need": 0, "candidates": 4,
              "shrubs": 0, "gather_marked": 0, "fish_water": 0, "jobs": jobs}
        lb.update(kw)
        return lb
    s = fort()
    s["orders"] = []
    s["labor"] = lab()
    s["buildings"]["workshops"]["MetalsmithsForge"] = 1
    s["military"]["gear"] = {"bars": {"COPPER": 1, "IRON": 10}}
    props, notes = [], []
    planner_labor._labor_rules(s, 30, dict(PLANNER_CONFIG), props, notes, Memory())
    pk = by_rule(props, "picks")
    assert pk and pk[0].action == {"type": "work_order", "recipe": "metal_pick", "amount": 2,
                                   "material": "INORGANIC:IRON"}, pk
    assert not you(notes) and not any("nobody can dig" in n for n in notes), notes
    # the industry's own picks order adds none on top in the same cycle
    planner_industry._picks_order(s, dict(PLANNER_CONFIG), props)
    assert len(by_rule(props, "picks")) == 1, by_rule(props, "picks")
    # no forge: a note of what the AI does, no Needs you
    s["buildings"]["workshops"].update(MetalsmithsForge=0, MagmaForge=0)
    props, notes = [], []
    planner_labor._labor_rules(s, 30, dict(PLANNER_CONFIG), props, notes, Memory())
    assert not by_rule(props, "picks"), props
    n = [x for x in notes if "nobody can dig" in x]
    assert n and "forges picks as soon as" in n[0] and "soldiers' hands" in n[0] and not you(notes), notes
    # a pick already being forged: said so
    s["buildings"]["workshops"]["MetalsmithsForge"] = 1
    s["orders"] = [{"job": "MakeTool", "recipe": "metal_pick", "amount_left": 2, "amount_total": 2, "by_ai": True}]
    props, notes = [], []
    planner_labor._labor_rules(s, 30, dict(PLANNER_CONFIG), props, notes, Memory())
    assert planner_industry.queued(s, {"metal_pick"}) == 2
    assert not by_rule(props, "picks") and any("being forged" in n for n in notes), (props, notes)


@test("underground depot the wagons can't reach: notes naming the tile and the pack animals, never a Needs you")
def _():
    def dd(**kw):
        return {"buildings": {"deep_depot": dict({"stage": "placed", "depot": "built", "x": 1, "y": 2,
                                                  "elevation": 3, "wagon_access": False}, **kw)}}
    for kw in ({"dfhack_wagon_access": True}, {"wagon_check": "clear"}, {},
               {"wagon_check": "blocked", "wagon_block": {"text": "rock at x9 y9", "fix": None},
                "opens_fort": {"x": 4, "y": 5, "elevation": 3}}):
        notes, props = [], []
        planner_industry._deep_depot_watch(dd(**kw), notes, props)
        assert len(notes) == 1 and not you(notes) and "pack animals" in notes[0], (kw, notes)
        assert "open the depot's sheet" not in notes[0] and "build a depot" not in notes[0], notes


@test("trade screen the AI can't open: the one Needs you kept, saying why and what the AI does meanwhile")
def _():
    s = fort()
    s["trade"] = {"depot": True, "goods": 0, "at_depot": 12,
                  "caravans": [{"civ": "the Mountainhomes", "state": "AtDepot"}],
                  "trader": {"at_depot": True, "can_open": False}, "screen": {}}
    props, notes = [], []
    planner_trade._trade_rules(s, dict(PLANNER_CONFIG), 30, props, notes, {}, Memory())
    y = [n for n in you(notes) if "trade depot" in n]
    assert y and "can't open" in y[0] and "Meanwhile" in y[0] and "takes them back out" in y[0], notes


if __name__ == "__main__":
    finish()
