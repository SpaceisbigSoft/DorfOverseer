"""(0.105.26, fix round: orders) Moods and work orders, drink, searches cut
short, the ghosts' tombs and slabs, the prison cooldown, levels nobody
reached, and the tanner's recipe.

    python tests/test_fix26_orders.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish, code_has  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import (PLANNER_CONFIG, Memory, Proposal, plan, record, select, abs_tick,  # noqa: E402
                     TICKS_PER_DAY)

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TPD = TICKS_PER_DAY


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def wo(rule, recipe, material=None, amount=2, priority=4):
    a = {"type": "work_order", "recipe": recipe, "amount": amount}
    if material:
        a["material"] = material
    return Proposal(rule, a, "x", priority, True)


def mood_state(*missing):
    s = fort()
    s["moods"] = {"list": [{"unit_id": 7, "name": "Urist", "mood": "Fey", "craft": True, "skill": "CLOTHESMAKING",
                            "workshop": True, "missing": list(missing)}]}
    return s


CLOTH = {"item": "CLOTH", "quantity": 2, "flags": [], "avail": {"reach": 0, "free": 0, "job": 1, "enough": False}}
LEATHER = {"item": "SKIN_TANNED", "quantity": 1, "flags": [], "avail": {"reach": 0, "free": 0, "job": 1}}
BAR = {"item": "BAR", "quantity": 1, "material": "iron", "flags": ["metal"], "avail": {"reach": 0, "free": 0, "job": 1}}
CFG = dict(PLANNER_CONFIG, max_actions_per_cycle=50)


# --- 1. tanning is a reaction --------------------------------------------------------------------

@test("1 tan_hide: a CustomReaction TAN_A_HIDE (TanAHide is no job)")
def _():
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert code_has(src, "tan_hide = {job = 'CustomReaction', reaction = 'TAN_A_HIDE'}"), "tan_hide recipe"
    assert "TanAHide" not in src


# --- 2. a mood's own orders are never held --------------------------------------------------------

@test("2 mood orders: not held by a stuck cancel (no fallback swapped in), a stalled order or the daily limit")
def _():
    s = fort()
    now = abs_tick(s)
    m = Memory()
    m.stuck_cancelled = {"weave_plant_cloth": {"tick": now - TPD, "n": 1},
                         "cloth_bag": {"tick": now - TPD, "n": 1}}
    a, h = select([wo("mood", "weave_plant_cloth", amount=1, priority=1)], s, m, CFG)
    assert a and a[0].action["recipe"] == "weave_plant_cloth", h
    a, h = select([wo("mood", "cloth_bag", amount=1, priority=1)], s, m, CFG)
    assert a and a[0].action["recipe"] == "cloth_bag", (h, [p.action for p in a])   # not silk_bag
    a, h = select([wo("bags", "cloth_bag")], s, m, CFG)
    assert not a or a[0].action["recipe"] != "cloth_bag", "another rule's stuck order is still held"
    m = Memory()
    m.order_watch = {"9": {"by_ai": True, "what": "tan_hide", "since": now - 20 * TPD, "left": 1}}
    a, h = select([wo("mood", "tan_hide", amount=1, priority=1)], s, m, CFG)
    assert a, h
    a, h = select([wo("leather", "tan_hide")], s, m, CFG)
    assert not a and "hasn't moved" in h[0], h
    m = Memory()
    from planner import game_day
    m.orders_by_day[str(game_day(s))] = CFG["max_orders_per_game_day"]
    a, h = select([wo("mood", "tan_hide", amount=1, priority=1), wo("crafts", "stone_crafts")], s, m, CFG)
    assert [p.rule for p in a] == ["mood"], h
    assert any("work-order limit" in x for x in h), h


# --- 3. other rules don't re-order what a mood waits for -------------------------------------------

@test("3 a waiting mood's materials: bags, quivers, shoes, jewellery, metal crafts held; the mood's own go")
def _():
    s = mood_state(CLOTH, LEATHER, BAR)
    props = [wo("bags", "cloth_bag"), wo("bags", "yarn_bag"), wo("quivers_order", "leather_quiver"),
             wo("arms", "leather_quiver"), wo("stress_care", "cloth_shoes"), wo("stress_care", "leather_shoes"),
             wo("needs_finery", "metal_ring", "INORGANIC:COPPER"), wo("crafts", "metal_crafts"),
             wo("weapons", "metal_spear", "INORGANIC:IRON"), wo("mood", "tan_hide", priority=1),
             wo("crafts", "stone_crafts")]
    a, h = select(props, s, Memory(), CFG)
    got = [(p.rule, p.action["recipe"]) for p in a]
    assert ("mood", "tan_hide") in got and ("crafts", "stone_crafts") in got, (got, h)
    held = [p for p in got if p not in (("mood", "tan_hide"), ("crafts", "stone_crafts"))]
    assert not held, held
    assert any("strange mood waits for" in x and "cloth_bag" in x for x in h), h
    # a silk cloth request holds only silk bags; enough within reach holds nothing
    silk = dict(CLOTH, flags=["silk"])
    a, _h = select([wo("bags", "cloth_bag"), wo("bags2", "silk_bag")], mood_state(silk), Memory(), CFG)
    assert [p.action["recipe"] for p in a] == ["cloth_bag"], [p.action for p in a]
    here = dict(CLOTH, avail={"reach": 5, "enough": True})
    a, _h = select([wo("bags", "cloth_bag")], mood_state(here), Memory(), CFG)
    assert a
    # a weaver's mood waiting for thread: the cloth rule's weaving waits
    thread = {"item": "THREAD", "quantity": 1, "flags": ["plant"], "avail": {"reach": 0}}
    a, _h = select([wo("cloth", "weave_plant_cloth"), wo("cloth2", "weave_yarn_cloth")], mood_state(thread),
                   Memory(), CFG)
    assert [p.action["recipe"] for p in a] == ["weave_yarn_cloth"], [p.action for p in a]


# --- 4. a search cut short is tried again soon ----------------------------------------------------

@test("4 timed-out searches: again in 1-2 days, no failure in Needs you; after 3 in a row the back-off")
def _():
    s = fort()
    now = abs_tick(s)
    m = Memory()
    p = Proposal("well", {"type": "place_well"}, "x", 3)
    cut = {"ok": False, "error": "no safe spot found within the time limit", "timed_out": True}
    record([(p, cut)], s, m)
    assert m.well_failure == "", m.well_failure
    r = list(m.refusals.values())[0]
    assert r["n"] == 0 and r["until"] - now <= 2 * TPD and r["t"] == 1, r
    cd = PLANNER_CONFIG["well_cooldown_ticks"]
    assert now - m.last_fired["well"] >= cd - TPD, "the well rule's wait is a day"
    record([(p, cut)], s, m)
    assert m.well_failure == "" and list(m.refusals.values())[0]["t"] == 2
    record([(p, cut)], s, m)
    r = list(m.refusals.values())[0]
    assert m.well_failure and r["n"] == 1 and r["t"] == 3, (m.well_failure, r)
    record([(p, cut)], s, m)
    assert list(m.refusals.values())[0]["n"] == 2, "the back-off grows"
    # a plain refusal ends the streak
    record([(p, {"ok": False, "error": "no water"})], s, m)
    assert "t" not in list(m.refusals.values())[0]
    # farms, pastures and the first stair likewise
    for a, field in (({"type": "farm_plots", "dig": True}, "farm_failure"), ({"type": "make_pasture"}, "pasture_failure"),
                     ({"type": "found_fort"}, "found_failure")):
        m = Memory()
        record([(Proposal("x", a, "x", 3), cut)], s, m)
        assert getattr(m, field) == "", field
        assert list(m.refusals.values())[0]["until"] - now <= 2 * TPD, field
    m = Memory()
    record([(Proposal("farms", {"type": "farm_plots", "dig": True}, "x", 3), cut)], s, m)
    assert now - m.farm_failure_tick >= (PLANNER_CONFIG["farm_dig_retry_days"] - 1) * TPD


# --- 5./6./7. drink ---------------------------------------------------------------------------------

def same_booze():
    s = fort()
    s.setdefault("needs", {})["stress_causes"] = {"causes": [{"thought": "SameBooze", "citizens": 40}]}
    s["stocks"]["drink"] = 10
    s["supplies"].update(drink_kinds=1, brewable_growths=200, brewable_plants=0, empty_barrels=12, empty_pots=0)
    s["orders"] = []
    return s


@test("5 booze variety: no second fruit brew beside the drink rule's; open brew jobs take its barrels")
def _():
    s = same_booze()
    props = plan(s, Memory())[0]
    fruit = [p for p in props if p.action.get("recipe") == "brew_drink_from_fruit"]
    assert [p.rule for p in fruit] == ["drink"], [(p.rule, p.action) for p in fruit]
    a, _h = select(props, s, Memory())
    n = sum(p.action["amount"] for p in a if p.action.get("recipe") in ("brew_drink", "brew_drink_from_fruit"))
    assert n <= 12, n
    # drink plentiful (the drink rule quiet): booze variety brews, less the open plant brews' jobs
    s["stocks"]["drink"] = 100000
    s["orders"] = [{"id": 5, "recipe": "brew_drink", "by_ai": True, "amount_left": 10, "amount_total": 10}]
    bv = by_rule(plan(copy.deepcopy(s), Memory())[0], "booze_variety")
    bf = [p for p in bv if p.action.get("recipe") == "brew_drink_from_fruit"]
    assert bf and bf[0].action["amount"] <= 2, [p.action for p in bv]
    s["orders"][0]["amount_left"] = 12
    bv = by_rule(plan(copy.deepcopy(s), Memory())[0], "booze_variety")
    assert not [p for p in bv if p.action.get("recipe") == "brew_drink_from_fruit"], [p.action for p in bv]


@test("6 drink: a stuck brew source waits days, not 28; none when urgent; the note says nothing is ordered")
def _():
    s = fort()
    s["stocks"]["drink"] = 500                      # short of the target, not urgent
    s["orders"] = []
    s["supplies"].update(brewable_plants=0, brewable_growths=30)
    now = abs_tick(s)
    m = Memory()
    m.stuck_cancelled = {"brew_drink_from_fruit": {"tick": now - 8 * TPD}}
    assert by_rule(plan(copy.deepcopy(s), m)[0], "drink"), "8 days on: brewed again"
    m.stuck_cancelled = {"brew_drink_from_fruit": {"tick": now - TPD}}
    props, notes = plan(copy.deepcopy(s), m)
    assert not by_rule(props, "drink")
    note = [n for n in notes if n.startswith("drink ")]
    assert note and "nothing is brewing" in note[0] and "got stuck" in note[0], note
    assert not any("work through the brew orders there are" in n for n in notes), notes
    s["stocks"]["drink"] = 0                        # urgent: no wait at all
    assert by_rule(plan(copy.deepcopy(s), m)[0], "drink")


@test("7 needs_drink is gone: no rule, no cooldown key, no label")
def _():
    import planner_core
    s = fort()
    s["orders"] = []
    s["stocks"]["drink"] = 600
    s["settings"]["traits"] = {"stockpile": -100}
    s["supplies"].update(brewable_plants=30, brewable_growths=0, empty_barrels=17)
    s.setdefault("needs", {}).setdefault("needs", {})["DrinkAlcohol"] = {"distracted": 40, "badly": 10}
    assert not by_rule(plan(s, Memory())[0], "needs_drink")
    assert "needs_drink_cooldown_ticks" not in PLANNER_CONFIG
    assert "needs_drink" not in planner_core.STEER_PROTECTED
    for p in (ROOT / "brain").glob("*.py"):
        assert '"needs_drink"' not in p.read_text(encoding="utf-8"), p.name


# --- 8./9. tombs for ghosts once; the prison's cooldown --------------------------------------------

@test("8 tombs_ghosts is proposed in one place")
def _():
    src = (ROOT / "brain" / "planner_building.py").read_text(encoding="utf-8")
    assert src.count('Proposal("tombs_ghosts"') == 1, src.count('Proposal("tombs_ghosts"')


@test("9 prisoners: the rule waits its own 7-day cooldown (prisoner_room_cooldown_ticks)")
def _():
    s = fort()
    m = Memory()
    m.last_fired["prisoners"] = abs_tick(s) - 3 * TPD
    a, h = select([Proposal("prisoners", {"type": "prisoner_room"}, "x", 3)], s, m)
    assert not a and "cooldown" in h[0], h
    m.last_fired["prisoners"] = abs_tick(s) - 8 * TPD
    assert select([Proposal("prisoners", {"type": "prisoner_room"}, "x", 3)], s, m)[0]


# --- 10. levels nobody reached ----------------------------------------------------------------------

@test("10 unreached: only a level nothing was dug on; a slow cavern well stays revivable")
def _():
    s = fort()
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1}, "total": 3}
    now = s["date"]
    old = {"year": now["year"] - 2, "tick": now["tick"]}
    s["projects"] = {"max_open": 2, "open": [
        {"id": 25, "kind": "well", "phase": "dig", "started": old, "summary": {"cavern": True},
         "dig": {"dug": 2, "total": 24, "digging": 1}},
        {"id": 26, "kind": "bedrooms", "phase": "dig", "started": old, "dig": {"dug": 3, "total": 90}},
        {"id": 27, "kind": "tombs", "phase": "dig", "started": old, "dig": {"dug": 0, "total": 40}}]}
    acts = {p.action["project_id"]: p.action for p in by_rule(plan(s, Memory())[0], "project")
            if p.action.get("type") == "cancel_project"}
    assert acts[25] == {"type": "cancel_project", "project_id": 25, "cavern_well": True}, acts
    assert "unreached" not in acts[26] and acts[27].get("unreached") is True, acts


def _lua_fn(name: str) -> str:
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    m = re.search(r"\nfunction " + name + r"\(.*?\nend\n", src, re.S)
    assert m, f"{name} not in ai-builder-projects.lua"
    return m.group(0)


@test("10 unreached (lua): a given-up level's stair column is dropped at every level unless a citizen reaches it")
def _():
    try:
        from lupa.lua53 import LuaRuntime
    except ImportError:
        return
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert code_has(src, "stairs = unreached_stairs_dropped(stairs, banned)")
    L = LuaRuntime()
    L.execute("""
        GROUPS = {}
        function xyz2pos(x, y, z) return {x = x, y = y, z = z} end
        dfhack = {maps = {getWalkableGroup = function(p) return GROUPS[p.x .. ',' .. p.y .. ',' .. p.z] or 0 end}}
        function citizen_positions() return {{x = 1, y = 1, z = 10}} end
    """ + _lua_fn("unreached_stairs_dropped"))
    L.execute("""
        GROUPS['1,1,10'] = 5; GROUPS['50,50,3'] = 9; GROUPS['60,60,8'] = 5
        local stairs = {{x = 50, y = 50, z_top = 4, z_bottom = 2}, {x = 60, y = 60, z_top = 9, z_bottom = 7},
                        {x = 70, y = 70, z_top = 9, z_bottom = 7}}
        local banned = {[50 * 100000 + 50] = true, [60 * 100000 + 60] = true}
        local kept = unreached_stairs_dropped(stairs, banned)
        R1 = #kept .. ':' .. kept[1].x .. ':' .. kept[2].x
        dfhack.maps.getWalkableGroup = function() error('no map') end
        R2 = #unreached_stairs_dropped(stairs, banned)
    """)
    assert L.eval("R1") == "2:60:70", L.eval("R1")   # 50 unreachable (group 9): dropped; 60 reached: kept
    assert L.eval("R2") == 1, L.eval("R2")           # groups unknown: banned stairs count as not reached


# --- 11. the ghosts' slab or coffin that can't be made ----------------------------------------------

@test("11 ghosts: a slab or coffin that can't be made is said in Needs you, with why")
def _():
    s = fort()
    s["dead"] = {"ghosts": 3, "ghost_names": ["A"], "free_tombs": 2, "unburied": 0}
    s["supplies"]["slabs"] = 0
    s["supplies"]["memorial_slabs"] = 0
    s["tools"] = dict(s.get("tools") or {}, autoslab=True)
    s["stone_use"] = {"usable": 0, "economic": {}}
    notes = plan(copy.deepcopy(s), Memory())[1]
    you = [n for n in notes if n.startswith("[you] ") and "ghost" in n and "can't be made" in n]
    assert you and "stone" in you[0], [n for n in notes if "ghost" in n]
    # stone enough, but the game refused the slabs
    s["stone_use"] = {"usable": 30, "economic": {}}
    m = Memory()
    m.refusals = {'slabs:{"recipe": "stone_slab", "type": "work_order"}': {
        "n": 2, "until": abs_tick(s) + 3 * TPD, "at": abs_tick(s), "why": "no mason may use the stone"}}
    notes = plan(copy.deepcopy(s), m)[1]
    you = [n for n in notes if n.startswith("[you] ") and "can't be made" in n]
    assert you and "refused" in you[0] and "no mason may use" in you[0], you
    # no mason's workshop
    s2 = copy.deepcopy(s)
    for k in list(s2["buildings"]["workshops"]):
        if k.startswith("Mason"):
            del s2["buildings"]["workshops"][k]
    notes = plan(s2, Memory())[1]
    assert any(n.startswith("[you] ") and "no mason's workshop" in n for n in notes), \
        [n for n in notes if "ghost" in n]
    # a coffin a tomb level waits for, with no stone and no wood
    s3 = copy.deepcopy(s)
    s3["tools"]["autoslab"] = None
    s3["stone_use"] = {"usable": 0, "economic": {}}
    s3["stocks"]["wood"] = 0
    s3["projects"] = {"max_open": 2, "open": [{"id": 4, "kind": "tombs", "phase": "furnish",
                                               "furnish": {"waiting": {"Coffin": 4}}}]}
    notes = plan(s3, Memory())[1]
    assert any(n.startswith("[you] ") and "coffins" in n and "no stone or wood" in n for n in notes), \
        [n for n in notes if "ghost" in n]
    # nothing in the way: no such note
    ok = copy.deepcopy(s)
    ok["supplies"]["slabs"] = 5
    assert not any("can't be made" in n for n in plan(ok, Memory())[1])


if __name__ == "__main__":
    finish()
