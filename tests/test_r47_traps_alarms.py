"""(0.105.47) Traps by Fortification, alarms by Caution (brain/planner_traplean.py,
brain/alarm_caution.py, and the rules they set: planner_gates._trap_rule, the
thieves' traps, planner_killzone, planner_alarm.govern_alarm,
planner_military.hazard_alert, planner_threats.threat_alert,
planner_core.reachable_threats; the scorecard's gate works and alarms lines).

    python tests/test_r47_traps_alarms.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import planner  # noqa: E402
from planner import Memory, plan, record, Proposal, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
import defence  # noqa: E402
import planner_gates as PG  # noqa: E402
import planner_killzone as PKZ  # noqa: E402
import planner_alarm as PA  # noqa: E402
import planner_threats as PT  # noqa: E402
import planner_traplean as TL  # noqa: E402
import alarm_caution as AC  # noqa: E402
import scorecard  # noqa: E402
from planner_core import reachable_threats  # noqa: E402
from planner_military import hazard_alert  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
ON = {"type": "civ_alert", "on": True}
OFF = {"type": "civ_alert", "on": False}

# the built-in presets' sliders that matter here (lua/ai-overseer-settings.lua BUILTIN_PRESETS)
WAR = {"militarism": 150, "fortification": 120, "caution": 60, "engineering": 60, "outsiders": -80}
HERMIT = {"outsiders": -150, "caution": 60, "fortification": 100}
DEEP = {"mining": 150, "engineering": 60, "caution": -40}
MERCHANT = {"outsiders": 100, "trade": 120}
LOW = {"fortification": -80}


def fort(traits=None, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits or {})
    s["civ_alert_ready"] = True
    s.update(kw)
    return planner.normalize(s)


SURF = {"id": 1, "kind": "surface", "x": 40, "y": 50, "z": 170, "sealed": True, "equipment": [{"kind": "door"}]}
CAV1 = {"id": 2, "kind": "cavern", "x": 10, "y": 10, "z": 120, "sealed": True, "equipment": [{"kind": "door"}]}
CAV2 = {"id": 3, "kind": "cavern", "x": 90, "y": 90, "z": 110, "sealed": True, "equipment": [{"kind": "hatch"}]}


def mem(used=None) -> Memory:
    m = Memory()
    m.atlas = {"entrances": used or {}, "registry": {}}
    return m


def trap_gates(traits, used=None) -> list:
    """The gates _trap_rule sets traps behind, one a cycle until none is left."""
    m = mem(used)
    s = fort(traits)
    out = []
    old = PG.profile_from
    PG.profile_from = lambda *a, **k: {"traps": "cage", "gate": "plain"}
    try:
        for _ in range(5):
            props = []
            PG._trap_rule(s, m, CFG, [SURF, CAV1, CAV2], abs_tick(s), traits, props)
            t = [p for p in props if p.action.get("type") == "place_traps"]
            if not t:
                break
            e = next(x for x in (SURF, CAV1, CAV2) if x["id"] == t[0].action["entrance_id"])
            out.append((e["id"], t[0].action["count"]))
            m.atlas["registry"][f"traps:{e['x']},{e['y']},{e['z']}"] = {"kind": "traps"}
    finally:
        PG.profile_from = old
    return out


# --- traps by Fortification ---------------------------------------------------------------------

@test("traps a gate by Fortification: War-hold 7, Hermit hold 6, a fort at 0 (Deep mine, Merchant city) 3, low 2")
def _():
    assert defence.trap_count(WAR) == 7, defence.trap_count(WAR)
    assert defence.trap_count(HERMIT) == 6, defence.trap_count(HERMIT)
    assert defence.trap_count(DEEP) == 3 and defence.trap_count(MERCHANT) == 3
    assert defence.trap_count({"fortification": -100}) == 2
    assert defence.trap_count(WAR) > defence.trap_count(HERMIT) > defence.trap_count(DEEP) >= defence.trap_count(LOW)


@test("which gates: high (War-hold, Hermit hold) every gate; at 0 the surface one; low none until enemies came")
def _():
    assert TL.trap_tier(WAR) == "every" and TL.trap_tier(HERMIT) == "every"
    assert TL.trap_tier(DEEP) == "surface" and TL.trap_tier(MERCHANT) == "surface" and TL.trap_tier(LOW) == "used"
    assert TL.trap_tier({"outsiders": -150}) == "every"            # a closed fort keeps every way in
    war = trap_gates(WAR)
    assert sorted(g for g, _ in war) == [1, 2, 3] and all(n == 7 for _, n in war), war
    her = trap_gates(HERMIT)
    assert sorted(g for g, _ in her) == [1, 2, 3] and all(n == 6 for _, n in her), her
    deep = trap_gates(DEEP)
    assert deep == [(1, 3)], deep                                   # the Deep mine's cavern doors: no traps
    assert trap_gates(LOW) == [], trap_gates(LOW)
    # traps total: the War-hold's 21, the Deep mine's 3, a low fort's 0
    tot = {k: sum(n for _, n in trap_gates(t)) for k, t in (("W", WAR), ("H", HERMIT), ("D", DEEP), ("L", LOW))}
    assert tot["W"] > tot["H"] > tot["D"] > tot["L"], tot


@test("a gate enemies came through gets traps at any Fortification (said why); low needs that")
def _():
    used = {"10,10,120": {"threats": 2, "deaths": 1}}
    deep = trap_gates(DEEP, used)
    assert sorted(g for g, _ in deep) == [1, 2], deep
    low = trap_gates(LOW, used)
    assert low == [(2, 2)], low
    why = TL.trap_gate_why(CAV1, LOW, mem(used), CFG)
    assert why == "enemies came this way 2 time(s), 1 died by it", why
    assert TL.trap_gate_why(CAV1, LOW, mem(), CFG) == ""
    assert "every gate" in TL.trap_gate_why(CAV1, WAR, mem(), CFG)


@test("the trap proposal says why this gate (Fortification or the enemies' way)")
def _():
    s = fort(WAR)
    props = []
    old = PG.profile_from
    PG.profile_from = lambda *a, **k: {"traps": "weapon", "gate": "plain"}
    try:
        PG._trap_rule(s, mem(), CFG, [CAV1], abs_tick(s), WAR, props)
    finally:
        PG.profile_from = old
    assert props and "(Fortification +120: traps behind every gate)" in props[0].reason, props


@test("thieves' cage traps (a fort with no trap style): the surface gates; cavern ones only where Fortification puts traps")
def _():
    import culture
    for traits, want in ((DEEP, [1]), (WAR, [2])):
        s = copy.deepcopy(BASE)
        s["settings"]["traits"] = dict(traits)
        s["threats"] = {"thieves": {"list": [], "seen_total": 2}}
        s["entrances"] = {"entrances": [dict(CAV1), dict(SURF)]}         # the cavern gate first
        old = culture.profile_from
        props, notes = [], []
        try:
            culture.profile_from = lambda *a, **k: {"traps": "none"}
            PT._threat_rules(planner.normalize(s), mem(), PLANNER_CONFIG, props, notes)
        finally:
            culture.profile_from = old
        got = [p.action["entrance_id"] for p in props if p.action.get("type") == "place_traps"]
        assert got == want, (traits, got)


# --- kill zones by Fortification ----------------------------------------------------------------

def kz_row(**kw):
    r = {"id": 1, "kind": "surface", "x": 50, "y": 50, "z": 120, "sealed": True, "state": "possible",
         "corridor": 5, "trap_tiles": 6, "drawbridge": {"possible": True, "channel": False, "why": "x"}}
    r.update(kw)
    return r


def kz_state(traits, *rows):
    s = copy.deepcopy(BASE)
    s["killzones"] = {"entrances": list(rows), "threats": [], "free_mechanisms": 20, "trap_weapons": 6,
                      "mechanics": 2, "scanned": True}
    s["settings"]["traits"] = dict(traits)
    return planner.normalize(s)


def kz_builds(s, m=None):
    props, notes = [], []
    PKZ._killzone_rule(s, m or mem(), dict(PLANNER_CONFIG), props, notes)
    return [p.action for p in props if p.action.get("type") == "build_killzone"]


@test("kill zones: every entrance by Fortification (War-hold, Hermit hold), not by Caution alone; 6 traps high")
def _():
    s = kz_state(WAR, kz_row())
    b = kz_builds(s)
    assert b and b[0]["traps"] == 6, b
    assert kz_builds(kz_state(HERMIT, kz_row()))                        # 100 and closed
    assert kz_builds(kz_state({"caution": 100}, kz_row())) == []        # Caution alone: only used ways
    assert kz_builds(kz_state(DEEP, kz_row())) == []                    # the Deep mine: unused ways wait


@test("kill zones at low Fortification: a way used once waits; three times (or a death) gets a smaller zone")
def _():
    s = kz_state(LOW, kz_row())
    assert kz_builds(s, mem({"50,50,120": {"threats": 1}})) == []
    b = kz_builds(s, mem({"50,50,120": {"threats": 3}}))
    assert b and b[0]["traps"] == 3, b
    assert kz_builds(s, mem({"50,50,120": {"threats": 0, "deaths": 1}}))
    b = kz_builds(kz_state(DEEP, kz_row()), mem({"50,50,120": {"threats": 1}}))
    assert b and b[0]["traps"] == 4, b                                  # at 0: as before


# --- the scorecard's lines ----------------------------------------------------------------------

def dec(t, result, tick=10, **a):
    return {"kind": "decision", "date": {"year": 1, "tick": tick}, "action": dict(a, type=t), "result": result}


@test("gate works: kill zones and wing walls count; the gate watcher armed, the squads at the gate and dry runs don't")
def _():
    assert "build_killzone" in scorecard.GATE_WORKS and "build_wings" in scorecard.GATE_WORKS
    assert "arm_gates" not in scorecard.GATE_WORKS and "guard_gate" not in scorecard.GATE_WORKS
    es = [dec("build_killzone", {"ok": True}), dec("arm_gates", {"ok": True}), dec("guard_gate", {"ok": True}),
          dec("build_gatehouse", {"ok": True, "dry_run": True}), dec("place_traps", {"ok": True}),
          dec("fortify_entrance", {"ok": False})]
    j = scorecard.journal_counts(es, {"year": 2, "tick": 0})
    assert j["gate_works"] == 2, j["gate_works"]


@test("alarms raised: raises only (not a refresh of one already up, not a refused lowering, not a dry run)")
def _():
    es = [dec("civ_alert", {"ok": True, "on": True}, on=True),
          dec("civ_alert", {"ok": True, "on": True, "already_on": True}, on=True),     # up already: no new alarm
          dec("civ_alert", {"ok": True, "on": True}, on=False),                        # a lowering the game kept up
          dec("civ_alert", {"ok": True, "on": False}, on=False),
          dec("civ_alert", {"ok": True, "dry_run": True}, on=True),
          dec("civ_alert", {"ok": True}, on=True),                                     # no "on" in the reply: a raise
          dec("civ_alert", {"ok": False, "error": "no burrow"}, on=True)]
    j = scorecard.journal_counts(es, {"year": 2, "tick": 0})
    assert j["alarms_on"] == 2, j["alarms_on"]


# --- alarms by Caution --------------------------------------------------------------------------

@test("the alarm's numbers at Caution 0 are the config's own; a careful fort's nearer-sooner, more; a bold one's fewer")
def _():
    z = AC.alarm_settings({}, CFG)
    assert (z["fire_near"], z["cloud_near"], z["fire_hold"], z["cloud_hold"]) == (8, 20, 20, 20), z
    assert z["cooldown_ticks"] == PLANNER_CONFIG["alarm_cause_cooldown_ticks"] and z["month_cap"] == 4 and z["intruder"]
    w = AC.alarm_settings(WAR, CFG)
    assert (w["fire_near"], w["cloud_near"], w["cooldown_ticks"], w["month_cap"]) == (11, 26, TICKS_PER_DAY, 7), w
    d = AC.alarm_settings(DEEP, CFG)
    assert (d["fire_near"], d["cloud_near"], d["month_cap"]) == (6, 16, 2) and d["cooldown_ticks"] > 2 * TICKS_PER_DAY, d
    assert d["intruder"] is False
    lo = AC.alarm_settings({"caution": -200}, CFG)
    hi = AC.alarm_settings({"caution": 200}, CFG)
    assert lo["fire_near"] == 4 and hi["fire_near"] == 18 and lo["month_cap"] == 1 and hi["month_cap"] == 10
    assert lo["cooldown_ticks"] == 4 * TICKS_PER_DAY and hi["cooldown_ticks"] == TICKS_PER_DAY // 2


@test("fire 10 tiles off: the War-hold (Caution 60) sounds it, a fort at 0 doesn't; the Deep mine only within 6")
def _():
    def fire(traits, d):
        s = fort(traits)
        s["hazards"] = {"fires": 2, "fire_near": d}
        return hazard_alert(s, CFG, raising=True)
    assert fire(WAR, 10) and not fire({}, 10) and fire({}, 8)
    assert not fire(DEEP, 7) and fire(DEEP, 6)
    s = fort(WAR)
    s["hazards"] = {"clouds": 1, "cloud_near": 24}
    assert hazard_alert(s, CFG, raising=True) and hazard_alert(s, CFG)          # raised and held alike
    s = fort({})
    s["hazards"] = {"clouds": 1, "cloud_near": 24}
    assert not hazard_alert(s, CFG, raising=True)


def gov(traits, reason, last_off=None, month_n=0, tick=200000):
    s = fort(traits, civ_alert=False)
    s["date"]["tick"] = tick
    now = abs_tick(s)
    m = Memory()
    g = {}
    key = PA.alarm_cause(reason)[1]
    if last_off is not None:
        g["off"] = {key: now - last_off}
    if month_n:
        g["month"] = {"m": now // PA.TICKS_PER_MONTH, "n": month_n}
    m.alarm_gov = g
    props, notes = [Proposal("threat_alert", dict(ON), reason, 0)], []
    PA.govern_alarm(s, m, CFG, props, notes)
    return bool(props), notes


FIRE = "fire 5 tiles from the dwarves: sound the alarm (the civilians go to the shelter)"


@test("the cooldown by Caution: a day and a half after a fire alarm came down, the War-hold raises again; 0 and the Deep mine wait")
def _():
    t = 3 * TICKS_PER_DAY // 2
    assert gov(WAR, FIRE, last_off=t)[0]
    assert not gov({}, FIRE, last_off=t)[0]
    assert not gov(DEEP, FIRE, last_off=5 * TICKS_PER_DAY // 2)[0]            # 2.5 days: still waiting
    assert gov({}, FIRE, last_off=5 * TICKS_PER_DAY // 2)[0]


@test("the month's cap by Caution: the War-hold 7, a fort at 0 4, the Deep mine 2; enemies in reach never held")
def _():
    assert gov(WAR, FIRE, month_n=6)[0] and not gov(WAR, FIRE, month_n=7)[0]
    assert gov({}, FIRE, month_n=3)[0] and not gov({}, FIRE, month_n=4)[0]
    assert gov(DEEP, FIRE, month_n=1)[0] and not gov(DEEP, FIRE, month_n=2)[0]
    ok, notes = gov(DEEP, FIRE, month_n=2)
    assert any("at most 2" in n for n in notes), notes
    assert gov(DEEP, "3 threat(s) can reach the dwarves", month_n=50, last_off=10)[0]
    assert gov({"caution": -200}, "a necromancer siege: 40 walking dead: sound the alarm", month_n=50)[0]


@test("an unseen lone intruder: the Deep mine (Caution -40) waits until one is seen (said); a group, or Caution 0, sounds it")
def _():
    lone = "DF reports an intruder on the map (2 game hour(s) ago), nobody seen yet (a thief hides until spotted)"
    group = "DF reports 6 intruders on the map (2 game hour(s) ago), nobody seen yet (a thief hides until spotted)"
    ok, notes = gov(DEEP, lone)
    assert not ok and any("waits until a lone intruder is seen" in n for n in notes), notes
    assert gov(DEEP, group)[0] and gov({}, lone)[0] and gov(WAR, lone)[0]


@test("the walking dead and a great beast outside: farther with Caution above 0, never nearer below it")
def _():
    def undead(traits, d):
        s = fort(traits)
        s["threats"] = {"undead": {"list": [{"id": 1, "name": "zombie", "can_reach_dwarves": True, "distance": d}]}}
        return PT.threat_alert(s, CFG)
    assert undead(WAR, 38) and not undead({}, 38) and undead({}, 30)
    assert undead(DEEP, 30) and undead({"caution": -200}, 30)
    def beast(traits, d):
        s = fort(traits)
        s["threats"] = {"surface": {"list": [{"great": True, "name": "titan", "distance_outside": d}]}}
        return PT.threat_alert(s, CFG)
    assert beast(WAR, 50) and not beast({}, 50) and beast(DEEP, 40)


@test("threats whose reach DF can't tell, near: in reach from Caution 50 (War-hold, Hermit hold: 6 levels), not at 0")
def _():
    s = fort({})
    s["others_on_map"] = dict(s["others_on_map"], threats_that_can_reach_dwarves=0,
                              threats=[{"id": 5, "can_reach_dwarves": None, "levels_from_nearest_dwarf": 5},
                                       {"id": 6, "can_reach_dwarves": None, "levels_from_nearest_dwarf": 8}])
    assert reachable_threats(s, WAR, CFG) == [5]
    assert reachable_threats(s, HERMIT, CFG) == [5]
    assert reachable_threats(s, {"caution": 100}, CFG) == [5, 6]                # as before at +100
    assert reachable_threats(s, {}, CFG) == [] and reachable_threats(s, DEEP, CFG) == []


@test("whole plan: a fire 10 tiles off sounds the War-hold's alarm and not a neutral fort's")
def _():
    def p(traits):
        s = fort(traits, civ_alert=False)
        s["hazards"] = {"fires": 1, "fire_near": 10}
        props, _ = plan(s, Memory())
        return [x for x in props if x.action == ON]
    assert p(WAR) and not p({})


@test("both switched off (the d0 merge test's main comparison): every gate, the old trap counts, the alarm's old numbers")
def _():
    keep = {k: PLANNER_CONFIG[k] for k in ("traps_by_fortification", "alarms_by_caution")}
    try:
        PLANNER_CONFIG.update(traps_by_fortification=False, alarms_by_caution=False)
        cfg = dict(PLANNER_CONFIG)
        assert defence.trap_count(HERMIT) == 5 and TL.trap_tier(LOW, cfg) == "every"
        w = AC.alarm_settings(WAR, cfg)
        assert (w["fire_near"], w["month_cap"], w["cooldown_ticks"]) == (8, 4, PLANNER_CONFIG["alarm_cause_cooldown_ticks"])
        assert AC.cautious_levels(WAR, cfg) is None and AC.cautious_levels({"caution": 100}, cfg) == 10
        assert kz_builds(kz_state({"caution": 100}, kz_row()))           # Caution 100 alone: every entrance, as before
    finally:
        PLANNER_CONFIG.update(keep)


if __name__ == "__main__":
    finish()
