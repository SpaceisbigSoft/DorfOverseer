"""planner_military: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_gates import *  # noqa: F401,F403  (13c: split out by theme)
from planner_matchup import facts_mult, judge, matchup  # noqa: F401  (0.105.45) a threat against the squads
from planner_military_squads import *  # noqa: F401,F403  (r7: split out by theme)
from planner_military_squads import _shelter_possible, _shelter_due, _no_shelter_note, _soldiers_wanted, _train_mode_held, _training_rotation, _bowyer_rule, _crossbow_order, _ranged_squad_rule, _uniform_weapon_rule, _anvil_rule, _one_enemy_hold, _lone_squad  # noqa: F401  (* skips the underscored names)
from planner_military_threats import *  # noqa: F401,F403  (r7: split out by theme)
from planner_military_threats import _base_power, _players, _note_fight, _fight_outcome, _crossing_rule, _alerts_rule, _war_animal_rule, _hazard_rules, _no_melee_beasts, _shoots  # noqa: F401  (* skips the underscored names)

__all__ = ["called_off_ids", "FIGHT_FACTOR_MAX", "lone_intruders", "hunted_outside", "few_ordinary", "few_alert_over", "ai_gates_shut", "lockdown_released", "lone_alert_over", "note_lockdown", "_lone_squad", "quick_clear", "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule", "GEAR_HELD", "_shelter_possible", "no_shelter", "SHELTER_RETRY_DAYS", "SHELTER_RETRY_THREAT_DAYS", "_shelter_due", "_no_shelter_note", "weak_squad", "soldier_share", "_gate_rules", "_free_gate_levers", "_lever_far_enough", "_link_wanted", "_lever_rule", "_trap_rule", "_gatehouse_rule", "_lever_hatches_ok", "_near_spot", "soldiers_wanted", "civilian_cap", "crossing_value", "_crossing_rule", "ALERT_DANGERS", "alert_ages", "_alerts_rule", "_war_animal_rule", "hazard_alert", "_hazard_rules", "_military_rules", "watched_gate_levers", "_training_rotation", "_ranged_squad_rule", "note_ranged_need", "crossbows_wanted", "_bowyer_rule", "_crossbow_order", "WEAPON_IDS", "_uniform_weapon_rule", "_anvil_rule", "idle_hands"]


def _military_rules(s: dict, memory, cfg: dict, traits: dict, citizens: int,
                    proposals: list, notes: list, gate_rules: bool = True) -> None:
    """(0.105.48, K6) gate_rules=False: plan() runs _gate_rules itself, under
    its own guard and without the military section."""
    mil, rules_ = s["military"], player_rules(s)
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict)]
    threats = {t.get("id"): t for t in _l(s["others_on_map"].get("threats")) if isinstance(t, dict)}
    reach = [i for i in reachable_threats(s, traits, cfg) if i in threats]
    any_reach = bool(reachable_threats(s, traits, cfg))

    # The gate: a lever the player named "AI gate". Pulled when a threat can
    # reach the dwarves, pulled back once it has been quiet for a while.
    # The fort's own entrances: found, closed and opened by the AI itself.
    # (0.97) mapping, walls, doors and traps run whatever gate_lever says (each
    # has its own switch); gate_lever is only closing gates and their levers
    if gate_rules and "entrances" in s and "entrances" not in s["_errors"]:
        _gate_rules(s, memory, cfg, rules_, any_reach, proposals, notes, traits)
    # A lever the player named "AI gate" and linked to something: pulled too.
    gates = [g for g in _l(mil.get("gates")) if isinstance(g, dict) and not g.get("pending") and g.get("linked")]
    # (one linked to an entrance's drawbridge is the gate watcher's to pull)
    watched = watched_gate_levers(s)
    gates = [g for g in gates if g.get("id") not in watched]
    # (0.105.3) not for a lone intruder inside, nor after the lockdown was lifted
    lone = lone_intruders(s, cfg, traits, memory) if any_reach else []
    open_up = bool(lone) or lockdown_released(memory) or bool(any_reach and hunted_outside(s, cfg, traits, memory)
                                                              and not _one_enemy_hold(s, cfg, memory, traits))
    # (0.105.54) the squads out on a sortie (planner_gates.sortie_out): the AI gate lever lets them out too
    from planner_gates import sortie_out
    sortie = bool(sortie_out(s, cfg, memory)) and not lone
    open_up = open_up or sortie
    if rules_["gate_lever"] and gates:
        # (0.105.36) never pulled while the report says the gate is already
        # shut (the player's, or the AI's own not yet read back)
        if any_reach and not memory.gate_closed_by_ai and not open_up and gates[0].get("shut") is not True:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "a threat can reach the dwarves: pull the AI gate lever", 0))
        elif memory.gate_closed_by_ai and sortie:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "the squads sortie against the enemies outside, the civilians in the "
                                      "shelter: pull the AI gate lever back (open) to let them out", 0))
        elif memory.gate_closed_by_ai and any_reach and open_up:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "only a few enemies left, inside the fort, or no new one for days: pull "
                                      "the AI gate lever back (open)", 0))
        elif (not any_reach and memory.gate_closed_by_ai and gates
              and (all_clear(s, memory, cfg)[0] or quick_clear(s, memory, cfg))):     # (0.105.3)
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      f"no threat for {memory.quiet_cycles} cycles: pull the AI gate "
                                      "lever back", 1))

    # Squads at threats: kill orders the AI gives, and clears again.
    able = [q for q in squads if can_fight(q, cfg)]
    policy = rules_["attack_policy"]
    # (0.105.40b) a fire breather is no melee squad's target, great or not
    # (planner_firebreath: crossbows from inside only, and the note why)
    fire = {i for i in reach if threats[i].get("fire_breather") is True and policy != "all"}
    # (0.105.54, "fight back") nor a great beast whose breath, dust or webs make
    # closing in suicidal: crossbows from a safe spot only (_no_melee_beasts)
    cloud = no_melee_great(threats, reach, policy) - fire
    great = [i for i in reach if threats[i].get("great_danger") and i not in fire and i not in cloud]
    # (0.104.118, phase 11) a great danger is fought when the squads are
    # strong enough for it (judged), else the dwarves hide behind shut gates
    fight, verdict = fight_or_hide(s, memory, cfg, [threats[i] for i in great], able) if great else (False, "")
    # (0.105.26) a great danger whose fight was called off: never a target
    # again while it's on the map (since 0.105.48 under attack everything too)
    off = called_off_ids(s, memory)
    # (0.105.48 K1b, audit A6 #6) "attack everything" lowers the bar, it does
    # not remove the retreat: a fight called off for its losses is off under
    # `all` too (War-hold: six squads sent at a titan with deadly dust, never
    # called back however many fell)
    # (0.105.51) a wild pack the free squads don't beat (planner_core.wild_pack):
    # the alarm keeps the civilians in, no sortie at it (under `ordinary`)
    wp = wild_pack(s, cfg)
    no_sortie = set(wp["ids"]) if wp["danger"] and not wp["fight"] else set()
    targets = [i for i in reach if (policy == "all" and i not in off)
               or (policy == "ordinary" and i not in off and i not in fire and i not in no_sortie
                   and i not in cloud and (not threats[i].get("great_danger") or fight))]
    # (0.105.51) a thief among a crowd (a tavern of guests) is no defence target:
    # the thieves rule posts a squad to wait for them (E, 15 Nov: three tavern fights)
    from planner_core import thief_rows, crowded_thief
    crowd = {x.get("id") for x in thief_rows(s) if crowded_thief(x, cfg)}
    if crowd & set(targets):
        targets = [i for i in targets if i not in crowd]
    recalled = set()
    held_back = [i for i in reach if i not in targets and i not in fire and i not in no_sortie and i not in crowd
                 and i not in cloud]
    if no_sortie and policy == "ordinary":
        notes.append(f"{wp['danger']}: the squads stay in")
    # (0.105.48, K16) a squad out on a great danger the squads can no longer
    # take (more came, the verdict turned: held back, not a target now) comes
    # back as a called-off one does, under every policy; a hunt's party is
    # the hunt rule's (its own retreat)
    lost = {i for i in held_back if threats[i].get("great_danger")} - off
    # (r1g5) E: the long alarm nobody fought ends in an all-out attack when
    # it isn't hopeless (planner_war_hold.unfought): those enemies are no
    # squad's to be called back from for the odds
    from planner_war_hold import unfought, unfought_proposals
    uf = unfought(s, memory, cfg, reach) if reach else {}
    uf_ids = set(uf.get("ids") or []) if uf.get("mode") == "fight" else set()
    lost -= uf_ids
    if off or lost:
        # (0.105.26) the squads whose kill order names it come back, whatever
        # else is about (hiding() is false with a goblin in reach, and the
        # order on the titan stayed); free, they are sent at the others
        # (0.105.48, K16) to the station or the shelter (planner_army.fall_back)
        from planner_army import fall_back
        from planner_hunt import hunt_rows
        hr = hunt_rows(s)
        hunting = {h.get("squad_id") for h in (hr[2] if hr else [])}
        hunting |= {q.get("id") for q in (hr[1] if hr else []) if isinstance(q, dict) and q.get("hunting") is not None}
        back = []
        for q in squads:
            kill = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
            if not q.get("ai_orders"):
                continue
            if kill & off or (kill & lost and q.get("id") not in hunting and not _players(q)
                              and not kill & set(targets)):
                recalled.add(q.get("id"))
                back.append(q["id"])
        if back:
            why = ("the fight with the great danger was called off" if off else
                   f"the squads are too weak now for the great danger(s) they were sent at ({verdict})")
            proposals.extend(fall_back(s, cfg, back, why, proposals))
    if great and ((fight and policy == "ordinary") or (policy == "all" and set(great) - off)):
        # (0.104.139) recorded even when the squads were already out at others;
        # (0.105.48 K1b) under `all` too, so its losses are counted and the
        # fight is called off (fight_or_hide) as under `ordinary`
        _note_fight(s, memory, [threats[i] for i in great if policy != "all" or i not in off])
    # (0.105.83) a few ordinary enemies already inside, fliers and wild
    # animals too (B, 23 Nov 14:48: three agitated giant ravens in through the
    # cavern well's shaft killed a planter, a stonecrafter and a child in a
    # minute; the Rules tab sends squads against nothing and a flier is never a
    # "lone intruder", so 37 soldiers stood by): one armed squad, whatever the
    # policy, when nothing else is sent
    if not lone and not targets and reach:
        from planner_leisure import inside_few
        lone = inside_few(s, cfg, reach, threats)
    if lone:
        # (0.105.3) a lone intruder inside: one armed squad, whatever the policy
        _lone_squad(s, memory, cfg, squads, lone, threats, proposals, notes)
    elif targets:
        from planner_holdfast import _inside_ids
        inside_ = _inside_ids(s)
        for q in able:
            if q.get("id") in recalled:
                continue                 # (0.105.26) called back this cycle: sent again next
            if _players(q) and not set(targets) & inside_:
                continue                 # (0.105.48, K16; A6 #17) on the player's own orders: theirs, unless inside
            names = ", ".join(sorted({str(threats[i].get("name") or "?") for i in targets}))[:80]
            # (0.105.0) a squad waiting in the shelter goes out when it's sent
            if not q.get("ai_orders") or q.get("sheltering"):
                proposals.append(Proposal(
                    "squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": targets[:50]},
                    f"{len(targets)} enemies can reach the dwarves ({names}): send {q.get('name') or 'the squad'}", 0))
            elif not q.get("guarding") and isinstance(q.get("kill_ids"), list):
                # (0.104.140) a second wave: enemies in reach the squad's kill
                # order doesn't name (the order was a list made when it went out).
                # (review) The new order keeps the old targets (a berserk dwarf,
                # one behind a gate), and an id once sent isn't new again (one
                # the game refuses, a war animal, would re-order every cycle)
                known = [int(x) for x in q["kill_ids"] if isinstance(x, int) and x not in off]
                sent = {int(x) for x in _l(_d(getattr(memory, "kill_sent", None)).get(str(q["id"])))
                        if isinstance(x, int)}
                new = [i for i in targets[:50] if isinstance(i, int) and i not in known and i not in sent]
                if new:
                    kill = list(dict.fromkeys(known + [i for i in targets if isinstance(i, int)]))[:50]
                    proposals.append(Proposal(
                        "squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": kill},
                        f"{len(new)} more enemies can reach the dwarves ({names}): "
                        f"{q.get('name') or 'the squad'} goes after them too", 0))
        if not able:
            # (0.105.35) said, not asked: the alarm and the gates keep the dwarves
            # in meanwhile, and the squads are filled and armed by the rules below
            notes.append(f"{len(targets)} enemies can reach the dwarves and no squad has "
                         f"{cfg['min_squad_to_fight']}+ armed soldiers to send: the dwarves keep behind the alarm "
                         "and the gates meanwhile, while the squads are filled and armed")
    if uf_ids:
        # (r1g5) the all-out attack: every squad with anyone armed (crossbows
        # only at a beast no melee squad may face), whatever the policy
        ordered = {p.action.get("squad_id") for p in proposals if p.action.get("type") == "squad_orders"}
        proposals.extend(p for p in unfought_proposals(s, uf) if p.action.get("squad_id") not in ordered)
    if cloud:
        _no_melee_beasts(s, memory, cfg, threats, cloud, squads, proposals, notes)
    if held_back and policy != "never":
        notes.append(f"{len(held_back)} great danger(s) (beast, titan...) can reach the dwarves: the dwarves hide "
                     f"behind the gates ({verdict}; Rules tab: attack everything)")
    elif great and fight:
        notes.append(f"{len(great)} great danger(s) can reach the dwarves: the squads go ({verdict})")
    _fight_outcome(s, memory, cfg)
    # (0.104.140) after an attack, once all is clear: the enemies' corpses at
    # the gate rot away now (miasma, a necromancer's fuel), not at the year's end
    lt = int(getattr(memory, "last_threat_tick", 0) or 0)
    if (lt and not any_reach and getattr(memory, "pruned_after", 0) != lt
            and all_clear(s, memory, cfg)[0]):
        proposals.append(Proposal("siege_cleanup", {"type": "prune_remains"},
                                  "the attack is over: the enemies' corpses and remains lying about rot away "
                                  "(entombed dead are kept)", 5))
    # (0.100.1, review) a dwarf gone berserk isn't a threat that "can reach",
    # but the squad sent at them stays on them until they're stopped
    berserk_now = bool(_l(_d(s.get("hazards")).get("berserk")))
    from planner_tantrums import guard_ids          # (0.105.47) the hospital guards
    hospital_guards = guard_ids(s)
    if not any_reach and not berserk_now:
        invaders_near = bool(gate_invaders(s))
        # (0.105.33) a thief inside the game doesn't count as a threat: the
        # squad _thieves sent stays on them (recalled, it was sent again next
        # cycle, and so on, the thief never caught)
        # (0.105.51) the pulse's others_on_map thieves too (thief_rows)
        from planner_core import thief_rows
        thieves_in = {x.get("id") for x in thief_rows(s)
                      if isinstance(x, dict) and x.get("id") is not None
                      and (x.get("inside") or x.get("can_reach_dwarves") is True)}
        # (0.105.51) a squad waiting for a thief in a crowd (planner_threats) stays
        # while a thief is inside; the intruder guard on its post while DF's
        # unseen intruder is about (E, 15 Nov: posted, then recalled here the
        # next cycle, posted again)
        from planner_threats import thief_watchers, unseen_intrusion
        from planner_holdfast import _hf
        posted = {w.get("id") for w in thief_watchers(s, memory)} if thieves_in else set()
        if unseen_intrusion(s, memory, cfg):
            for k, g in _d(_hf(memory).get("guards")).items():
                q = next((q for q in squads if str(q.get("id")) == str(k)), None)
                if q and _d(q.get("stationed")) == {c: _d(g).get(c) for c in ("x", "y", "z")}:
                    posted.add(q.get("id"))
        # (item1, 14 Nov) one DF shows keeping the dwarves from drink and food
        # (planner_threats _interrupters) isn't a threat to the game either
        thieves_in |= {x.get("id") for x in _l(_d(_d(s.get("threats")).get("interrupters")).get("list"))
                       if isinstance(x, dict) and x.get("id") is not None and not x.get("caged")}
        # (0.105.48 K1b, audit A6 #7, #8) a recall respects who sent the squad
        # and why: a squad on a hunt is the hunt rule's (planner_hunt calls it
        # back on losses, wounds or hunt_max_days; recalled here after a day,
        # the bridge closed the hunt as dropped and the next cycle sent it out
        # again), and one sent at a vampire is the killers rule's (recalled
        # the very next cycle, the vampire left alone)
        from planner_hunt import hunt_rows
        from planner_killers import killer_rows
        hr = hunt_rows(s)
        hunting = {h.get("squad_id") for h in (hr[2] if hr else [])}
        hunting |= {q.get("id") for q in (hr[1] if hr else []) if isinstance(q, dict) and q.get("hunting") is not None}
        killers_in = {r["id"] for r in killer_rows(s) if r.get("kind") == "vampire"}
        for q in squads:
            if q.get("guarding") and invaders_near:
                continue                     # (0.104.83) holding the gate while invaders are about
            if thieves_in and set(_l(q.get("kill_ids"))) & thieves_in:
                continue                     # (0.105.33) after a thief still inside
            if q.get("id") in posted:
                continue                     # (0.105.51) waiting for a thief, or the intruder guard
            if q.get("id") in hunting:
                continue                     # (0.105.48) on a hunt: planner_hunt's retreat calls it back
            if killers_in and set(_l(q.get("kill_ids"))) & killers_in:
                continue                     # (0.105.48) after a vampire still here (planner_killers)
            if q.get("sheltering") and s.get("civ_alert"):
                continue                     # (0.105.0) in the shelter until the alarm is over (planner_army)
            if q.get("id") in hospital_guards:
                continue                     # (0.105.47) on guard at a hospital: planner_tantrums takes it off
            if q.get("ai_orders"):
                proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                          f"no more threats: call {q.get('name') or 'the squad'} back", 1))

    # Training: a squad with soldiers sitting off duty.
    routines = [r for r in _l(mil.get("routines")) if isinstance(r, str)]
    train_to = next((r for r in routines if "staggered" in r.lower()), None) or \
        next((r for r in routines if "training" in r.lower()), None)
    small = citizens < cfg["train_min_citizens"]
    off = next((r for r in routines if "off duty" in r.lower()), None)
    if rules_["train_squads"] and not any_reach and small and off:
        # A small fort needs every pair of hands: a squad the AI put on
        # training goes back to work until the fort has grown (yours stay)
        for q in squads:
            if (q["id"] in memory.squads_trained and q["id"] not in memory.squads_rested
                    and not q.get("ai_orders") and "off duty" not in str(q.get("routine") or "").lower()):
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": off},
                                          f"{q.get('name') or 'a squad'}: only {citizens} dwarves, every pair of "
                                          f"hands is needed: off duty until the fort has {cfg['train_min_citizens']}", 4))
    rotating = set()
    # (0.83) with many idle hands every squad trains: the rotation exists to
    # keep hands at work, and they would sit idle anyway
    # (0.105.82) not while the soldiers badly miss what only time off gives (B,
    # 23 Nov: 20-34% truly idle civilians kept all 4 squads on constant
    # training; 20 of 20 dwarves missing drink and 13 of 13 merriment were
    # soldiers, 28 miserable, dwarves strangling dwarves): idle civilians gain
    # nothing from more training, the soldiers lose every hour off
    # (0.105.97) nor while a fifth of them badly miss friends (in an unhappy
    # fort), drink or prayer (planner_leisure.company_short)
    from planner_leisure import soldiers_short_of_leisure, company_short
    many_idle = (idle_hands(s, memory, cfg) and not soldiers_short_of_leisure(s, cfg)
                 and not company_short(s, cfg))
    if (rules_["train_squads"] and not any_reach and train_to and off and not small and not many_idle
            and traits.get("militarism", 0) < cfg["train_rotate_below_militarism"]):
        # (0.100) the rotation trains on "Constant training": "Staggered" has
        # DF's own 3-month blocks, which fought the monthly turns (uniforms off and on)
        rotate_to = next((r for r in routines if "constant" in r.lower() and "training" in r.lower()), None)
        rotating = _training_rotation(s, memory, squads, rotate_to or train_to, off, cfg, proposals)
    # (0.104.59) while many badly want to train, "Staggered training" (DF's own
    # months off) isn't enough: the AI's squads go on constant training
    # (Enxah, summer y74: MartialTraining 31 badly, Fight 24, squads 26 and 46
    # staggered while the idle-hands path skipped the rotation)
    constant = next((r for r in routines if "constant" in r.lower() and "training" in r.lower()), None)
    cit_n = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    # (0.105.82) the soldiers' own longing when the report counts it (as the rotation, 0.105.81)
    mtd = _d(_d(_d(s.get("needs")).get("needs")).get("MartialTraining"))
    mts = mtd.get("badly_soldiers")
    mt_badly = int(mts if isinstance(mts, int) and not isinstance(mts, bool) else (mtd.get("badly") or 0))
    train_all = mt_badly >= max(5, cit_n * cfg["train_all_share"])
    if train_all and constant:
        train_to = constant
    staggered = next((r for r in routines if "staggered" in r.lower()), None)
    keen_n = int(_d(s.get("needs")).get("keen_civilians") or 0)
    starved = [x for x in _l(_d(s.get("needs")).get("starved_soldiers")) if isinstance(x, dict)]
    if rules_["train_squads"] and not any_reach and train_to and traits.get("militarism", 0) > -50 and not small:
        # the AI's squads: trained or made by it, or wearing a uniform it set
        # (Enxah's 26 and 46 wear the AI's uniform; its memory of training
        # them was lost on a reload)
        ai_squads = (set(memory.squads_trained) | set(getattr(memory, "squads_made", None) or [])
                     | {q.get("id") for q in squads if q.get("ai_uniform")})
        for q in squads:
            if q.get("id") in rotating:
                continue
            if (q.get("members") or 0) > 0 and "off duty" in str(q.get("routine") or "").lower():
                if q["id"] in memory.squads_trained and q["id"] not in memory.squads_rested:
                    continue          # the AI trained it before and you sent it off duty: your call
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": train_to},
                                          f"{q.get('name') or 'a squad'} sits off duty: put it on {train_to.lower()}", 4))
            elif (train_all and constant and (q.get("members") or 0) > 0 and q.get("id") in ai_squads
                  and not q.get("ai_orders") and "staggered" in str(q.get("routine") or "").lower()):
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": constant},
                                          f"{mt_badly} dwarves badly want to train: {q.get('name') or 'a squad'} "
                                          f"goes from staggered to {constant.lower()}", 4))
            elif (not train_all and staggered and (q.get("members") or 0) > 0 and q.get("id") in ai_squads
                  and not q.get("ai_orders") and "constant" in str(q.get("routine") or "").lower()
                  and keen_n < cfg["soldier_swap_keen_min"] and len(starved) >= cfg["staggered_starved_min"]
                  and traits.get("militarism", 0) < cfg["train_rotate_below_militarism"]):
                # (0.104.72) the training wanted is met, the civilians' too, and
                # the soldiers miss everything else: DF's staggered months off
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": staggered},
                                          f"training is met and {len(starved)} soldiers badly miss other things: "
                                          f"{q.get('name') or 'a squad'} goes to {staggered.lower()} (months off by turns)", 5))

    # (0.105.54, "fight back") enemies about: a squad sitting off duty that
    # isn't sent or posted goes on training, whatever the fort's size or
    # Militarism: on duty the soldiers wear their uniform and pick up the
    # gear the gap rules hand out (off duty they put it away), and they
    # train at the barracks instead of hiding with the civilians. The AI's
    # own rests end here too; one the player sent off duty stays theirs
    if rules_["train_squads"] and any_reach and train_to:
        for q in squads:
            if (q.get("id") is not None and (q.get("members") or 0) > 0
                    and "off duty" in str(q.get("routine") or "").lower() and not q.get("ai_orders") and not (q.get("orders") or 0) and not q.get("sheltering")
                    and not (q["id"] in memory.squads_trained and q["id"] not in memory.squads_rested)):
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"],
                                                    "routine": train_to},
                                          f"enemies can reach the dwarves and {q.get('name') or 'a squad'} sits off "
                                          f"duty: on {train_to.lower()} (in uniform and armed, ready at the "
                                          "barracks)", 2))

    # Gear: weapons, body armour, helms for every soldier, made at a forge in
    # the best metal there are bars for. Only with a uniform set: without one
    # the game doesn't hand the gear out.
    gear = _d(mil.get("gear"))
    # judged on soldiers on duty (off duty they put weapons away); an older
    # bridge without the on-duty count: all soldiers
    soldiers = gear.get("on_duty") if "on_duty" in gear else (gear.get("soldiers") or 0)
    soldiers = soldiers or 0
    just_trained = (memory.last_train_tick is not None
                    and 0 <= abs_tick(s) - memory.last_train_tick < cfg["gear_wait_ticks"])
    if rules_["make_gear"] and soldiers and "error" not in gear and not just_trained:
        spare, bars = _d(gear.get("spare")), _d(gear.get("bars"))
        wants = [("weapons", "armed", GEAR_WEAPONS[rules_["gear_weapon"]], "weapons"),
                 ("body", "armored", "metal_mail_shirt", "body armour"),
                 ("helms", "helmed", "metal_helm", "helms")]
        # the rest of a kit, once a squad wears the metal uniform (a leather one
        # takes none of it) and the bridge counts it (0.61)
        if "legged" in gear and any("metal" in str(q.get("ai_uniform") or "").lower() for q in squads):
            wants += [("shields", "shielded", "metal_shield", "shields"),
                      ("pants", "legged", "metal_greaves", "greaves"),
                      ("boots", "booted", "metal_high_boots", "metal boots"),
                      ("gloves", "gloved", "metal_gauntlets", "gauntlets")]
        # a soldier holding a miner's pick isn't armed for this: the pick goes
        # back once the uniform asks for the AI's weapon (_uniform_weapon_rule)
        picks = int(_d(s.get("labor")).get("soldier_picks") or 0)
        held = {"armed": max(0, (gear.get("armed") or 0) - picks - int(gear.get("ranged_armed") or 0))}
        # (0.104.60) a melee weapon given to a soldier's place counts, fetched or
        # not (the AI hands them out itself; more aren't made meanwhile)
        if isinstance(gear.get("melee_given"), int):
            held["armed"] = max(held["armed"], int(gear["melee_given"]))
        # crossbow soldiers aren't counted for melee weapons (_ranged_squad_rule arms them)
        ranged_n = sum(int(q.get("members") or 0) for q in squads if is_ranged(q))
        if isinstance(gear.get("spare_weapons"), dict):
            # only the AI's own weapon counts as spare (others may not suit the uniform)
            spare = dict(spare, weapons=int(gear["spare_weapons"].get(WEAPON_IDS.get(rules_["gear_weapon"])) or 0))
        # boots and gauntlets come and are worn in pairs: two spares a soldier
        pairs = {"boots", "gloves"}
        short = [(k, r, w, (soldiers - ranged_n if k == "weapons" else soldiers) - held.get(h, gear.get(h) or 0)
                  - ((spare.get(k) or 0) // (2 if k in pairs else 1)) - queued(s, {r}))
                 for k, h, r, w in wants]
        short = [x for x in short if x[3] > 0]
        # Spares lying unused: soldiers aren't picking them up (often a uniform
        # that asks for something else), so more would only be wasted metal.
        waiting = [x for x in short
                   if (spare.get(x[0]) or 0) // (2 if x[0] in pairs else 1) >= cfg["gear_spare_stop"]]
        # (0.104.138) twice with nothing changed: it doesn't help here (456 runs
        # in two days, every result "0 replaced", the spares the same)
        seen = _d(memory.unstick_seen)
        same = seen.get("sig") == spare_sig(gear) and int(seen.get("n") or 0) >= 2
        if waiting and same:
            notes.append("untangling the uniforms twice changed nothing: left until the spare gear changes")
        if waiting and not same and int(gear.get("on_duty") or 0) > 0:
            # (0.99.7) region2: each soldier had 17-19 items assigned for a
            # 9-item uniform, 31 of them in other dwarves' hands, and nobody
            # picked anything up. DFHack's uniform-unstick frees them.
            proposals.append(Proposal("unstick_uniforms", {"type": "unstick_uniforms"},
                                      f"{len(waiting)} kind(s) of gear lie spare while the soldiers on duty go "
                                      "without: untangle the uniforms' assignments (DFHack uniform-unstick)", 4))
        # (0.104.58) gear the game lost track of (assigned to a dead soldier's
        # place, or on no list): never handed out until it's put back (Enxah:
        # a battle axe on the ground assigned to no one, 7 of 26 armed)
        stray = _d(gear.get("stray"))
        # what the bridge moves: anything assigned to no one, weapons on no list
        movable = {k: v for k, v in _d(stray.get("orphan")).items()}
        if _d(stray.get("unlisted")).get("WEAPON"):
            movable["WEAPON"] = int(movable.get("WEAPON") or 0) + int(stray["unlisted"]["WEAPON"])
        if movable and int(gear.get("on_duty") or 0) > 0:
            kinds = sorted(movable)
            proposals.append(Proposal("stray_gear", {"type": "free_stray_gear", "limit": 100},
                                      f"{sum(int(v or 0) for v in movable.values())} piece(s) of gear "
                                      f"({', '.join(k.lower() for k in kinds)}) "
                                      "the game assigns to no soldier and never hands out: put them back "
                                      "on its list so the soldiers get them", 3))
        # (0.104.60) DF leaves the weapon entry of a uniform empty while free
        # weapons of its kind lie about (Enxah: 19 melee places "given 0", 19
        # spare battle axes, the armour handed out): after a week of that, the
        # AI puts them on the soldiers' places itself
        since = memory.gear_spare_since.get("weapon_gaps")
        if (_weapon_gaps(gear) and isinstance(since, int)
                and abs_tick(s) - since >= cfg["assign_weapons_wait_ticks"]):
            proposals.append(Proposal("assign_weapons", {"type": "assign_weapons", "limit": 10},
                                      f"{int(gear['weapon_gaps'])} soldier place(s) the game gives no weapon "
                                      "though free ones lie about: hand them out to the soldiers", 3))
        # (0.105.8) the same for armour: E's 7 bare-handed soldiers with 5
        # left and 5 right gauntlets free; uniform-unstick changed nothing
        kit = _d(gear.get("kit"))
        since = memory.gear_spare_since.get("kit_gaps")
        if (int(kit.get("fillable") or 0) > 0 and isinstance(since, int)
                and abs_tick(s) - since >= cfg["assign_kit_wait_ticks"]):
            empty = {k: int(_d(_d(kit.get(k)).get("why")).get("fillable") or 0)
                     for k in ("body", "helms", "pants", "gloves", "boots")}
            empty = {k: v for k, v in empty.items() if v}
            proposals.append(Proposal("assign_kit", {"type": "assign_kit", "limit": 20},
                                      f"{int(kit['fillable'])} soldier place(s) the game gives no armour though "
                                      "free pieces that fit lie about"
                                      + (f" ({', '.join(f'{k} {v}' for k, v in empty.items())})" if empty else "")
                                      + ": hand them out to the soldiers", 3))
        released = []
        for k, _r, what, _n in waiting:
            since = memory.gear_spare_since.get(k)
            # (0.104.57) weapons that lie unused a month aren't the uniform's
            # (Enxah: 3 battle axes reachable, none ever assigned, 7 of 26
            # soldiers armed): new ones are made all the same
            # (0.104.138) armour and helms too: Teacheroar's 5 body armour and 4
            # helms lay unused 6,600 days (loose on floors, never handed out)
            # while ~20 soldiers went without, and none was made again
            # (0.105.35) every kind of the kit: shields, greaves, boots and
            # gauntlets too (nothing waits for the player to check the uniforms)
            if (isinstance(since, int)
                    and abs_tick(s) - since >= cfg["gear_weapons_anyway_ticks"]):
                released.append(k)
                notes.append(f"{spare.get(k)} spare {what} lie unused for a month: making new ones anyway")
                continue
            if isinstance(since, int) and abs_tick(s) - since >= cfg["gear_unused_ticks"]:
                days = max(1, (since + cfg["gear_weapons_anyway_ticks"] - abs_tick(s)) // TICKS_PER_DAY)
                notes.append(f"{spare.get(k)} {what} lie unused while soldiers go without (they may not fit the "
                             f"squads' uniforms: the AI makes {rules_['gear_weapon']}s for weapons): the uniforms "
                             f"are untangled and the gear handed out, and new ones are made if they still lie "
                             f"unused in {days} days")
            else:
                notes.append(f"{spare.get(k)} spare {what} not picked up yet: waiting before making more")
        short = [x for x in short if x not in waiting or x[0] in released]
        if short and not gear.get("forges"):
            # (0.105.35) the AI builds the forge itself (it asked the player before)
            open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
            forge_planned = any(isinstance(p, dict) and any(k in _d(p.get("furniture"))
                                                             for k in ("MetalsmithsForge", "MagmaForge"))
                                for p in open_)
            if forge_planned or _has_shop(_d(s.get("buildings")), "MetalsmithsForge"):
                notes.append(f"soldiers lack {short[0][2]} and no forge is ready to make them: waiting for "
                             "the forge being built")
            elif _workshops_busy(open_):
                notes.append(f"soldiers lack {short[0][2]} and the fort has no forge: one is built once the "
                             "workshops under way are done")
            else:
                proposals.append(Proposal("arms_forge", {"type": "start_project", "kind": "workshops",
                                                         "shops": ["MetalsmithsForge"]},
                                          f"soldiers lack {short[0][2]} and the fort has no forge to make them: "
                                          "build one", 4))
        elif (short and not gear.get("squads_with_uniform")
              and not [t for t in _l(mil.get("uniform_templates")) if isinstance(t, str)]):
            # (with the fort's uniform templates the AI gives the squad one itself)
            # (0.105.35) kept: the AI's uniforms are the fort's templates, and
            # the bridge has no way to make a template
            ask_player(notes, f"soldiers lack {', '.join(x[2] for x in short)}, but no squad has a uniform and "
                              "the fort has no uniform template, which the AI can't make: the gear isn't handed "
                              "out meanwhile; the AI gives every squad one as soon as a template exists "
                              "(military screen, Equip)")
        elif short:
            key, recipe, what, n = short[0]
            n = min(n, cfg["max_gear_order"])
            need = n * cfg["gear_bars"][key]
            metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= need), None)
            if metal:
                proposals.append(Proposal(
                    "arms", {"type": "work_order", "recipe": recipe, "amount": n, "material": f"INORGANIC:{metal}"},
                    f"{soldiers} soldiers, {gear.get(GEAR_HELD[key]) or 0} "
                    f"have {what}: make {n} in {metal.lower().replace('_', ' ')}", 3, True))
            elif (_has_shop(s["buildings"], "Smelter") and _d(_d(s.get("industry")).get("ores"))
                  and ("smelting" in (memory.libraries_imported or []) or not rules_["import_smelting"]
                       or "ore_stock_by" in _d(s.get("industry")))):
                # the AI is on it: ore mined, a smelter, DFHack's smelting orders in
                notes.append(f"soldiers lack {what}: waiting for {need} bars of weapon-grade metal "
                             "(the ore is being mined and smelted)")
            else:
                # (0.105.35) said, not asked: the industry rule builds the
                # furnaces and mines a vein once ore is uncovered near the fort
                ores = _d(_d(s.get("industry")).get("ores"))
                notes.append(f"soldiers lack {what} and there aren't {need} bars of a weapon-grade metal "
                             "(steel, iron, bronze, copper): "
                             + ("the AI mines the ore and builds the smelter for it" if ores else
                                "no ore of it uncovered yet: the AI smelts once the miners find some, or a "
                                "caravan brings bars"))

    # Barracks: each squad trains (and keeps its gear) in one, as the zone's
    # squad screen does; one squad a cycle
    # a crossbow squad also trains at an archery range
    rngs = [b for b in _l(mil.get("ranges")) if isinstance(b, dict) and b.get("id") is not None]
    if rngs:
        at_range = {sid for b in rngs for sid in _l(b.get("squads"))}
        for q in squads:
            if is_ranged(q) and q.get("id") is not None and q["id"] not in at_range and (q.get("members") or 0) > 0:
                proposals.append(Proposal("barracks_assign", {"type": "squad_barracks", "squad_id": q["id"],
                                                              "zone_id": rngs[0]["id"]},
                                          f"{q.get('name') or 'a squad'} shoots crossbows: train at the archery range", 4))
                break
    bks = [b for b in _l(mil.get("barracks")) if isinstance(b, dict) and b.get("id") is not None]
    if bks and squads:
        using = {sid for b in bks for sid in _l(b.get("squads"))}
        for q in squads:
            if q.get("id") is not None and q["id"] not in using and (q.get("members") or 0) > 0:
                b = min(bks, key=lambda b: len(_l(b.get("squads"))))
                proposals.append(Proposal("barracks_assign", {"type": "squad_barracks", "squad_id": q["id"],
                                                              "zone_id": b["id"]},
                                          f"{q.get('name') or 'a squad'} has no barracks: train there and keep its "
                                          "gear on the armour stands and racks", 4))
                break

    # Filling: soldiers wanted from the Militarism trait, into open places.
    # (0.105.54) never fewer than the defence floor by threat: the threat on
    # the map counts at once (the floor rises now and fades over seasons)
    # (planner.note_cycle remembers it: plan() never writes memory)
    from planner_defence_floor import defence_floor, floor_note
    floor_ = defence_floor(s, memory, cfg, citizens)
    want, have = soldiers_wanted(s, citizens, cfg, many_idle, memory, floor_), mil.get("soldiers") or 0
    floor_tag = ""
    if floor_.get("threat", 0) > 0:
        by_slider = soldiers_wanted(s, citizens, cfg, many_idle, None, {"soldiers": 0})
        # said while it binds (above the slider's number) or the soldiers fall short of it
        if int(floor_.get("soldiers") or 0) > by_slider or have < int(floor_.get("soldiers") or 0):
            line = floor_note(floor_, have, by_slider)
            if line:
                notes.append(line)
        if int(floor_.get("soldiers") or 0) > by_slider:
            floor_tag = " (defence floor)"
    from quirks import has_rule
    if memory is not None and has_rule(memory.culture, "more_soldiers"):
        want = min(citizens, round(want * 1.25))   # (Oathbound)
    base_want = want
    want = keen_lift(s, memory, cfg, want, have, citizens, bool(any_reach))      # (0.104.168) the keen in a crisis
    cap = civilian_cap(s, cfg)                                                    # (0.105.2) enough left to work
    if cap is not None and not any_reach:
        want = min(want, cap)
    # (0.102) an army bigger than the fort wants (Militarism lowered, the fort
    # shrank) gives soldiers back to work a few at a time, while all is quiet.
    # Monastery kept 49 soldiers at Militarism -60 (it wanted ~10).
    over = have - want
    from planner_war_hold import arm_check, armed_count
    try:
        arm_why, arm_lift = arm_check(s, cfg, rules_, memory)
    except Exception:  # noqa: BLE001   (x4: never stops the drafting)
        arm_why, arm_lift = "", ""
    if (floor_tag and int(_d(mil.get("gear")).get("on_duty") or 0) > 0
            and armed_count(s) < int(floor_.get("soldiers") or 0) <= have):
        # (r1g5) the floor counts armed soldiers: met in members, not in arms
        notes.append(f"Defence floor {floor_.get('soldiers')}: {have} soldiers but only {armed_count(s)} armed: "
                     "the floor is met once they are armed (weapons first)")
    # (0.104.66) while civilians badly want to train, the swap turns the squads
    # over instead: the wanted number falls as the keen are drafted (the cap
    # for the keen lifts and drops), and a trim then sent 2 of 38 home (16:03)
    # just as the fill drafted more
    keen = int(_d(s.get("needs")).get("keen_civilians") or 0)
    if (rules_["fill_squads"] and not any_reach and not berserk_now and keen < cfg["soldier_swap_keen_min"]
            and over > max(cfg["trim_margin_min"], round(want * cfg["trim_margin_share"]))):
        count = min(over, cfg["max_trim_per_cycle"])
        proposals.append(Proposal("squad_trim", {"type": "squad_trim", "count": count},
                                  f"{have} soldiers, the fort wants {want} (Militarism "
                                  f"{int(traits.get('militarism', 0) or 0):+d}): {count} go back to work", 5))
    if have < want and not rules_["fill_squads"]:
        notes.append(f"{have} soldiers, the fort wants {want}: raising and filling squads is off on the Rules tab, "
                     "so the AI leaves the squads as they are")
    elif (have < want and isinstance(getattr(memory, "fight", None), dict) and memory.fight
          and 0 <= abs_tick(s) - int(memory.fight.get("tick") or 0) < cfg["fight_freeze_days"] * TICKS_PER_DAY):
        # (0.104.139) no new soldiers mid-fight: the losses are read from the
        # soldier count after it (refills hid them, and the beast was learned as weaker)
        notes.append(f"{have} soldiers, the fort wants {want}: the squads are filled once the fight is over")
    elif have < want and (berserk_now or tantrums_recent(s, memory, cfg["fill_tantrum_hold_days"])):
        # (0.104.168, review) nobody armed while a dwarf is berserk or a tantrum
        # is under way (Teacheroar's spirals: soldiers among those who killed)
        notes.append(f"{have} soldiers, the fort wants {want}: no drafting while "
                     + ("a dwarf is berserk" if berserk_now else "tantrums are under way"))
    elif have < want and arm_why:
        # (r1g5) A: 22 of 57 armed with 68 steel bars; B: the floor drafted 6, none armed
        notes.append(f"{have} soldiers, the fort wants {want}{floor_tag}: {arm_why}")
    elif have < want:
        if arm_lift:
            # (x4, V3) the arming hold would stand, but the weapons can't come soon or the fort needs numbers
            notes.append(f"{have} soldiers, the fort wants {want}{floor_tag}: drafted unarmed ({arm_lift})")
        open_ = [(q, min(9, (q.get("size") or 0) - 1) - max(0, (q.get("members") or 0) - (1 if q.get("leader") else 0)))
                 for q in squads]
        open_ = [(q, n) for q, n in open_ if n > 0 and not q.get("training_squad")]   # (0.105.47) volunteers only
        if open_:
            q, n = open_[0]
            count = min(n, want - have, cfg["max_fill_per_cycle"])
            act = {"type": "squad_fill", "squad_id": q["id"], "count": count}
            # (0.104.168, review) the keen lift's places go to the keen alone;
            # the places the fort wants anyway are filled first, as before
            if want > base_want:
                if have < base_want:
                    act["count"] = count = min(count, base_want - have)
                else:
                    act["keen_only"] = True
            if _d(getattr(memory, "crisis", None)).get("why"):
                act["strict"] = True          # in a crisis never the very unhappy, whatever they long for
            home = recently_home(s, memory)              # (0.104.138) not those just sent home
            if home:
                act["avoid"] = home
            proposals.append(Proposal("squad_fill", act,
                                      f"{have} soldiers, the fort wants {want}{floor_tag}"
                                      + (f" ({want - base_want} more for the civilians who badly want to train, "
                                         "while the fort is in crisis)" if want > base_want else "")
                                      + f": add {count} to {q.get('name') or 'a squad'}", 3))
        else:
            # (0.97: "Raise and fill squads" governs new squads too; it was
            # appoint_nobles, which said nothing about squads)
            # a new squad: a militia commander's (or captain's) post, its leader
            # appointed, the uniform copied from a squad that has one. When the
            # game has no free post for it, that's yours to add (Oct 23: refused
            # quietly over and over while the fort wanted more soldiers)
            ref = _d((getattr(memory, "refusals", None) or {}).get(
                refusal_key(Proposal("squad_make", {"type": "make_squad"}, "", 3))))
            if "no military office" in str(ref.get("why") or ""):
                # (0.105.35) said, not asked: make_squad adds a captain's post
                # itself when DF lets it; what's left is the game's own limit
                why_ = str(ref.get("why") or "")
                why_ = why_[why_.find("(") + 1:why_.rfind(")")] if "(" in why_ and ")" in why_ else ""
                notes.append(f"{have} soldiers, the fort wants {want}, every squad is full and no military "
                             "office is free to lead another" + (f" ({why_[:100]})" if why_ else "")
                             + ": the AI trains the squads it has and makes another once DF allows one "
                             "(a militia commander appointed, a captain's post free)")
            proposals.append(Proposal("squad_make", {"type": "make_squad"},
                                      (f"the fort wants {want} soldiers{floor_tag} and has no squad" if not squads else
                                       f"{have} soldiers, the fort wants {want}{floor_tag}, and every squad is full")
                                      + ": make a squad and appoint its leader", 3))
    g = _d(mil.get("gear"))
    templates = [t for t in _l(mil.get("uniform_templates")) if isinstance(t, str)]
    if rules_["make_gear"] and templates and proposals is not None:
        # a uniform from the fort's templates: leather until the forge has made
        # metal armour and helms for every soldier, then metal
        spare = _d(g.get("spare"))
        bars_total = sum(v for v in _d(g.get("bars")).values() if isinstance(v, (int, float)))
        for q in squads:
            n = int(q.get("members") or 0)
            # metal once the armour is there, or once there are bars enough to
            # make it: a leather uniform takes only leather helms and armour, so
            # iron helms made for it lay unused (region2, y52)
            metal = n > 0 and (((spare.get("body") or 0) >= n and (spare.get("helms") or 0) >= n)
                               or bars_total >= cfg["metal_kit_bars"] * n)
            kind = "metal" if metal else "leather"
            ranged = is_ranged(q)
            if q.get("uniform") is False:
                proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": q["id"], "kind": kind},
                                          f"{q.get('name') or 'a squad'} has no uniform (they'd fight in their "
                                          f"clothes): give it the fort's {kind} uniform", 3))
            elif metal and q.get("ai_uniform") and "metal" not in str(q["ai_uniform"]).lower():
                proposals.append(Proposal("uniform", dict({"type": "set_uniform", "squad_id": q["id"], "kind": "metal"},
                                                          **({"ranged": True} if ranged else {})),
                                          f"metal armour and helms for all {n} of {q.get('name') or 'a squad'}, "
                                          f"or {round(bars_total)} bars to make them: change its uniform from "
                                          "leather to metal", 5))
                # the leather armour they wear counts as armour: order the mail
                short = n - int(spare.get("body") or 0) - queued(s, {"metal_mail_shirt"})
                metal_tok = _best_metal(s, max(1, short))
                if short > 0 and metal_tok:
                    proposals.append(Proposal("kit", {"type": "work_order", "recipe": "metal_mail_shirt",
                                                      "amount": short, "material": metal_tok},
                                              f"{q.get('name') or 'a squad'} goes from leather to metal: make "
                                              f"{short} mail shirt(s) in {metal_tok.split(':')[-1].lower()}", 5, True))
        # squads the AI made before 0.82 copied the AI's uniform without saying
        # it was the AI's: mark it so, so the AI may change it later
        for q in squads:
            if (q.get("id") in (getattr(memory, "squads_made", None) or []) and q.get("uniform")
                    and not q.get("ai_uniform")):
                proposals.append(Proposal("uniform_adopt", {"type": "adopt_uniform", "squad_id": q["id"]},
                                          f"{q.get('name') or 'a squad the AI made'} wears a copy of the AI's "
                                          "uniform: the AI takes charge of it", 3))
                break
        from planner_defence_floor import peaceful_ranged
        _ranged_squad_rule(s, g, squads, templates, cfg, proposals, getattr(memory, "squads_made", None),
                           peaceful_ranged(s, traits), memory=memory, traits=traits)
        _uniform_weapon_rule(s, g, squads, rules_, proposals)
    elif isinstance(g.get("squads"), int) and g["squads"] > (g.get("squads_with_uniform") or 0):
        n_bare = g["squads"] - (g.get("squads_with_uniform") or 0)
        if not rules_["make_gear"]:
            # (0.105.35) the player's switch: said, not asked
            notes.append(f"{n_bare} squad(s) have no uniform (they'd fight in their clothes): making and "
                         "handing out gear is off on the Rules tab, so the AI leaves their uniforms alone")
        else:
            # kept: the AI's uniforms are the fort's templates, and the bridge
            # has no way to make a template
            ask_player(notes, f"{n_bare} squad(s) have no uniform, so they'd fight in their clothes, and the fort "
                              "has no uniform template, which the AI can't make; meanwhile they train as they "
                              "are, and the AI gives every squad one (and copies it to the squads it makes) as "
                              "soon as a template exists (military screen, Equip)")


# --- (0.104.83) the fort defends itself: the gate held, war dogs posted ----------------


