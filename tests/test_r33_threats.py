"""(0.105.33, threats) The B3/L1 audit's findings in planner_gates,
planner_threats, planner_military and planner_industry's prune: the
stranded rule's open_gates held during a siege; the cavern seals kept while
the deep section is unread; a squad after a thief inside not recalled; the
unstick rule no longer holding arm_gates; the gatehouse's outer lever
watched; usable parts not rotted while a mood wants bone; the cavern doors
retried; hazard_alert on a bad first row. Fake reports, no Lua.

    python tests/test_r33_threats.py
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
import planner_core  # noqa: E402
import planner_threats  # noqa: E402
import planner_military  # noqa: E402
import planner_industry  # noqa: E402
from planner_threats import _cavern_beasts, threat_rules_of, deep_read  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


def needs_you(notes):
    return [n for n in notes if n.startswith("[you]")]


def siege_fort(goblins: int = 12, cavern: bool = False) -> dict:
    """Gate A shut on held-off goblins, 2 citizens shut out at gate B far off."""
    s = copy.deepcopy(BASE)
    ent = s["entrances"]
    ent["armed"] = True
    kind = "cavern" if cavern else "surface"
    ent["entrances"] = [
        {"id": 1, "kind": "surface", "x": 31, "y": 140, "z": 173, "width": 1, "sealed": True, "closed": True,
         "equipment": [{"id": 500, "kind": "door"}], "door_spots": 0},
        {"id": 2, "kind": kind, "x": 150, "y": 20, "z": 173, "width": 1, "sealed": True, "closed": True,
         "equipment": [{"id": 501, "kind": "door"}], "door_spots": 0}]
    ent["stranded"] = [{"id": 70 + i, "name": f"Urist {i}", "x": 152, "y": 18, "z": 173, "cause": "lockdown",
                        "by_ai": True, "out_ticks": 600, "out_days": 0, "danger_near": 120, "gate_danger": 119,
                        "entrance": {"id": 2, "kind": kind, "x": 150, "y": 20, "z": 173}} for i in range(2)]
    s["others_on_map"]["threats"] = [{"id": 900 + i, "name": "goblin", "invader": True, "can_reach_dwarves": False,
                                      "layer": "surface", "distance_to_nearest_dwarf": 4} for i in range(goblins)]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    return s


# --- B3 High: planner_gates _stranded_rule ------------------------------------------

@test("stranded: a siege held off at another gate: no open_gates (it opens every gate); their gate alone or a wait, nothing for the player")
def _():
    s = siege_fort()
    s["deep"] = {"caverns": [], "dangers": []}
    props, notes = plan(s, Memory())
    assert not acts(props, "stranded", "open_gates") and not acts(props, typ="open_gates"), \
        [(p.rule, p.action) for p in props]
    # (0.105.34) nothing waits for the player: their gate alone, or a wait said
    assert not [n for n in needs_you(notes) if "Urist 0" in n], needs_you(notes)
    assert acts(props, "stranded", "open_entrance") or [n for n in notes if "keeps it shut" in n or
                                                        "stay as they are" in n], (props, notes)


@test("stranded: no enemy on the map at all: the gates opened as before")
def _():
    s = siege_fort(goblins=0)
    s["deep"] = {"caverns": [], "dangers": []}
    props, _ = plan(s, Memory())
    p = acts(props, "stranded", "open_gates")
    assert p and "Urist 0" in p[0].reason, [(p.rule, p.action) for p in props]


@test("stranded: a threat that can reach the dwarves: no open_gates; the watcher is armed (the open no longer holds it)")
def _():
    s = siege_fort(goblins=0)
    s["deep"] = {"caverns": [], "dangers": []}
    s["entrances"]["armed"] = False
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    props, notes = plan(s, Memory())
    assert not acts(props, "stranded", "open_gates"), [(p.rule, p.action) for p in props]
    assert acts(props, "gates", "arm_gates"), [(p.rule, p.action) for p in props]
    assert not [n for n in needs_you(notes) if "Urist" in n], needs_you(notes)   # (0.105.34) nothing waits for the player


# --- B3 High: the deep section failed ------------------------------------------------

def deep_state(deep):
    s = {"threats": {"sealed": {"all caverns": {"days": 1}}, "openings": {"list": []}},
         "settings": {}, "entrances": {}, "date": {"year": 5, "tick": 100}}
    if deep is not None:
        s["deep"] = deep
    return s


@test("cavern seal: the deep section failed or missing: the caverns stay locked, said; a good empty read opens them")
def _():
    for deep in ({"error": "ai-bridge-report.lua:2690: attempt to index nil"}, None):
        s = deep_state(deep)
        props, notes = [], []
        _cavern_beasts(s, PLANNER_CONFIG, Memory(), s["threats"], threat_rules_of(s), props, notes)
        assert not acts(props, "seal_cavern"), [(p.rule, p.action) for p in props]
        assert [n for n in notes if "couldn't be read" in n and "stay locked" in n], notes
    s = deep_state({"caverns": [], "dangers": []})
    s["_errors"] = {"deep": "boom"}
    assert not deep_read(s)
    s = deep_state({"caverns": [], "dangers": []})
    props, notes = [], []
    _cavern_beasts(s, PLANNER_CONFIG, Memory(), s["threats"], threat_rules_of(s), props, notes)
    assert [p for p in props if p.action == {"type": "seal_cavern", "layer": "all caverns", "open": True}], props


@test("cavern seal via plan(): {error} deep and a seal on record: no open")
def _():
    s = copy.deepcopy(BASE)
    s["deep"] = {"error": "get_deep failed"}
    s.setdefault("threats", {})["sealed"] = {"all caverns": {"days": 1}}
    props, _ = plan(s, Memory())
    assert not [p for p in props if p.action.get("type") == "seal_cavern" and p.action.get("open")], \
        [(p.rule, p.action) for p in props]


@test("stranded: a cavern gate with the deep section unread: not opened, put to the player")
def _():
    s = siege_fort(goblins=0, cavern=True)
    s["deep"] = {"error": "get_deep failed"}
    props, notes = plan(s, Memory())
    assert not acts(props, "stranded", "open_gates"), [(p.rule, p.action) for p in props]
    assert [n for n in needs_you(notes) if "couldn't be read" in n and "Urist 0" in n], needs_you(notes)
    s = siege_fort(goblins=0, cavern=True)      # (merge33) a fresh report: normalize() keeps the first's _errors.deep
    s["deep"] = {"caverns": [], "dangers": []}
    props, _ = plan(s, Memory())
    assert acts(props, "stranded", "open_gates"), [(p.rule, p.action) for p in props]


# --- B3 High: the thief squad recalled every other cycle -----------------------------

def thief_fort(inside=True):
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s.setdefault("threats", {})["thieves"] = {"list": [{"id": 999, "name": "Thief", "kind": "thief", "inside": inside,
                                                        "can_reach_dwarves": False, "kill_ok": True}],
                                              "seen_total": 1}
    return s


@test("thief inside: the squad sent at it is not recalled the next cycle; once the thief is gone it is")
def _():
    s = thief_fort()
    props, _ = plan(s, Memory())
    sent = acts(props, "squad_attack")
    assert sent and sent[0].action["kill"] == [999], [(p.rule, p.action) for p in props]
    q0 = sent[0].action["squad_id"]
    for q in s["military"]["squads"]:
        if q["id"] == q0:
            q["ai_orders"] = True
            q["kill_ids"] = [999]
    props, _ = plan(s, Memory())
    assert not acts(props, "squad_recall") and not acts(props, "squad_attack"), [(p.rule, p.action) for p in props]
    s["threats"]["thieves"]["list"] = []
    props, _ = plan(s, Memory())
    assert [p for p in acts(props, "squad_recall") if p.action["squad_id"] == q0], [(p.rule, p.action) for p in props]


# --- L1 Med: the gatehouse's outer bridge lever is the watcher's ---------------------

@test("an 'AI gate' lever linked to a gatehouse's outer bridge: not pulled by the brain (the watcher drives it)")
def _():
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = [{"id": 5, "name": "goblin", "invader": True, "can_reach_dwarves": True,
                                      "layer": "surface", "distance_to_nearest_dwarf": 30}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s["military"]["gates"] = [{"id": 91, "name": "AI gate", "linked": True}]
    e = s["entrances"]["entrances"][0] if s["entrances"].get("entrances") else None
    assert isinstance(e, dict), s["entrances"]
    e["outer"] = [{"id": 40, "kind": "bridge", "lever_id": 91}]
    props, _ = plan(s, Memory())
    assert not acts(props, "gate", "pull_gate"), [(p.rule, p.action) for p in props]
    e["outer"] = []
    props, _ = plan(s, Memory())
    assert acts(props, "gate", "pull_gate"), [(p.rule, p.action) for p in props]


# --- B3 Low: hazard_alert --------------------------------------------------------------

@test("hazard_alert: a non-dict first berserk row doesn't crash; the first dict row is named")
def _():
    s = {"hazards": {"berserk": ["junk", {"id": 3, "name": "Urist"}]}}
    assert planner_military.hazard_alert(s, PLANNER_CONFIG) == "Urist has gone berserk"
    assert planner_military.hazard_alert({"hazards": {"berserk": ["junk"]}}, PLANNER_CONFIG) == ""


# --- B3 Low: planner_threats dead code, _cavern_doors retry ---------------------------

@test("player_attack is gone (dead code)")
def _():
    assert not hasattr(planner_threats, "player_attack")


@test("cavern doors: a refusal is retried after gate_retry_ticks, not skipped for good")
def _():
    s = copy.deepcopy(BASE)
    s["entrances"]["entrances"] = [{"id": 4, "kind": "cavern", "x": 10, "y": 11, "z": 120, "door_spots": 1}]
    now = planner_core.abs_tick(s)
    m = Memory()
    m.gate_failures = {"10,11,120": "refused: no mechanism"}
    m.gate_failure_ticks = {"10,11,120": now - 10}
    props, notes = [], []
    planner_threats._cavern_doors(s, m, props, notes, PLANNER_CONFIG)
    assert not props, props
    m.gate_failure_ticks = {"10,11,120": now - PLANNER_CONFIG["gate_retry_ticks"] - 1}
    planner_threats._cavern_doors(s, m, props, notes, PLANNER_CONFIG)
    assert acts(props, "cavern_openings", "build_gate_doors"), props


# --- B3 Med: usable parts kept while a mood wants bone --------------------------------

def prune_state(**kw):
    s = copy.deepcopy(BASE)
    s["fps_low"] = True
    s["dead"] = dict(s.get("dead") or {}, unburied=0)
    s["needs"] = dict(s.get("needs") or {}, bones=50)
    s.update(kw)
    m = Memory()
    m.census = {"tick": planner_core.abs_tick(s), "items": {"on_ground": [{"name": "CORPSEPIECE", "n": 3000}]}}
    return s, m


def prune_extra(s, m):
    props, notes = [], []
    planner_industry._clutter_rules(s, PLANNER_CONFIG, props, notes, m)
    p = acts(props, "prune", "prune_remains")
    assert p, props
    return p[0].action.get("extra") or []


@test("prune: usable parts rot only with no mood wanting bone or shell and bones over the reserve")
def _():
    s, m = prune_state()
    s["moods"] = {"list": []}
    assert "usable-parts" in prune_extra(s, m)
    s, m = prune_state()
    s["moods"] = {"list": [{"craft": True, "missing": [{"item": "NONE", "flags": ["bone"], "on_hand": True}]}]}
    assert "usable-parts" not in prune_extra(s, m)
    s, m = prune_state()
    s["moods"] = {"list": []}
    s["needs"]["bones"] = PLANNER_CONFIG["reserve_bones"]
    assert "usable-parts" not in prune_extra(s, m)


finish()
