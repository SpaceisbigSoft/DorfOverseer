"""(0.105.51, R3 fort B "Monastery") What stressed fort B: eating without a
table, the training squad with nowhere to train, guildhall petitions left to
lapse, arguments in a crowded tavern. Rows from the R3 run's logs
(/home/claude/r3/DF-AI-B/logs, 15 Nov: 254-summer and 255-autumn states).

    python tests/test_k48_fort_b_stress.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG, TICKS_PER_DAY, Memory, abs_tick, plan  # noqa: E402
import planner_building as PB  # noqa: E402
import planner_locations as PL  # noqa: E402
import planner_training as PTR  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort_b(dining=None, causes=None) -> dict:
    """254-summer: 83 dwarves, 37 dining hall zones, 29 tables (6 of them in
    the one public dining hall), Monastery sliders."""
    s = copy.deepcopy(BASE)
    s["dwarves"].update(total=83, adults=81, children=2)
    s["buildings"]["zones"] = {"Bedroom": 96, "DiningHall": 37, "MeetingHall": 66, "Office": 5}
    s["buildings"].setdefault("other", {})["Table"] = 29
    s["buildings"]["other"]["Chair"] = 52
    if dining is not None:
        s["buildings"]["dining"] = dining
    s.setdefault("needs", {})["stress_causes"] = {"days": 28, "causes": causes or []}
    return s


B_DINING = {"hall": 6, "meeting": 4, "owned": 9, "other": 10, "halls": 35, "halls_with_tables": 1,
            "owned_halls": 2}
LACK = [{"thought": "LackTables", "citizens": 60, "children": 3, "stress": 60, "emotion": "ANNOYANCE"}]


# ---- 1. LackTables -----------------------------------------------------------------

@test("dining: B's 29 tables, 6 in the public hall, for 83 dwarves: another hall (was: all 29 counted, none)")
def _():
    dn = PB.dining_shortfall(fort_b(B_DINING), CFG)
    assert dn and dn["have"] == 6 and dn["want"] == 42 and dn["tables"] == 36 and dn["source"] == "public", dn
    # enough public tables (half the fort) and no stress: none
    assert PB.dining_shortfall(fort_b(dict(B_DINING, hall=42)), CFG) is None


@test("dining: an older bridge (no table census): eating without a table makes the halls short")
def _():
    assert PB.dining_shortfall(fort_b(), CFG) is None              # 29 tables >= half of 28: as before
    dn = PB.dining_shortfall(fort_b(causes=LACK), CFG)
    assert dn and dn["lack"] == 60 and dn["source"] == "all" and dn["tables"] == 13, dn
    # a few upset (under lack_tables_min): not on its own
    few = [dict(LACK[0], citizens=CFG["lack_tables_min"] - 1)]
    assert PB.dining_shortfall(fort_b(causes=few), CFG) is None


@test("dining: LackTables with the public halls seating half: one more until three quarters, then none")
def _():
    dn = PB.dining_shortfall(fort_b(dict(B_DINING, hall=45), causes=LACK), CFG)
    assert dn and dn["tables"] == 8, dn                             # 45 < 63 (0.75 of 83)
    assert PB.dining_shortfall(fort_b(dict(B_DINING, hall=63), causes=LACK), CFG) is None


@test("dining: the plan digs another dining hall with tables and chairs, saying why")
def _():
    s = fort_b(B_DINING, LACK)
    s["projects"] = {"open": [], "max_open": 4}
    props, _notes = plan(s, Memory())
    ps = [p for p in props if p.action.get("type") == "start_project" and p.action.get("kind") == "dining"]
    assert ps and ps[0].action["tables"] == 36 and ps[0].action.get("urgent"), [p.action for p in ps]
    assert "6 tables in the dining halls for 83" in ps[0].reason and "60 citizens" in ps[0].reason, ps[0].reason


# ---- 4. arguments: the stop-gap tavern is no tavern of its own ---------------------

def social(locs, friends_badly=49, friends_dist=69, argue=0) -> dict:
    s = fort_b()
    s["locations"] = {"count": {"INN_TAVERN": len(locs)}, "list": locs}
    s["needs"]["needs"] = {"BeWithFriends": {"badly": friends_badly, "distracted": friends_dist, "have": 77}}
    if argue:
        s["needs"]["stress_causes"]["causes"] = [{"thought": "Argument", "citizens": argue}]
    return s


TAVERNS_B = [{"id": 1, "type": "INN_TAVERN", "value": 803, "tier": 0, "zones": [147], "over_dining": True},
             {"id": 2, "type": "INN_TAVERN", "value": 798, "tier": 0, "zones": [203]}]


@test("taverns: B's stop-gap over the dining hall isn't counted: another tavern (was: 2 of 2 wanted, none)")
def _():
    out = dict(PB.social_shortfall(social(TAVERNS_B), CFG))
    assert "tavern" in out and "1 tavern(s) for 83" in out["tavern"] and "stop-gap" in out["tavern"], out
    # two of its own: as before (2 wanted for 49 badly, 69 distracted)
    two = [dict(TAVERNS_B[0], over_dining=None), TAVERNS_B[1]]
    assert "tavern" not in dict(PB.social_shortfall(social(two), CFG))
    # only the stop-gap: counted as one, as before
    only = dict(PB.social_shortfall(social(TAVERNS_B[:1]), CFG))
    assert "1 tavern(s) for 83" in only["tavern"] and "stop-gap" not in only["tavern"], only


@test("taverns: arguments for a quarter of the fort with under one tavern per 40 (+1): another tavern")
def _():
    two = [dict(TAVERNS_B[0], over_dining=None), TAVERNS_B[1]]
    calm = social(two, friends_badly=5, friends_dist=10)
    assert "tavern" not in dict(PB.social_shortfall(calm, CFG))
    out = dict(PB.social_shortfall(social(two, friends_badly=5, friends_dist=10, argue=46), CFG))
    assert "tavern" in out and "46 citizens upset by arguments" in out["tavern"] and "(3 wanted)" in out["tavern"], out
    three = two + [dict(TAVERNS_B[1], id=3)]
    assert "tavern" not in dict(PB.social_shortfall(social(three, friends_badly=5, friends_dist=10, argue=46), CFG))


# ---- 2. the training squad's barracks ----------------------------------------------

def training_fort(barracks=None, zones=None, open_=None) -> dict:
    s = fort_b()
    s["settings"]["traits"] = {"militarism": -60, "welfare": 80}
    s["settings"]["levels"] = {"barracks": False, "archery": False}
    s["dwarves"]["adults"] = 81
    s["military"]["squads"] = []
    s["military"]["training_squads"] = [{"id": 191, "name": "", "members": 10, "size": 10, "leader": True,
                                         "routine": "Staggered training", "orders": 0, "ai_orders": 0,
                                         "training": True, "training_squad": True, "uniform": False}]
    s["military"]["barracks"] = barracks if barracks is not None else []
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    s["buildings"]["zones"] = dict(s["buildings"]["zones"], **(zones or {}))
    s["projects"] = {"open": open_ or [], "max_open": 4}
    s["needs"].update(keen_civilians=28, keen_draftable=0)
    s["others_on_map"] = {}
    return s


def train_rule(s):
    props, notes = [], []
    PTR._training_squad_rule(s, Memory(), CFG, props, notes)
    return props, notes


@test("training: B's squad of 10 with no barracks (the level off): a small training hall (was: nothing)")
def _():
    props, _ = train_rule(training_fort())
    hall = [p.action for p in props if p.action.get("type") == "start_project"]
    assert hall == [{"type": "start_project", "kind": "barracks", "beds": CFG["training_hall_beds"]}], hall
    # one being dug: waits; the slots full: a note
    props, notes = train_rule(training_fort(open_=[{"kind": "barracks", "phase": "dig"}]))
    assert not [p for p in props if p.action.get("type") == "start_project"]
    assert any("training hall (being built)" in n for n in notes), notes
    props, notes = train_rule(training_fort(open_=[{"kind": k} for k in ("a", "b", "c", "d")]))
    assert not [p for p in props if p.action.get("type") == "start_project"]
    assert any("waits for a building slot" in n for n in notes), notes


@test("training: a barracks stands: the training squad is given it; once given, nothing")
def _():
    props, _ = train_rule(training_fort(barracks=[{"id": 900, "squads": [177]}, {"id": 901, "squads": []}],
                                        zones={"Barracks": 2}))
    got = [p.action for p in props if p.action.get("type") == "squad_barracks"]
    assert got == [{"type": "squad_barracks", "squad_id": 191, "zone_id": 901}], got
    props, _ = train_rule(training_fort(barracks=[{"id": 900, "squads": [191]}], zones={"Barracks": 1}))
    assert not [p for p in props if p.action.get("type") in ("squad_barracks", "start_project")]
    # an empty squad needs none
    s = training_fort()
    s["military"]["training_squads"][0]["members"] = 0
    props, _ = train_rule(s)
    assert not [p for p in props if p.action.get("type") in ("squad_barracks", "start_project")]


# ---- 3. guildhall petitions --------------------------------------------------------

GUILDS_B = [{"id": 10, "type": "GUILDHALL", "profession": "FARMER", "tier": 2, "value": 37425},
            {"id": 11, "type": "GUILDHALL", "profession": "CRAFTSMAN", "tier": 2, "value": 13649}]


def petition_fort(pending, agreed, guilds=GUILDS_B) -> dict:
    s = fort_b()
    s["settings"]["traits"] = {"craftsmanship": 40, "industriousness": -20, "trade": -30, "welfare": 80,
                               "militarism": -60, "piety": 150, "grandeur": 60}
    s["petitions"] = {"pending": pending, "agreed": agreed}
    s["locations"] = {"count": {"GUILDHALL": len(guilds)}, "list": guilds}
    s["projects"] = {"open": [], "max_open": 4}
    s["date"]["year"] = 255
    return s


def pet(pid, prof, days, tier=1):
    return {"id": pid, "type": "Location", "loc": "GUILDHALL", "profession": prof, "tier": tier, "days": days,
            "applicant": {"entities": 1}}


def answers(s, memory=None):
    props, notes = [], []
    PL._location_petition_rules(s, CFG, props, notes, {"answer_locations": True, "levels": {}},
                                memory or Memory())
    return [p for p in props if p.rule == "petition_answer"], notes


@test("petitions: asked again for B's farmers' guildhall (agreed, standing at tier 2): agreed (was: left to lapse)")
def _():
    s = petition_fort([pet(2784, "FARMER", 79)], [{"id": 2781, "loc": "GUILDHALL", "profession": "FARMER",
                                                   "tier": 1, "days": 85}])
    mem = Memory()
    mem.wishes_agreed = {"GUILDHALL|FARMER|None|None": abs_tick(s) - 85 * TICKS_PER_DAY}   # agreed 85 days ago
    got, notes = answers(s, mem)
    assert [(p.action["id"], p.action["accept"]) for p in got] == [(2784, True)], [p.action for p in got]
    assert not any("left to lapse" in n for n in notes), notes


@test("petitions: asked again for a hall promised and still being built: agreed, the cap not counted")
def _():
    agreed = [{"id": 2899, "loc": "GUILDHALL", "profession": "MINER", "tier": 1, "days": 28}]
    got, _ = answers(petition_fort([pet(2907, "MINER", 9)], agreed))
    assert [(p.action["id"], p.action["accept"]) for p in got] == [(2907, True)], [p.action for p in got]
    assert "already promised" in got[0].reason


@test("petitions: another hall while one promised is unbuilt: waits, then agreed late, then declined (never ignored)")
def _():
    agreed = [{"id": 2557, "loc": "GUILDHALL", "profession": "CRAFTSMAN", "tier": 1, "days": 36}]
    no_hall = GUILDS_B[:1]
    got, _ = answers(petition_fort([pet(2562, "MINER", 24)], agreed, no_hall))
    assert got == [], [p.action for p in got]                        # waits for the slot
    late = CFG["location_petition_late_days"]
    got, _ = answers(petition_fort([pet(2562, "MINER", late)], agreed, no_hall))
    assert [(p.action["id"], p.action["accept"]) for p in got] == [(2562, True)], [p.action for p in got]
    two = agreed + [{"id": 2600, "loc": "GUILDHALL", "profession": "MASON", "tier": 1, "days": 20}]
    got, _ = answers(petition_fort([pet(2562, "MINER", late)], two, no_hall))
    assert [(p.action["id"], p.action["accept"]) for p in got] == [(2562, False)], [p.action for p in got]


@test("petitions: a hall the fort has at the asked tier is agreed even while another promised one is unbuilt")
def _():
    agreed = [{"id": 2557, "loc": "GUILDHALL", "profession": "MINER", "tier": 1, "days": 36}]
    got, _ = answers(petition_fort([pet(2569, "CRAFTSMAN", 14)], agreed))
    assert [(p.action["id"], p.action["accept"]) for p in got] == [(2569, True)], [p.action for p in got]


# ---- the bridge's table census -----------------------------------------------------

@test("bridge: get_buildings counts the tables by where they stand (public hall, tavern, owned, other) once each")
def _():
    if LuaRuntime is None:
        skip("needs lupa")
        return
    hyg = (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8")
    harness = re.search(r'HARNESS = r"""(.*?)"""', hyg, re.S).group(1)
    hub = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    L = LuaRuntime(unpack_returned_tuples=True)
    H = L.execute(harness, hub, str(ROOT / "lua"))
    H.scripts = L.table()
    M = H.module()
    setup = L.eval(r"""function(H, M)
      local df, dfhack = H.df, H.dfhack
      df.building_type = {Stockpile = 1, Civzone = 2, Workshop = 3, Furnace = 4, Table = 5, Chair = 6, Trap = 7}
      df.building_type[5] = 'Table'
      df.civzone_type = {[0] = 'DiningHall', [1] = 'MeetingHall', [2] = 'Office', DiningHall = 0}
      local function zone(id, typ, owner) return {id = id, type = typ, assigned_unit_id = owner or -1,
        getType = function() return 2 end} end
      local function tbl(x) return {x1 = x, y1 = 0, z = 0, getType = function() return 5 end,
        getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end} end
      local hall, noble, tav, office, hall2 = zone(1, 0), zone(2, 0, 77), zone(3, 1), zone(4, 2, 78), zone(5, 0)
      local at = {[1] = {hall}, [2] = {hall}, [3] = {noble}, [4] = {tav, hall}, [5] = {office}, [6] = {}}
      df.global.world.buildings = {all = {hall, noble, tav, office, hall2, tbl(1), tbl(2), tbl(3), tbl(4), tbl(5), tbl(6)}}
      dfhack.buildings = {findCivzonesAt = function(p) return at[p.x] end}
      M.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      H.scripts['ai-builder'] = {}
    end""")
    setup(H, M)
    b = M.get_buildings()
    d = b.dining
    got = {k: d[k] for k in ("hall", "meeting", "owned", "other", "halls", "halls_with_tables", "owned_halls")}
    assert got == {"hall": 3, "meeting": 0, "owned": 2, "other": 1, "halls": 2, "halls_with_tables": 1,
                   "owned_halls": 1}, got
    assert b.other.Table == 6


if __name__ == "__main__":
    finish()
