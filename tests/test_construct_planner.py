"""Tests for the construction round's brain rules (0.105.30, group G4):
brain/planner_construct.py (the surface hall, blocks for building, wing
walls, the Hermit's cavern walls, soil floors) and their hooks in planner,
planner_industry (the keep), planner_gates and planner_building.

    python tests/test_construct_planner.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
import planner_construct as pc  # noqa: E402
from planner import Memory, plan, record, select, note_cycle  # noqa: E402
from planner_core import (PLANNER_CONFIG, Proposal, TICKS_PER_DAY, abs_tick, refusal_key,  # noqa: E402
                          _refused_wait)
from planner_gates import _gate_rules  # noqa: E402
from planner_core import player_rules  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
GARDEN = {"agriculture": 120, "husbandry": 80, "surface": 80, "welfare": 40, "grandeur": 40}
MERCHANT = {"trade": 120, "greed": 80, "outsiders": 100, "craftsmanship": 60, "stockpile": 40,
            "growth": 60, "surface": 40, "deference": 40}
WAR = {"militarism": 150, "fortification": 120, "caution": 60, "engineering": 60, "outsiders": -80,
       "grandeur": -40}
HERMIT = {"outsiders": -150, "trade": -100, "growth": -60, "caution": 60, "surface": -60, "fortification": 100}
MONASTERY = {"piety": 150, "welfare": 80, "outsiders": 60, "grandeur": 60, "craftsmanship": 40}
DEEP = {"mining": 150, "verticality": 120, "surface": -100, "engineering": 60}
CONSTRUCT_TYPES = {"place_hall", "build_wings", "floor_rooms"}


def fort(traits=None, **over) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits or {})
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["stocks"]["blocks"] = 400
    s.update(over)
    return s


def keep_refused(m: Memory, n: int = 3) -> Memory:
    m.refusals[refusal_key(Proposal("keep", {"type": "place_keep"}, "", 7))] = {"n": n, "until": 0, "at": 0}
    return m


def hall_props(ps):
    return [p for p in ps if p.action.get("type") == "place_hall"]


def run(s, m=None, traits=None):
    m = m if m is not None else Memory()
    traits = traits if traits is not None else s["settings"]["traits"]
    ps, notes = [], []
    pc._hall_rule(s, CFG, s["dwarves"]["total"], traits, ps, notes, m)
    return ps, notes


def construct_actions(ps) -> list:
    return [p.action for p in ps if p.action.get("type") in CONSTRUCT_TYPES
            or p.rule in ("hall", "wings", "soil_floor", "construct_blocks")
            or p.action.get("style") == "sealed"]


def gatehouse_fort(traits, gatehouse="standing", **over):
    s = fort(traits, **over)
    s["entrances"]["entrances"][0].update({"gatehouse": gatehouse})
    return s


# --- the sliders at default: nothing new built -------------------------------------------

@test("defaults: no construction proposal of any kind, whatever the report shows (hall, gatehouse, soil)")
def _():
    s = fort({})
    s["buildings"]["halls"] = {"stage": "walls", "walls_planned": 0, "kind": "field_hall"}
    s["entrances"]["entrances"][0]["gatehouse"] = "standing"
    s["entrances"]["entrances"].append({"id": 2, "kind": "cavern", "x": 5, "y": 5, "z": 40, "width": 2,
                                        "equipment": [], "door_spots": 0})
    s["projects"]["decorating"] = [{"id": 7, "kind": "dining", "phase": "decorate"}]
    m = keep_refused(Memory(), 50)
    ps, notes = plan(s, m)
    assert construct_actions(ps) == [], construct_actions(ps)
    assert not [n for n in notes if "hall" in n and "waits" in n], notes


@test("defaults: the Monastery builds only soil floors; the Deep mine nothing above ground")
def _():
    s = fort(MONASTERY)
    s["projects"]["decorating"] = [{"id": 7, "kind": "temple", "phase": "decorate"}]
    ps, _ = plan(s, keep_refused(Memory()))
    kinds = {a["type"] for a in construct_actions(ps)}
    assert kinds <= {"floor_rooms", "work_order"}, kinds
    assert "place_hall" not in kinds and "build_wings" not in kinds
    s = fort(DEEP)
    ps, _ = plan(s, keep_refused(Memory()))
    assert not [a for a in construct_actions(ps) if a["type"] != "work_order"], construct_actions(ps)


# --- the surface hall -----------------------------------------------------------------------

@test("hall: the Garden fort waits for the keep, then builds a field hall once the keep failed 3 times")
def _():
    s = fort(GARDEN)
    ps, _ = run(s, Memory())
    assert not hall_props(ps)                         # the keep goes first
    ps, _ = run(s, keep_refused(Memory(), 2))
    assert not hall_props(ps)
    ps, _ = run(s, keep_refused(Memory(), 3))
    assert [p.action for p in hall_props(ps)] == [{"type": "place_hall", "kind": "field_hall"}], ps
    assert hall_props(ps)[0].priority == 7


@test("hall: the Merchant city builds a market hall by its depot (Surface 40: no keep), none without a depot")
def _():
    s = fort(MERCHANT)
    ps, _ = run(s)
    assert [p.action for p in hall_props(ps)] == [{"type": "place_hall", "kind": "market_hall"}], ps
    s["buildings"]["other"].pop("TradeDepot")
    ps, _ = run(s)
    assert not hall_props(ps)


@test("hall: one stage pending at a time; planned tiles wait, trees wait, done is done")
def _():
    s = fort(MERCHANT)
    s["buildings"]["halls"] = {"list": [{"kind": "market_hall", "stage": "walls", "walls_planned": 12}]}
    ps, notes = run(s)
    assert not hall_props(ps) and any("12 walls tile(s) still to build" in n for n in notes), notes
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "clearing", "trees_left": 3}
    ps, notes = run(s)
    assert not hall_props(ps) and any("3 tree(s)" in n for n in notes), notes
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "walls", "walls_planned": 0}
    ps, _ = run(s)
    assert hall_props(ps)
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "done"}
    ps, notes = run(s)
    assert not hall_props(ps) and not notes


@test("hall: the tile cap: no stage while its tiles would put the planned constructions over 100")
def _():
    s = fort(MERCHANT)
    s["buildings"]["being_built"] = {"Construction": 80}
    ps, notes = run(s)
    assert not hall_props(ps) and any("at most 100" in n for n in notes), notes
    s["buildings"]["being_built"] = {"Construction": 60}
    assert hall_props(run(s)[0])
    s["constructions"] = {"planned": {"n": 90}}
    assert not hall_props(run(s)[0])


@test("hall: waits for free blocks; after two seasons short it builds with any material")
def _():
    s = fort(MERCHANT)
    s["stocks"]["blocks"] = 10
    m = Memory()
    ps, notes = run(s, m)
    assert not hall_props(ps) and any("waits for 28 blocks" in n for n in notes), notes
    note_cycle(s, m)
    since = m.construct["hall_short"]["since"]
    assert m.construct["hall_short"]["stage"] == "walls"
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += CFG["hall_block_wait_ticks"] // 2
    assert not hall_props(run(s2, m)[0])
    s3 = copy.deepcopy(s)
    s3["date"]["year"] += 1                           # well past two seasons
    note_cycle(s3, m)
    assert m.construct["hall_short"]["since"] == since          # the clock isn't restarted
    assert hall_props(run(s3, m)[0])
    s3["stocks"].update(boulders=0, wood=0)                     # and nothing at all to build with: still waits
    assert not hall_props(run(s3, m)[0])


@test("hall: quiet in a young or small fort, underground, hidden, halted, switched off, in a crisis")
def _():
    s = fort(MERCHANT)
    s["dwarves"]["total"] = 25
    assert not hall_props(run(s)[0])
    assert not hall_props(run(fort(dict(MERCHANT, surface=-90)))[0])
    assert not hall_props(run(fort(dict(GARDEN, outsiders=-150, caution=40)), keep_refused(Memory()))[0])
    s = fort(MERCHANT, halted=True)
    assert not hall_props(run(s)[0])
    s = fort(MERCHANT)
    s["settings"]["construct"] = False
    assert not hall_props(run(s)[0])
    m = Memory()
    m.crisis = {"since": 1, "why": ["deaths"]}
    assert not hall_props(run(fort(MERCHANT), m)[0])


@test("hall: quiet with a threat that can reach the dwarves, a siege held off, the alarm, a threat days ago")
def _():
    s = fort(MERCHANT)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    assert not hall_props(run(s)[0])
    s = fort(MERCHANT)
    s["others_on_map"]["threats"] = [{"id": 9, "invader": True, "can_reach_dwarves": False}]
    assert not hall_props(run(s)[0])
    s = fort(MERCHANT, civ_alert=True)
    assert not hall_props(run(s)[0])
    s = fort(MERCHANT)
    s["entrances"]["armed"] = True
    assert not hall_props(run(s)[0])
    s = fort(MERCHANT)
    m = Memory(last_threat_tick=abs_tick(s) - TICKS_PER_DAY)
    assert not hall_props(run(s, m)[0])
    m = Memory(last_threat_tick=abs_tick(s) - 10 * TICKS_PER_DAY)
    assert hall_props(run(s, m)[0])


@test("one building at a time: the hall waits for an open keep, the keep for an open hall")
def _():
    s = fort(dict(GARDEN, trade=100))
    s["buildings"]["keep"] = {"stage": "walls", "walls_planned": 0}
    ps, notes = run(s, keep_refused(Memory()))
    assert not hall_props(ps) and any("waits for the keep" in n for n in notes), notes
    s["buildings"]["keep"] = {"stage": "done"}
    assert hall_props(run(s, keep_refused(Memory()))[0])
    # the keep waits for the hall
    s = fort(GARDEN)
    s["buildings"]["halls"] = {"kind": "field_hall", "stage": "roof", "roof_planned": 0}
    ps, notes = plan(s, Memory())
    assert not [p for p in ps if p.action.get("type") == "place_keep"]
    assert any("keep waits for the hall" in n for n in notes), notes
    s["buildings"]["halls"] = {"kind": "field_hall", "stage": "furnish"}
    ps, _ = plan(s, Memory())
    assert [p for p in ps if p.action.get("type") == "place_keep"]


@test("keep: blocks count first; boulders and logs still do")
def _():
    s = fort(GARDEN)
    s["stocks"].update(blocks=0, blocks_free=0, boulders=0, wood=10)
    ps, notes = plan(s, Memory())
    assert not [p for p in ps if p.action.get("type") == "place_keep"]
    assert any("keep waits for blocks" in n for n in notes), notes
    s["stocks"].update(blocks=100, blocks_free=70)
    assert [p for p in plan(s, Memory())[0] if p.action.get("type") == "place_keep"]


# --- blocks for building ----------------------------------------------------------------------

@test("blocks: ordered for the hall's stage, outside the idle cap, at most 10 jobs, only from usable stone")
def _():
    s = fort(MERCHANT)
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "walls", "walls_planned": 0, "blocks_needed": 70}
    s["stocks"]["blocks"] = 600                       # over the idle-hands cap of 500
    ps, notes = [], []
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, notes, Memory())
    assert not ps                                     # 600 cover 70
    s["stocks"]["blocks"] = 5
    s["buildings"]["halls"]["blocks_needed"] = 200
    ps, notes = [], []
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, notes, Memory())
    assert [p.action for p in ps] == [{"type": "work_order", "recipe": "stone_blocks", "amount": 10}], ps
    assert ps[0].rule == "construct_blocks" and ps[0].is_order
    s["stone_use"] = {"usable": 3}
    ps, notes = [], []
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, notes, Memory())
    assert not ps and any("usable stone" in n for n in notes), notes
    # not twice in a cycle with the idle hands' order
    s.pop("stone_use")
    ps = [Proposal("idle", {"type": "work_order", "recipe": "stone_blocks", "amount": 5}, "", 5, True)]
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, [], Memory())
    assert len(ps) == 1


@test("blocks: queued jobs count (4 blocks each); nothing to build, nothing ordered")
def _():
    s = fort(MERCHANT)
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "walls", "walls_planned": 0, "blocks_needed": 40}
    s["stocks"]["blocks"] = 0
    s["orders"] = [{"id": 1, "recipe": "stone_blocks", "amount_left": 12, "amount_total": 12, "by_ai": True}]
    ps = []
    pc._construction_blocks_rule(s, CFG, 194, MERCHANT, ps, [], Memory())
    assert not ps                                     # 48 >= 44
    ps = []
    pc._construction_blocks_rule(fort({}), CFG, 194, {}, ps, [], Memory())
    assert not ps


# --- wing walls (the War-hold) ---------------------------------------------------------------

def gate_props(s, m=None, traits=None):
    m = m if m is not None else Memory()
    ps, notes = [], []
    _gate_rules(s, m, CFG, player_rules(s), False, ps, notes, traits if traits is not None else
                s["settings"]["traits"])
    return ps, notes


@test("wings: a War-hold gatehouse gets its arms once; not without a standing gatehouse")
def _():
    s = gatehouse_fort(WAR)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    m = Memory()
    ps, _ = gate_props(s, m)
    w = [p for p in ps if p.rule == "wings"]
    assert [p.action for p in w] == [{"type": "build_wings", "entrance_id": 1}], ps
    record([(w[0], {"ok": True})], s, m)
    assert "31,140,173" in m.construct["wings"]
    assert not [p for p in gate_props(s, m)[0] if p.rule == "wings"]
    s = gatehouse_fort(WAR, gatehouse="possible")
    s["entrances"]["scanned_tick"] = abs_tick(s)
    assert not [p for p in gate_props(s)[0] if p.rule == "wings"]


@test("wings: a refusal waits two weeks (gate_failures) and backs off; never Hermit, alert, Rules off")
def _():
    s = gatehouse_fort(WAR)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    m = Memory()
    w = [p for p in gate_props(s, m)[0] if p.rule == "wings"][0]
    record([(w, {"ok": False, "error": "an arm would close a courtyard"})], s, m)
    assert "wings:31,140,173" in m.gate_failures
    assert not [p for p in gate_props(s, m)[0] if p.rule == "wings"]
    assert _refused_wait(m, w, abs_tick(s)) == 1
    s2 = copy.deepcopy(s)
    s2["date"]["year"] += 1
    s2["entrances"]["scanned_tick"] = abs_tick(s2)
    assert [p for p in gate_props(s2, m)[0] if p.rule == "wings"]
    # Hermit: hidden, and Surface -60
    s = gatehouse_fort(HERMIT)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    assert not [p for p in gate_props(s)[0] if p.rule == "wings"]
    s = gatehouse_fort(dict(WAR, outsiders=-150, caution=60))      # hidden_hold
    s["entrances"]["scanned_tick"] = abs_tick(s)
    assert not [p for p in gate_props(s)[0] if p.rule == "wings"]
    s = gatehouse_fort(WAR, civ_alert=True)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    assert not [p for p in gate_props(s)[0] if p.rule == "wings"]
    s = gatehouse_fort(WAR)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    s["settings"]["fortify_entrances"] = False
    assert not [p for p in gate_props(s)[0] if p.rule == "wings"]


# --- the Hermit's cavern walls ------------------------------------------------------------

def cavern_fort(traits, width=2):
    s = fort(traits)
    s["entrances"]["scanned_tick"] = abs_tick(s)
    s["entrances"]["entrances"] = [{"id": 4, "kind": "cavern", "x": 10, "y": 12, "z": 60, "width": width,
                                    "equipment": [], "door_spots": 0}]
    return s


@test("cavern walls: the Hermit seals a narrow cavern opening; wide, other forts and refused keep the usual gate")
def _():
    s = cavern_fort(HERMIT)
    m = Memory()
    f = [p for p in gate_props(s, m)[0] if p.rule == "fortify"]
    assert f and f[0].action["style"] == "sealed", f
    record([(f[0], {"ok": False, "error": "a citizen is beyond"})], s, m)
    assert "10,12,60" in m.construct["sealed_refused"]
    m.gate_failures.clear()
    m.refusals.clear()
    f = [p for p in gate_props(s, m)[0] if p.rule == "fortify"]
    assert f and f[0].action["style"] != "sealed", f
    f = [p for p in gate_props(cavern_fort(HERMIT, width=4))[0] if p.rule == "fortify"]
    assert f and f[0].action["style"] != "sealed"
    f = [p for p in gate_props(cavern_fort(WAR))[0] if p.rule == "fortify"]
    assert f and f[0].action["style"] != "sealed"
    s = cavern_fort(HERMIT)
    s["settings"]["fortify_entrances"] = False
    assert not [p for p in gate_props(s)[0] if p.rule == "fortify"]


# --- soil floors -------------------------------------------------------------------------------

def soil_fort(traits, **over):
    s = fort(traits, **over)
    s["projects"]["decorating"] = [{"id": 7, "kind": "dining", "phase": "decorate"},
                                   {"id": 8, "kind": "bedrooms", "phase": "decorate"}]
    return s


def soil_props(s, m=None):
    ps, notes = [], []
    pc._soil_floor_rule(s, s["settings"]["traits"], CFG, ps, notes, m if m is not None else Memory())
    return ps, notes


@test("soil floors: a finished dining level gets them once (Garden, Merchant); not bedrooms; not by default")
def _():
    s = soil_fort(GARDEN)
    m = Memory()
    ps, _ = soil_props(s, m)
    assert [p.action for p in ps] == [{"type": "floor_rooms", "project_id": 7}], ps
    record([(ps[0], {"ok": True, "tiles": 20})], s, m)
    assert "7" in m.construct["floored"]
    assert not soil_props(s, m)[0]
    assert soil_props(soil_fort(MERCHANT))[0]
    assert not soil_props(soil_fort({}))[0]
    assert not soil_props(soil_fort(WAR))[0]


@test("soil floors: wait for blocks; the report's soil count; given up after 3 refusals")
def _():
    s = soil_fort(GARDEN)
    s["stocks"]["blocks"] = 30
    ps, notes = soil_props(s)
    assert not ps and any("waits for 60 blocks" in n for n in notes), notes
    s["projects"]["soil_floors"] = [{"project_id": 7, "tiles": 25}]
    assert soil_props(s)[0]
    s["projects"]["soil_floors"] = [{"project_id": 7, "tiles": 0}]
    assert not soil_props(s)[0]
    s = soil_fort(GARDEN)
    m = Memory()
    for _i in range(3):
        p = soil_props(s, m)[0][0]
        record([(p, {"ok": False, "error": "no soil reachable"})], s, m)
    assert not soil_props(s, m)[0]
    # nothing_to_do counts as done
    m = Memory()
    p = soil_props(s, m)[0][0]
    record([(p, {"ok": False, "nothing_to_do": True, "error": "no soil"})], s, m)
    assert not soil_props(s, m)[0]


# --- cooldowns and the refusal back-off ------------------------------------------------

@test("every rule has its cooldown; a refused hall backs off and doesn't loop")
def _():
    for rule in ("hall", "wings", "soil_floor", "construct_blocks"):
        assert isinstance(CFG.get(f"{rule}_cooldown_ticks"), int) and CFG[f"{rule}_cooldown_ticks"] >= 1200, rule
    def halls(s, m):
        return [p for p in plan(s, m)[0] if p.rule == "hall"]

    s = fort(MERCHANT)
    m = Memory()
    allowed, _ = select(halls(s, m), s, m)
    h = [p for p in allowed if p.rule == "hall"]
    assert h, [p.rule for p in allowed]
    record([(h[0], {"ok": False, "error": "no site: open flat ground near the depot"})], s, m)
    days = []
    for i in range(12):
        s2 = copy.deepcopy(s)
        s2["date"]["tick"] += (i + 1) * TICKS_PER_DAY
        allowed, held = select(halls(s2, m), s2, m)
        h = [p for p in allowed if p.rule == "hall"]
        if h:
            days.append(i + 1)
            record([(h[0], {"ok": False, "error": "no site"})], s2, m)
    # back-off 1, 2, 4 ... days and the 2-day cooldown: a handful of tries in 12 days, not 12
    assert 1 <= len(days) <= 4, days
    # a success: the cooldown holds the next stage a while
    m = Memory()
    s = fort(MERCHANT)
    h = [p for p in select(halls(s, m), s, m)[0] if p.rule == "hall"][0]
    record([(h, {"ok": True})], s, m)
    s2 = copy.deepcopy(s)
    s2["date"]["tick"] += TICKS_PER_DAY
    allowed, held = select(halls(s2, m), s2, m)
    assert not [p for p in allowed if p.rule == "hall"]
    assert any(x.startswith("hall: waiting for its cooldown") for x in held), held


@test("the halt: nothing construction-related is proposed while halted in the game")
def _():
    s = fort(MERCHANT, halted=True)
    s["projects"]["decorating"] = [{"id": 7, "kind": "dining", "phase": "decorate"}]
    s["buildings"]["halls"] = {"kind": "market_hall", "stage": "walls", "walls_planned": 0, "blocks_needed": 999}
    ps, _ = plan(s, Memory())
    assert not [a for a in construct_actions(ps)], construct_actions(ps)


# --- labels, memory --------------------------------------------------------------------------

@test("labels: the new actions have words; the hall and the wings are asked first in co-pilot")
def _():
    for t in ("place_hall", "build_wings", "floor_rooms"):
        assert overseer.short({"type": t}) == overseer.SHORT_WORDS[t], t
    assert {"place_hall", "build_wings"} <= overseer.BIG_MOVES
    assert "floor_rooms" not in overseer.BIG_MOVES


@test("memory: construct survives a save and load; an old save without it loads")
def _():
    m = Memory()
    m.construct = {"wings": {"1,2,3": 5}, "floored": ["7"], "hall_short": {"stage": "walls", "since": 9}}
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert m2.construct == m.construct
    m3 = Memory.from_dict({"construct": None})
    assert m3.construct == {}
    assert pc.HALL_MAX_INTERIOR >= 7 * 5


if __name__ == "__main__":
    finish()
