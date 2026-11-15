"""(0.105.54, builder 43) Prepare and weaken while the civilians shelter.

The player (15 Nov, "fight back"): the fort deals with its threats instead
of only hiding from them. Here:
  * a besieger the bridge places in "upper_levels" (the surface's layer:
    ai-bridge-report layer_at, never "surface") is a besieger: before,
    gate_invaders never found one live, so no archer was posted, no gate
    guard held and siege works went on during a siege;
  * archers at the walls: the crossbow squads with bolts are posted behind
    the fortifications with a great beast held off outside too, not only in
    a siege; a squad without bolts isn't posted (said);
  * the archers' fortifications are carved once a siege or a great beast
    has been seen (before the next), crossbow squad or not;
  * a sortie: an AI squad with a kill order on enemies outside the gates
    while the civilians shelter opens the armed gates (a gatehouse's raised
    drawbridge lowered), and the gates aren't armed again while it lasts;
    the AI gate lever is pulled open for it; never with the alarm down nor
    with a great danger outside that no squad goes at;
  * squads sitting off duty while enemies can reach the dwarves go on
    training (in uniform, armed), whatever the fort's size; one the player
    sent off duty stays theirs;
  * the kill zone the enemy is coming to: what it has ready, said; the cage
    traps' re-arming (an animal stockpile, empty cages) goes on in a siege.

    python tests/test_k54_prepare.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

import digest  # noqa: E402
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_siege as PS  # noqa: E402
import planner_gates as PG  # noqa: E402
import planner_killzone as PK  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def acts(props, typ=None, rule=None):
    return [p for p in props if (typ is None or p.action.get("type") == typ) and (rule is None or p.rule == rule)]


# --- the siege rules alone (as tests/test_siege.py) --------------------------------------

def entrance(**kw):
    e = {"id": 1, "x": 20, "y": 9, "z": 100, "kind": "surface", "sealed": True, "fortifications": 3, "posts": 3,
         "carve": 0, "smooth": 0, "dig": 0, "engines_near": 0}
    e.update(kw)
    return e


def siege(*ents):
    return {"scanned": True, "entrances": list(ents) or [entrance()], "engines": [], "ai_engines": 0, "built": 0,
            "planned": 0, "ammo": {}, "operators": 0, "engineers": 0}


def squad(id_, ranged=False, armed=5, **kw):
    q = {"id": id_, "name": f"squad {id_}", "members": 5, "power": {"armed": armed, "power": 10},
         "ai_orders": 0, "orders": 0}
    if ranged:
        q["ai_uniform"] = "AI crossbow"
    q.update(kw)
    return q


def sfort(sg, squads, threats=(), traits=None) -> dict:
    s = copy.deepcopy(BASE)
    s["siege"] = sg
    s["settings"]["traits"] = dict(traits or {})
    s["dwarves"]["total"] = 40
    s["military"]["squads"] = squads
    s["others_on_map"]["threats"] = [dict(t) for t in threats]
    return digest.normalize(s)


def srun(s, memory=None):
    props, notes = [], []
    PS._siege_rules(s, memory or Memory(), CFG, props, notes)
    return props, notes


GOBLIN = {"id": 50, "name": "goblin", "invader": True, "can_reach_dwarves": False, "layer": "upper_levels"}
BEAST = {"id": 60, "name": "Ozsit the forgotten beast", "great_danger": True, "can_reach_dwarves": False,
         "layer": "upper_levels"}


@test("a besieger in the bridge's 'upper_levels' layer is a gate invader (it never was: archers never posted)")
def _():
    s = sfort(siege(), [squad(1, ranged=True)], [GOBLIN])
    assert [t["id"] for t in PG.gate_invaders(s)] == [50]
    props, _ = srun(s)
    assert acts(props, "archer_post"), [(p.rule, p.action) for p in props]
    # a cavern creature is still none
    s = sfort(siege(), [squad(1, ranged=True)], [dict(GOBLIN, layer="Cavern 1")])
    assert not PG.gate_invaders(s)


@test("archers: a great beast held off outside the gates: the crossbows behind the fortifications; a fire "
      "breather: none (fire passes through them)")
def _():
    props, _ = srun(sfort(siege(), [squad(1, ranged=True), squad(2)], [BEAST]))
    post = acts(props, "archer_post")
    assert post and post[0].action["squads"] == [1] and "Ozsit" in post[0].reason, props
    props, notes = srun(sfort(siege(), [squad(1, ranged=True)], [dict(BEAST, fire_breather=True)]))
    assert not acts(props, "archer_post") and any("fire breather" in n for n in notes), notes
    # one that can reach the dwarves is no siege beast: the shelter and the squads' rules have it
    props, _ = srun(sfort(siege(), [squad(1, ranged=True)], [dict(BEAST, can_reach_dwarves=True)]))
    assert not acts(props, "archer_post")


@test("archers: only squads with bolts are posted; none with bolts: said, none posted")
def _():
    dry = squad(1, ranged=True, power={"armed": 5, "power": 10, "ranged": 0})
    wet = squad(2, ranged=True, power={"armed": 5, "power": 10, "ranged": 4})
    props, _ = srun(sfort(siege(), [dry, wet], [GOBLIN]))
    assert acts(props, "archer_post")[0].action["squads"] == [2]
    props, notes = srun(sfort(siege(), [dry], [GOBLIN]))
    assert not acts(props, "archer_post") and any("no bolts" in n for n in notes), notes


@test("fortifications: once a siege or a great beast has been seen they are carved, crossbows or not; "
      "never seen: none (as before)")
def _():
    sg = siege(entrance(fortifications=0, posts=0, smooth=4))
    assert not acts(srun(sfort(sg, []))[0], "fortify_post")
    m = Memory()
    m.culture = {"sieges": 1}
    p = acts(srun(sfort(sg, []), m)[0], "fortify_post")
    assert p and "ready for the next" in p[0].reason, p
    m = Memory()
    m.last_great_tick = 12345
    assert acts(srun(sfort(sg, []), m)[0], "fortify_post")
    # still never during the siege itself
    m = Memory()
    m.culture = {"sieges": 1}
    assert not acts(srun(sfort(sg, [], [GOBLIN]), m)[0], "fortify_post")


# --- the gates: a sortie ------------------------------------------------------------------

def gate(i=1, x=31, y=140, z=173, closed=True):
    return {"id": i, "kind": "surface", "x": x, "y": y, "z": z, "width": 1, "sealed": True, "closed": closed,
            "equipment": [{"id": 500 + i, "kind": "bridge"}], "door_spots": 0,
            "outer": [{"id": 700, "kind": "bridge"}]}


def gsq(i, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": 10, "size": 10, "orders": 0, "ai_orders": 0,
         "routine": "Staggered training", "power": {"power": 5000, "armed": 10}}
    q.update(kw)
    return q


def besieger(i, **kw):
    t = {"id": i, "name": "goblin lasher", "invader": True, "can_reach_dwarves": False, "great_danger": False,
         "layer": "upper_levels", "pos": {"x": 31, "y": 110, "z": 173}, "distance_to_nearest_dwarf": 30}
    t.update(kw)
    return t


def gfort(threats, squads, alarm=True, armed=True) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["military"]["squads"] = squads
    s["civ_alert"] = alarm
    e = s["entrances"]
    e["entrances"] = [gate()]
    e.update(armed=armed, intruders_inside=[], citizens_outside=0)
    return s


SIEGE = [besieger(7000 + i) for i in range(6)]


@test("sortie: armed gates, the civilians sheltered, a squad sent at the besiegers outside: the gates open "
      "(the gatehouse's drawbridge lowered); no squad on them: they stay shut")
def _():
    out = gsq(11, ai_orders=1, kill_ids=[7000, 7001, 7002])
    s = gfort(SIEGE, [out, gsq(12)])
    assert PG.sortie_out(s, CFG) == [7000, 7001, 7002]
    props, _ = plan(s, Memory())
    op = acts(props, "open_gates")
    assert op and "sortie" in op[0].reason, [(p.rule, p.action, p.reason) for p in props if p.rule == "gates"]
    props, _ = plan(gfort(SIEGE, [gsq(11), gsq(12)]), Memory())
    assert not acts(props, "open_gates")


@test("sortie: never with the alarm down, never with a great danger outside no squad goes at, never for a "
      "squad holding the gate or sheltering")
def _():
    out = gsq(11, ai_orders=1, kill_ids=[7000])
    assert PG.sortie_out(gfort(SIEGE, [out], alarm=False), CFG) == []
    titan = besieger(7100, invader=False, great_danger=True, name="Bax the titan")
    assert PG.sortie_out(gfort(SIEGE + [titan], [out]), CFG) == []
    assert PG.sortie_out(gfort(SIEGE + [titan], [gsq(11, ai_orders=1, kill_ids=[7100])]), CFG) == [7100]
    assert PG.sortie_out(gfort(SIEGE, [gsq(11, ai_orders=1, kill_ids=[7000], guarding=True)]), CFG) == []
    assert PG.sortie_out(gfort(SIEGE, [gsq(11, ai_orders=1, kill_ids=[7000], sheltering=True)]), CFG) == []
    # enemies inside the fort are no sortie
    s = gfort([besieger(7000, can_reach_dwarves=True)], [out])
    s["entrances"]["intruders_inside"] = [7000]
    assert PG.sortie_out(s, CFG) == []


@test("sortie: the gates the AI opened for it stay open while the squads are out (said); back home: armed; "
      "squads sent at enemies that can reach the dwarves are no sortie (the watcher keeps those gates)")
def _():
    out = gsq(11, ai_orders=1, kill_ids=[7000, 7001])
    m = Memory()
    assert acts(plan(gfort(SIEGE, [out]), m)[0], "open_gates") and m.atlas.get("sortie")
    reach = [besieger(7000 + i, can_reach_dwarves=True, distance_to_nearest_dwarf=12) for i in range(6)]
    props, notes = plan(gfort(reach, [out], armed=False), m)
    assert not acts(props, "arm_gates"), [(p.rule, p.action) for p in props if p.rule == "gates"]
    assert any("sortie" in n for n in notes), [n for n in notes if "gate" in n][:6]
    props, _ = plan(gfort(reach, [gsq(11)], armed=False), m)
    assert acts(props, "arm_gates") and not m.atlas.get("sortie")
    # the ordinary defence: no sortie record, squads at enemies in reach: the gates are armed
    props, _ = plan(gfort(reach, [out], armed=False), Memory())
    assert acts(props, "arm_gates")
    props, _ = plan(gfort(reach, [out]), Memory())
    assert not acts(props, "open_gates")


@test("sortie: the AI gate lever the AI pulled shut is pulled back open to let the squads out")
def _():
    out = gsq(11, ai_orders=1, kill_ids=[7000])
    s = gfort(SIEGE, [out])
    s["military"]["gates"] = [{"id": 900, "name": "AI gate", "linked": True, "shut": True}]
    m = Memory()
    m.gate_closed_by_ai = True
    props, _ = plan(s, m)
    pull = acts(props, "pull_gate")
    assert pull and pull[0].action["lever_id"] == 900 and "sortie" in pull[0].reason, \
        [(p.rule, p.action) for p in props if p.rule == "gate"]


# --- squads train while the enemies are about ---------------------------------------------

@test("training: enemies in reach and a squad off duty, not sent: on training; the player's off-duty squad "
      "(the AI trained it before, not its own rest) stays")
def _():
    reach = [besieger(7000, can_reach_dwarves=True, distance_to_nearest_dwarf=40)]
    sq = [gsq(11, routine="Off duty", power={"power": 0, "armed": 0}), gsq(12, routine="Off duty",
                                                                             power={"power": 0, "armed": 0})]
    s = gfort(reach, sq, alarm=False, armed=False)
    s["dwarves"]["total"] = 8                 # a small fort: every pair of hands, in peace
    m = Memory()
    m.squads_trained = [12]
    props, _ = plan(s, m)
    tr = [p for p in props if p.rule == "train" and p.action.get("type") == "squad_routine"]
    assert [p.action["squad_id"] for p in tr] == [11], [(p.action, p.reason) for p in tr]
    assert "training" in tr[0].action["routine"].lower() and "enemies" in tr[0].reason
    m.squads_rested = [12]                    # the AI's own rest: ends now
    props, _ = plan(s, m)
    tr = [p for p in props if p.rule == "train" and p.action.get("type") == "squad_routine"]
    assert sorted(p.action["squad_id"] for p in tr) == [11, 12], [(p.action, p.reason) for p in tr]


# --- the kill zone and its cages ----------------------------------------------------------

@test("kill zone: the zone the enemy comes to: what it has ready, said (traps, full ones, the drawbridge, "
      "TRAPAVOID)")
def _():
    kz = {"entrances": [{"id": 3, "kind": "surface", "x": 10, "y": 10, "z": 100, "state": "standing",
                         "traps": {"planned": 4, "built": 4, "full": 1},
                         "drawbridge": {"id": 88, "built": True, "linked": False}}],
          "threats": [{"id": 7000, "invader": True, "entrance_id": 3, "trapavoid": False}]}
    notes = []
    PK._facing_notes(kz, PK._rows(kz), notes)
    assert len(notes) == 1 and "4 of 4" in notes[0] and "1 full" in notes[0] and "no lever" in notes[0], notes
    kz["threats"] = [{"id": 7100, "great": True, "entrance_id": 3, "trapavoid": True}]
    kz["entrances"][0]["drawbridge"]["linked"] = True
    notes = []
    PK._facing_notes(kz, PK._rows(kz), notes)
    assert "TRAPAVOID" in notes[0] and "raised with the gates" in notes[0], notes
    kz["threats"] = [{"id": 7100, "great": True, "entrance_id": 9}]
    notes = []
    PK._facing_notes(kz, PK._rows(kz), notes)
    assert not notes


@test("cage traps re-armed during a siege: full ones get an animal stockpile and empty cages")
def _():
    reach = [besieger(7000, can_reach_dwarves=True)]
    s = gfort(reach, [gsq(11)])
    s.setdefault("hazards", {}).update(cage_traps=4, cage_traps_full=2, free_cages=0, animal_piles=0)
    props, _ = plan(s, Memory())
    assert acts(props, "work_order", "cages"), [(p.rule, p.action) for p in props if "cage" in p.rule]
    # the rule asks for the animal stockpile too (placed on the surface: the
    # cycle's select may hold that until the siege is gone)
    from planner_military import _hazard_rules
    from planner_core import player_rules
    props, notes = [], []
    _hazard_rules(digest.normalize(s), Memory(), CFG, props, notes, player_rules(s))
    assert acts(props, "place_surface", "cages") and acts(props, "work_order", "cages"), \
        [(p.rule, p.action) for p in props]


finish()
