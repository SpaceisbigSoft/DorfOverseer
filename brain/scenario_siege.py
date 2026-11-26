"""(R29 W2, Phase 11) A siege played through the planner without the game.

No fort had ever had a real siege, so the defence's pieces had never been
seen working together. This feeds the brain a fort (tests/fixtures/
test_fort.json, with the siege, field watch, kill zone and shelter sections
a live bridge sends) through a whole siege, cycle by cycle, with the bridge
faked (every action answered ok, its effect written into the next report),
and checks the whole response:

  0. the Rules' "Invite a siege (test)" on, no enemy about: one invite_siege
     action; its answer is a journal line and the record; the switch off
     (the bridge's doing) and no second invitation;
  0b. (0.105.123) an invitation waiting: looked at daily with the switch off;
     no army in 7 days: the next civ's line; none from 3 civs: "DF sent no
     army: tried X, Y, Z"; then the switch on again: a new invitation (not
     refused); an army that came: again once it is over (0.105.127); the 30-day line names
     the civs tried; the fallback's war party placed at the map edge: its
     journal line, and the watch takes it as the invited siege;
  1. the army at the map edge, 60 tiles off, citizens outside: the alarm
     (the shelter burrow made first when there is none), the gates armed and
     NOT shut (gates close late: danger within 12 tiles or everyone inside),
     the squads: a strong fort sends the strongest at them, a weak one holds
     the gate they come at (behind its kill zone) instead of staying put;
  2. 10 tiles off, the gate shut by the watcher: the watch records it shut
     with the nearest enemy 10 tiles away; a broken watcher: the AI shuts
     that gate itself (close_threatened_gates);
  3. fighting at the gate (the atlas' located events: threats at the gate,
     kills, a death);
  4. the army gone half a day: the siege summary in the journal: survived,
     deaths, kills, each gate's record, the alarm, the shelter, the squads,
     the field watch.

    python brain/scenario_siege.py          # prints each check, exits 1 on a failure
    tests/test_r29_siege.py runs the same checks.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from planner import Memory, PLANNER_CONFIG, plan, select  # noqa: E402
from planner_cycle import note_cycle  # noqa: E402
from planner_record import record  # noqa: E402
import atlas  # noqa: E402
from planner_siege_watch import siege_journal  # noqa: E402

FIXTURE = HERE.parent / "tests" / "fixtures" / "test_fort.json"
DAY = 1200
GATE = {"x": 31, "y": 140, "z": 173}
CIV = "The Devil of Scalding"


def base_state(invite: bool = False, ready: bool = True, power: float = 500.0) -> dict:
    """The test fort with the sections a live 0.105.121 bridge sends for a siege."""
    s = json.loads(FIXTURE.read_text(encoding="utf-8"))
    s["date"]["tick"] = 100 * DAY
    s["settings"]["invite_siege"] = invite
    s["civ_alert"] = False
    s["civ_alert_ready"] = ready
    if ready:
        s["civ_alert_shelter"] = "AI shelter"
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["entrances"]["armed"] = False
    s["entrances"]["entrances"][0].update(closed=False, id=1, kind="surface", **GATE)
    for q in s["military"]["squads"]:
        q["power"] = {"power": power, "armed": q.get("members") or 10}
    s["siege"] = {"scanned": True, "entrances": [dict(GATE, id=1, kind="surface", sealed=True, fortifications=3,
                                                       posts=3, carve=0, smooth=0, dig=0, engines_near=0)],
                  "engines": [], "ai_engines": 0, "built": 0, "planned": 0, "all_built": 0,
                  "ammo": {"siege_ammo": 0, "ballista_parts": 0, "catapult_parts": 0, "arrowheads": 0},
                  "shops": 0, "operators": 2, "engineers": 2}
    s["field_watch"] = {"merchants": 0, "caravan": [], "wild": [], "wild_total": 0, "citizens_outside": 4}
    s["killzones"] = {"scanned": True, "entrances": [dict(GATE, id=1, kind="surface", sealed=True, state="standing",
                                                           fortifications=3, posts=3)],
                      "threats": [], "free_mechanisms": 2, "free_cages": 0, "trap_weapons": 0, "mechanics": 2}
    return s


def army(n: int, dist: int, reach: bool = True) -> list:
    """n goblins in a line west of the gate, `dist` tiles off (dist 60: the map edge)."""
    return [{"id": 7000 + i, "name": f"Snodub Ostuthsmata, goblin lasher {i}", "invader": True,
             "great_danger": False, "can_reach_dwarves": reach, "layer": "upper_levels", "size": 60000,
             "pos": {"x": max(0, GATE["x"] - dist), "y": GATE["y"] + (i % 3) - 1, "z": GATE["z"]},
             "distance_to_nearest_dwarf": dist, "levels_from_nearest_dwarf": 0} for i in range(n)]


def at(s: dict, day: float, threats: list, **kw) -> dict:
    s = copy.deepcopy(s)
    s["date"]["tick"] = int((100 + day) * DAY)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["killzones"]["threats"] = [{"id": t["id"], "name": t["name"], "pos": t["pos"]} for t in threats]
    for k, v in kw.items():
        s[k] = v
    return s


def fake_bridge(chosen: list, state: dict, invite_answer: dict | None = None) -> list:
    """Every action answered ok, as the bridge would (invite_answer: the
    invite_siege action's answer instead of a new invitation's)."""
    out = []
    for p in chosen:
        a = p.action
        if a.get("type") == "invite_siege" and invite_answer is not None:
            out.append((p, dict(invite_answer)))
        elif a.get("type") == "invite_siege":
            out.append((p, {"ok": True, "civ_id": 314, "civ_name": CIV, "race": "GOBLIN", "relation": "TotalWar",
                            "event": "EvaluateAttackAndSendImmediateArmy", "how": "force", "queued": 1,
                            "tick": state["date"]["year"] * 403200 + state["date"]["tick"],
                            "year": state["date"]["year"]}))
        else:
            out.append((p, {"ok": True}))
    return out


def cycle(s: dict, m: Memory, events: list | None = None, invite_answer: dict | None = None):
    """One overseer cycle: note_cycle, the atlas, plan, select, the fake bridge, record."""
    note_cycle(s, m)
    atlas.note_entrances(s, m)
    atlas.note_events(s, m, events or [])
    props, notes = plan(s, m)
    chosen, _held = select(props, s, m)
    results = fake_bridge(chosen, s, invite_answer)
    record(results, s, m)
    return props, chosen, notes


def _types(ps) -> list:
    return [p.action.get("type") for p in ps]


def _check(out: list, name: str, ok: bool, why: str = "") -> None:
    out.append((name, bool(ok), why))


def run() -> list:
    """Every check: [(name, passed, detail)]."""
    out: list = []
    m = Memory()

    # 0. the invitation, once
    s0 = base_state(invite=True)
    props, chosen, _ = cycle(s0, m)
    _check(out, "0 invite: one invite_siege while no enemy is about", _types(chosen).count("invite_siege") == 1,
           str(_types(props)))
    jr = siege_journal(m)
    _check(out, "0 invite: a clear journal line", any(e.get("what") == "siege_invited" and CIV in e.get("text", "")
                                                       for e in jr), str(jr)[:300])
    rec = dict(m.holdfast.get("invited") or {})
    s1 = at(base_state(invite=False), 0.5, [])
    s1["field_watch"]["invited"] = {"tick": rec.get("tick"), "year": 148, "civ_name": CIV, "race": "GOBLIN",
                                    "relation": "TotalWar", "how": "force"}
    props, chosen, _ = cycle(s1, m)
    _check(out, "0 invite: the switch off: no second invitation", "invite_siege" not in _types(props))
    s1b = copy.deepcopy(s1)
    s1b["settings"]["invite_siege"] = True
    props, _, _ = cycle(s1b, m)
    again = [p for p in props if p.action.get("type") == "invite_siege"]
    _check(out, "0 invite: switched on again: a new test once the last is over (0.105.127)", len(again) == 1
           and "the last invited siege came" in again[0].reason, str([p.reason for p in again]))

    # 0b. (0.105.123) waiting, the next civ, no army, the re-invite
    out.extend(_invite_flow())

    # 1. the army at the map edge, citizens outside
    base = copy.deepcopy(s1)
    s2 = at(base, 3, army(15, 60))
    props, chosen, notes = cycle(s2, m)
    t = _types(props)
    _check(out, "1 edge: the alarm sounds", any(p.action == {"type": "civ_alert", "on": True} for p in props), str(t))
    arm = [p for p in props if p.action.get("type") == "arm_gates"]
    _check(out, "1 edge: the gates armed with the late-closing rule", bool(arm) and "12 tiles" in arm[0].reason,
           str([p.reason for p in arm]))
    _check(out, "1 edge: no gate shut yet (60 tiles off, citizens outside)",
           not {"close_threatened_gates", "close_gates"} & set(t), str(t))
    kills = [p for p in props if p.action.get("type") == "squad_orders" and p.action.get("kill")]
    _check(out, "1 edge (strong squads): the strongest squad goes at them", bool(kills), str(t))
    _check(out, "1 edge: the watch began", isinstance(m.holdfast.get("siege_watch"), dict)
           and m.holdfast["siege_watch"].get("invited", {}).get("civ") == CIV, str(m.holdfast.get("siege_watch"))[:200])

    # 1b. no shelter yet: the burrow first
    s2b = at(base_state(ready=False), 3, army(15, 60))
    s2b.pop("civ_alert_shelter", None)
    props, _, _ = cycle(s2b, Memory())
    _check(out, "1 edge (no shelter): the shelter burrow is made for the alarm",
           any(p.action.get("type") == "setup_shelter" for p in props), str(_types(props)))

    # 1c. weak squads: they hold the gate the army comes at, behind its kill zone
    s2c = at(base_state(power=5.0), 3, army(15, 60))
    s2c["entrances"]["armed"] = True
    props, _, notes2 = cycle(s2c, Memory())
    hold = [p for p in props if p.action.get("type") == "guard_gate"]
    _check(out, "1 edge (weak squads): no sortie, the squads hold that gate behind its kill zone",
           bool(hold) and hold[0].action.get("x") == GATE["x"] and "kill zone" in hold[0].reason
           and not [p for p in props if p.action.get("kill")], str([p.reason for p in hold] or notes2[-3:])[:300])

    # 2. 10 tiles off: the gate shut by the watcher
    ent = copy.deepcopy(base["entrances"])
    ent["armed"] = True
    ent["entrances"][0]["closed"] = True
    ent["citizens_outside"] = 0
    s3 = at(base, 3.5, army(15, 10), entrances=ent, civ_alert=True)
    for q in s3["military"]["squads"][:1]:
        q.update(ai_orders=1, orders=1, kill_ids=[7000 + i for i in range(15)])
    m.ai_alert_raised = True
    cycle(s3, m)
    g = (m.holdfast.get("siege_watch") or {}).get("gates", {}).get("1", {})
    _check(out, "2 near: the watch records the gate shut with the enemy 10 tiles off",
           g.get("closed") is True and g.get("closed_near") == 10, str(g))
    ent2 = copy.deepcopy(ent)
    ent2["entrances"][0]["closed"] = False
    ent2["watch_error"] = {"error": "the gate watcher stopped"}
    s3b = at(base, 3.5, army(15, 10), entrances=ent2, civ_alert=True)
    props, _, _ = cycle(s3b, copy.deepcopy(m))
    _check(out, "2 near (watcher broken): the AI shuts the threatened gate itself",
           "close_threatened_gates" in _types(props), str(_types(props)))

    # 3. the fight at the gate: kills and a death by the gate
    ev = [{"kind": "death", "hostile": True, "x": GATE["x"] - 2, "y": GATE["y"], "z": GATE["z"],
           "name": "Snodub, goblin lasher 0"},
          {"kind": "death", "hostile": True, "x": GATE["x"] - 1, "y": GATE["y"], "z": GATE["z"],
           "name": "Snodub, goblin lasher 1"},
          {"kind": "death", "own_civ": True, "x": GATE["x"] - 1, "y": GATE["y"] + 1, "z": GATE["z"],
           "name": "Urist McAxedwarf"}]
    near = army(13, 2)
    for i, tt in enumerate(near):
        tt["id"] = 7002 + i
    s4 = at(base, 4, near, entrances=ent, civ_alert=True)
    cycle(s4, m, ev)

    # 4. gone: half a day later the summary
    s5 = at(base, 4.3, [], entrances=ent, civ_alert=True)
    cycle(s5, m)
    _check(out, "4 end: no summary before half a day without invaders",
           not [e for e in siege_journal(m) if e.get("what") == "siege_summary"])
    s6 = at(base, 5, [], entrances=ent, civ_alert=True)
    s6["dwarves"]["total"] = s6["dwarves"].get("total", 50) - 1
    cycle(s6, m)
    js = [e for e in siege_journal(m) if e.get("what") == "siege_summary"]
    e = js[0] if js else {}
    _check(out, "4 end: one siege summary in the journal", len(js) == 1, str(js)[:300])
    _check(out, "4 end: survived, 1 death, 2 kills, 15 invaders, invited",
           e.get("survived") is True and e.get("deaths") == 1 and e.get("kills") == 2 and e.get("invaders") == 15
           and e.get("invited") and e.get("civ") == CIV, json.dumps({k: e.get(k) for k in
                                                                    ("survived", "deaths", "kills", "invaders",
                                                                     "invited", "civ")}))
    g1 = next((x for x in e.get("gates") or [] if x.get("id") == 1), {})
    _check(out, "4 end: the gate's record: shut 10 tiles off, threats, deaths and kills there, its kill zone",
           g1.get("closed") and g1.get("closed_near") == 10 and g1.get("threats", 0) >= 1 and g1.get("deaths") == 1
           and g1.get("kills") == 2 and g1.get("killzone") == "standing", str(g1))
    _check(out, "4 end: the alarm, the shelter, the squads and the field watch reported",
           e.get("alarm") is True and e.get("shelter") == "AI shelter" and e.get("squads")
           and "field_watch" in e and "Siege over" in str(e.get("text")), str(e.get("text"))[:400])
    _check(out, "4 end: the watch is closed", "siege_watch" not in m.holdfast)
    return out


CIV2, CIV3 = "The Witch of Hardiness", "The Third Horde"


def _waiting(day: float, tries: list, state: str = "waiting", invite: bool = False) -> dict:
    s = at(base_state(invite=invite), day, [])
    t0 = _t0()
    s["field_watch"]["invited"] = {"tick": t0, "year": 148, "invitation": 1, "state": state,
                                   "civ_name": tries[-1], "how": "force",
                                   "tries": [{"civ_name": c, "tick": t0} for c in tries]}
    return s


def _t0() -> int:
    """The invitation's tick (absolute: year * 403200 + the year's tick), day 0."""
    return base_state()["date"]["year"] * 403200 + 100 * DAY


def _invite_flow() -> list:
    out: list = []
    m = Memory()
    s = _waiting(1, [CIV])
    props, chosen, _ = cycle(s, m, invite_answer={"ok": True, "waiting": True, "quiet": True, "state": "waiting",
                                                   "tick": _t0(), "civ_name": CIV, "tried": [CIV]})
    j = [e for e in siege_journal(m) if str(e.get("what", "")).startswith("siege_")]
    _check(out, "0b waiting: looked at with the switch off, and quietly",
           _types(chosen).count("invite_siege") == 1 and not j, str(_types(props)) + str(j)[:300])
    props, chosen, _ = cycle(_waiting(1.5, [CIV]), m)
    _check(out, "0b waiting: once a day at most", "invite_siege" not in _types(chosen), str(_types(chosen)))
    retry = {"ok": True, "retried": True, "no_army": CIV, "state": "waiting", "tick": _t0(), "civ_id": 304,
             "civ_name": CIV2, "race": "GOBLIN", "relation": "Skirmishing", "how": "force", "entity_set": True,
             "tried": [CIV, CIV2]}
    cycle(_waiting(8, [CIV]), m, invite_answer=retry)
    j = siege_journal(m)
    _check(out, "0b 7 days, no army: the next civ's journal line",
           any(e.get("what") == "siege_invite_retried" and CIV in e["text"] and CIV2 in e["text"]
               and "read back: set" in e["text"] for e in j), str(j)[:300])
    gave = {"ok": True, "gave_up": True, "no_army": CIV3, "state": "no_army", "tick": _t0(),
            "civ_name": CIV3, "tried": [CIV, CIV2, CIV3]}
    cycle(_waiting(23, [CIV, CIV2, CIV3]), m, invite_answer=gave)
    j = siege_journal(m)
    _check(out, "0b none from 3 civs: \"DF sent no army: tried X, Y, Z\"",
           any(e.get("what") == "siege_invite_no_army" and f"DF sent no army: tried {CIV}, {CIV2}, {CIV3}" in e["text"]
               for e in j), str(j)[:300])
    props, _, _ = cycle(_waiting(24, [CIV, CIV2, CIV3], state="no_army"), m)
    _check(out, "0b ended with no army, switch off: nothing", "invite_siege" not in _types(props), str(_types(props)))
    cycle(_waiting(31, [CIV, CIV2, CIV3], state="no_army"), m)
    _check(out, "0b ended with no army: no 30-day line on top", not siege_journal(m))
    props, _, _ = cycle(_waiting(25, [CIV, CIV2, CIV3], state="no_army", invite=True), Memory())
    inv = [p for p in props if p.action.get("type") == "invite_siege"]
    _check(out, "0b switch on again after no army: a new invitation, not a refusal",
           len(inv) == 1 and "refuses" not in inv[0].reason and "again" in inv[0].reason, str([p.reason for p in inv]))
    props, _, _ = cycle(_waiting(25, [CIV2], state="came", invite=True), Memory())
    inv = [p for p in props if p.action.get("type") == "invite_siege"]
    _check(out, "0b an invitation that brought an army: again once it is over, a bigger party (0.105.127)",
           len(inv) == 1 and "bigger war party" in inv[0].reason, str([p.reason for p in inv]))
    m2 = Memory()
    cycle(_waiting(31, [CIV, CIV2], state="came"), m2, invite_answer={"ok": False, "rejected": True, "error": "x"})
    j = [e for e in siege_journal(m2) if e.get("what") == "siege_no_show"]
    _check(out, "0b 30 days, none on the map: the line names the civs tried",
           len(j) == 1 and f"tried {CIV}, {CIV2}" in j[0]["text"] and "set out" in j[0]["text"], str(j)[:300])
    m4 = Memory()
    placed = {"ok": True, "gave_up": True, "no_army": CIV2, "state": "came", "tick": _t0(), "civ_name": CIV,
              "tried": [CIV, CIV2], "spawned": {"count": 16, "civ_id": 314, "civ_name": CIV, "race": "GOBLIN",
                                                "x": 287, "y": 1, "z": 176, "equipped": True}}
    cycle(_waiting(15, [CIV, CIV2]), m4, invite_answer=placed)
    j = siege_journal(m4)
    _check(out, "0b the fallback: \"No army came: placed 16 goblins of X at the map edge (the siege test)\"",
           any(e.get("what") == "siege_spawned" and f"No army came: placed 16 goblins of {CIV} at the map edge "
               "(the siege test)" in e["text"] for e in j), str(j)[:300])
    s = at(_waiting(15.2, [CIV, CIV2], state="came"), 15.2, army(16, 170))
    s["field_watch"]["invited"].update(civ_name=CIV, spawned=placed["spawned"])   # the bridge's record names the party's civ
    cycle(s, m4)
    _check(out, "0b the placed party is watched as the invited siege",
           (m4.holdfast.get("siege_watch") or {}).get("invited", {}).get("civ") == CIV,
           str(m4.holdfast.get("siege_watch"))[:200])
    m3 = Memory()
    s = at(_waiting(3, [CIV]), 3, army(4, 50))
    cycle(s, m3, invite_answer={"ok": True, "waiting": True, "quiet": True, "state": "waiting", "tick": _t0()})
    props, _, _ = cycle(_waiting(5, [CIV]), m3)
    came = [p for p in props if p.action.get("type") == "invite_siege"]
    _check(out, "0b invaders seen while it waits: the look says so (came)",
           len(came) == 1 and came[0].action.get("came") is True, str([p.action for p in came]))
    return out


def main() -> int:
    res = run()
    bad = 0
    for name, ok, why in res:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{why}]"))
        bad += not ok
    print(f"{len(res) - bad} of {len(res)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    PLANNER_CONFIG.setdefault("siege_watch_end_ticks", DAY // 2)
    sys.exit(main())
