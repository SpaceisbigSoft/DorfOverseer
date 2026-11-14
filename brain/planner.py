"""The local planner: fort report + player settings -> proposed actions.

Pure rules, no tokens. Each cycle the overseer calls, in this order:
  note_cycle()  bookkeeping from the fresh report (alert ownership, tools seen)
  plan()        propose actions (reads memory, never changes it)
  select()      apply the safety limits
  record()      remember what was actually done
See docs/local-planner.md. Every proposal carries the rule that made it and a
plain-English reason.

(0.104.83) The planner is in parts: planner_core (memory, shared helpers,
the refusal, loop and no-effect holds), planner_military, planner_industry,
planner_society and planner_building (the rules by area); this file keeps
plan(), select(), record() and note_cycle() and re-exports every name, so
`from planner import X` works as before. (0.105.25, 13c) Split further by
theme, each re-exported by the part it came from: planner_config
(PLANNER_CONFIG) from core; planner_wells and planner_growth from building;
planner_moods, planner_visitors, planner_health and planner_locations from
society; planner_farms, planner_labor, planner_trade and planner_orders from
industry; planner_gates from military. Later parts: planner_care,
planner_homes, planner_water, planner_threats, planner_world, planner_army,
planner_missions, planner_cleanup.
"""

from __future__ import annotations

import math

import masterplan
from quirks import has_rule
from digest import _d, _l, normalize

from planner_core import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_military import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_industry import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_society import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
import crisis  # noqa: E402  (0.104.137)
from planner_moods import mood_blocked  # noqa: E402  (0.105.26) a waiting mood's materials held from other orders
from planner_moods import reserve_room, note_reserve_swap, _mood_reserve_rule  # noqa: E402  (0.105.31) the mood reserves
from planner_gates import note_gate_stuck, note_gate_stuck_cycle  # noqa: E402  (0.105.32) a gate the game holds shut
from planner_building import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
import planner_design  # noqa: E402  (D0) the Design track's loop
from planner_design import design_rule, note_design  # noqa: E402
from planner_care import _doctor_post_rule, _infection_rule, _offices_refill_rule, _traction_rest_rule  # noqa: E402  (0.104.168)
from planner_water import _waterworks_rule  # noqa: E402  (0.105.0) moat, pumps, irrigation, magma workshops
from planner_homes import *  # noqa: E402,F401,F403  (0.104.168: homes and households)
from planner_threats import _threat_rules, unseen_intrusion, alarm_held  # noqa: E402  (0.105.0 round 3; 0.105.36)
from planner_world import (_contact_rule, _export_rule, _hostile_trade_filter, _meeting_answer_rule,  # noqa: E402
                           _messenger_rule, _world_notes, note_world)  # (0.105.0: the world outside, 12b and 13b)
from planner_peace import _peace_notes  # noqa: E402  (0.105.41, item 8: war and peace)
from planner_bans import _export_bans_notes  # noqa: E402  (0.105.41, item 8: the nobles' export bans)
from planner_missions import _mission_rule, note_missions  # noqa: E402  (0.105.39) missions on the world map
from planner_cleanup import _world_cleanup_rule, note_cleanup  # noqa: E402  (0.105.40) world cleanup for the game's speed
from planner_captives import _captives_rule, _necro_rule, note_captives  # noqa: E402  (item6) prisoners' outcomes, necromancer sieges
from planner_weather import _weather_rules, _weather_squad_filter, note_keep_in  # noqa: E402  (0.105.40b) evil weather
from planner_alarm import govern_alarm, note_alarm_change  # noqa: E402  (item4) the alarm kept from flapping
from planner_firebreath import _fire_breather_rule  # noqa: E402  (0.105.40b) no melee squad at a fire breather
from planner_siege import _siege_rules  # noqa: E402  (item5) siege engines, archer posts, caravan guard, wildlife hunts
from planner_hazards import _hazards_rule, magma_alarm  # noqa: E402  (0.105.41, item 7) spilt magma, cave-ins, frost, heat
from planner_insane import _insane_rule  # noqa: E402  (0.105.40b) the insane: deadly ground near them, the AI's doors
from planner_killers import _killer_rule  # noqa: E402  (item3) a killer among the fort's own: cells, a squad
from planner_hunt import _hunt_rule, note_hunt_cycle  # noqa: E402  (0.105.45) hunting threats the squads can beat
from planner_shelter import _shelter_pick_rule  # noqa: E402  (0.105.45) the shelter away from the threat
from planner_stuck import _stuck_rule, note_stuck  # noqa: E402  (0.105.45) the sweep for things stuck "in progress"
from planner_killzone import _killzone_rule  # noqa: E402  (0.105.45) kill zones at the gates and cavern openings
from planner_lure import _lure_rule  # noqa: E402  (0.105.45) a sealed cavern beast lured into a pocket, cut off
from planner_hauling import _hauling_labor_rule, note_hauling  # noqa: E402  (0.105.40 M5) hauling balanced
from planner_traffic import _traffic_rule  # noqa: E402  (0.105.41) traffic zones on the AI's own levels
from planner_food import _food_store_rule, note_food  # noqa: E402  (0.105.40b, M6) the food store
from planner_provisions import _provisions_rules  # noqa: E402  (0.105.41, item 4) hunting, butchery, fruit, meals, cavern farms
from planner_syndromes import _miasma_rule, _syndrome_rule, note_syndromes  # noqa: E402  (0.105.41, item 11) syndromes, miasma
from planner_food import note_food_level  # noqa: E402  (fix41) a food storage level booked per kitchen/still
from planner_nobles import _noble_value_rule, nobles_view, noble_room_plan  # noqa: E402,F401  (0.105.41) nobles' room values
from planner_piles import _pile_links_rule  # noqa: E402  (0.105.41, item 2) wheelbarrows and feeder links
from planner_artifacts import _artifact_rule  # noqa: E402  (item 12) the fort's artifacts shown behind doors
from planner_alloys import _alloy_rule  # noqa: E402  (0.105.40 M7) bronze for a fort without iron, value alloys
from planner_paper import _paper_rule  # noqa: E402  (item9) paper from plants, scrolls and codices for the library
from planner_deep import _deep_hazard_rule  # noqa: E402  (0.105.40b) adamantine and the underworld: never dug
from planner_construct import (_hall_rule, _construction_blocks_rule,  # noqa: E402  (0.105.30) construction
                               note_construct, note_construct_cycle)
from planner_forestry import _cavern_logging_rule, _grove_rule  # noqa: E402  (item10) cavern logging, the grove
from planner_benches import _bench_caps_rule  # noqa: E402  (item10) training benches
from planner_leather import _leather_gear_rule  # noqa: E402  (item10) leather armour while metal is short
from planner_army import (_army_gear_rule, _quiver_rule, _bolts_rule, _flask_rule,  # noqa: E402  (0.105.0, round 2)
                          _shelter_squads_rule, _gate_cut_rule)


# (0.105.36) SHELTER_RETRY_DAYS, _shelter_due and _no_shelter_note moved to
# planner_military, beside no_shelter, so every caller paces the shelter alike
SHOPS_RETRY_DAYS = 56          # (0.105.35) a workshops level started twice and not seen built: once more after this
SHOPS_RETRY_MAX = 3            # (v35 fix) and so at most this many times
GATE_PULL_SEEN_DAYS = 3        # (0.105.36) a gate read shut this soon after the AI pulled its lever is the AI's


def _set_adopted(s: dict, memory, traits: dict) -> None:
    """(D0) The language's adopted customs into customs.active (G1's
    customs.set_adopted); () at Scripts."""
    import customs
    if not hasattr(customs, "set_adopted"):
        return
    ids = ()
    if memory is not None and planner_design.mode_of(s) != "scripts" and planner_design.design is not None:
        ids = tuple(planner_design.design.adopted_customs(memory.culture or {}, traits) or ())
    customs.set_adopted(ids)


def plan(state: dict, memory: Memory, cfg: dict = PLANNER_CONFIG) -> tuple[list[Proposal], list[str]]:
    """Return (proposals, notes). Notes say what the planner wanted but couldn't do.
    Reads memory; never changes it, but for the Design track's own record
    (planner_design: the design language and the landmarks, at Guided and
    Architect only)."""
    s = normalize(state)
    errors = s["_errors"]
    # (0.100, review) without the date every cooldown reads tick 0, and
    # without the dwarves every need is sized for one: no plan this cycle
    missing = [x for x in ("date", "dwarves") if x in errors]
    if missing:
        return [], [f"the report has no {' or '.join(missing)} this cycle ({errors[missing[0]]}): "
                    "nothing planned; next cycle tries again"]
    traits = _traits(s)
    dw = s["dwarves"]
    citizens = max(1, dw.get("total", 0))
    adults = max(1, dw.get("adults", 0))
    st = s["stocks"]
    proposals: list[Proposal] = []
    notes: list[str] = []
    reported: set[str] = set()

    def can_use(*sections: str) -> bool:
        bad = [x for x in sections if x in errors]
        new = [x for x in bad if x not in reported]
        if new:
            reported.update(new)
            notes.append(f"skipped rules that need report section(s) {', '.join(new)} (failed)")
        return not bad

    def _guard(fn, *args, **kw):
        """(13c) One rule failing on an odd report value no longer stops the
        whole cycle (five failed cycles in a row stopped the overseer, gates
        and alerts with it): the error becomes a note and the others run."""
        try:
            return fn(*args, **kw)
        except Exception as e:  # noqa: BLE001
            notes.append(f"rule {fn.__name__} failed ({type(e).__name__}: {str(e)[:120]}); the others ran")
            return None

    rules_ = player_rules(s)                        # the Rules tab, read once a plan
    # (D0, Design track) the fort's design language kept, its landmarks moved
    # on; then the customs it adopts. At Scripts: nothing adopted, nothing proposed
    _guard(design_rule, s, traits, cfg, proposals, notes, memory)
    _guard(_set_adopted, s, memory, traits)
    buffer = factor(traits, "stockpile")
    winter = winter_factor(s, memory)               # stock up before winter (and through it)

    # 1. Threat alert ------------------------------------------------------
    def _threat_alert():
        if "civ_alert" in errors:
            # (0.105.36) unread is not "off": nothing raised or lowered on a
            # guess (the gates and squads act all the same); next cycle reads it
            notes.append(f"the alarm couldn't be read this cycle ({str(errors['civ_alert'])[:80]}): it is left as "
                         "it is until the next report")
            return
        if can_use("others_on_map"):
            ids = reachable_threats(s, traits, cfg)
            fresh = [i for i in ids if i not in memory.alert_suppressed]
            alert_on = bool(s.get("civ_alert"))
            ready = s.get("civ_alert_ready") is True
            # (0.105.3) B (2 Nov): the alarm stayed up 2.5 hours for one thief
            # inside. For a lone intruder it is held `lone_intruder_alert_ticks`
            # at most (the squad deals with them); after a lifted lockdown it
            # waits for a new enemy (note_lockdown)
            intrusion = unseen_intrusion(s, memory, cfg)       # (0.105.30 live fixes) DF's invasion record
            lone = lone_intruders(s, cfg, traits, memory) if ids else []
            few = few_ordinary(s, cfg, traits) if ids else []                # (0.105.8) B's 31 dead of thirst
            stand_down = (bool(lone and lone_alert_over(s, memory, cfg)) or lockdown_released(memory)
                          or bool(few and few_alert_over(s, memory, cfg)))
            if stand_down:
                if alert_on and memory.ai_alert_raised and not hazard_alert(s, cfg):
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                              f"only {len(lone)} enemy/enemies left, inside the fort, and a squad on "
                                              "them: the alarm comes down (it keeps everyone from work)" if lone else
                                              f"only {len(few)} ordinary enemy/enemies about for half a day: the alarm "
                                              "comes down (the shelter keeps the dwarves from food, drink and work; "
                                              "the gates still close when one comes near)" if few else
                                              "the fort has been shut for days with no new enemy: the alarm comes down", 0))
            elif fresh and not alert_on:
                if ready:
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                              f"{len(fresh)} threat(s) can reach the dwarves", 0))
                elif _shelter_due(s, memory, True):
                    notes.append(f"{len(fresh)} threat(s) can reach the dwarves: setting up a shelter so the "
                                 "alarm can sound")
                else:
                    notes.append(_no_shelter_note(s, memory, f"{len(fresh)} threat(s) can reach the dwarves"))
            elif ids and not fresh and not alert_on:
                notes.append(f"{len(ids)} threat(s) can reach the dwarves; you cleared the alert for "
                             "them, so the AI is leaving it off")
            elif not ids and not alert_on and intrusion:
                # (0.105.30 live fixes) E (8 Nov): DF's invasion record of a hidden
                # thief came 2,000 ticks before she was spotted among the dwarves
                what = ("an intruder" if intrusion.get("civ") in (None, -1) or (intrusion.get("invaders") or 0) <= 1
                        else f"{intrusion.get('invaders')} intruders")
                hours = max(0, (abs_tick(s) - intrusion["tick"]) // 50)
                if ready:
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                              f"DF reports {what} on the map ({hours} game hour(s) ago), nobody seen yet "
                                              "(a thief hides until spotted): sound the alarm before they strike", 0))
                elif _shelter_due(s, memory, True):
                    notes.append(f"DF reports {what} on the map, nobody seen yet: setting up a shelter so the "
                                 "alarm can sound")
                else:
                    notes.append(_no_shelter_note(s, memory, f"DF reports {what} on the map, nobody seen yet"))
            elif not ids and alert_on and memory.ai_alert_raised and not hazard_alert(s, cfg) and intrusion:
                notes.append("the alarm stays up: DF reported an intruder "
                             f"{max(0, (abs_tick(s) - intrusion['tick']) // 50)} game hour(s) ago and nobody has been "
                             f"seen yet (held {cfg.get('intrusion_alert_days', 2)} days at most)")
            elif not ids and alert_on and memory.ai_alert_raised and not hazard_alert(s, cfg):
                clear, why = all_clear(s, memory, cfg)
                quick = "" if clear else quick_clear(s, memory, cfg)     # (0.105.3) A's sneaker, 9 shut out
                if clear:
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                              "no threat has been able to reach the dwarves for "
                                              f"{memory.quiet_cycles} cycles and "
                                              f"{cfg['alert_quiet_days']}+ days", 0))
                elif quick:
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                              f"{quick}: the alarm comes down", 0))
                elif "great danger" in why or "day(s) ago" in why:
                    notes.append(f"the alarm stays up: {why}")
    _guard(_threat_alert)

    # 1b. Hazards: fire, clouds, flooding, berserk citizens, cursed, prisoners
    if can_use("hazards"):
        _guard(_hazard_rules, s, memory, cfg, proposals, notes, rules_)
    # (0.105.0) round 3: fire guarded, prisoners, thieves, the undead, werebeasts, cavern beasts, the wounded
    if can_use("threats"):
        _guard(_threat_rules, s, memory, cfg, proposals, notes)
    # (0.105.45) a great beast sealed in the caverns lured into a pocket behind a
    # cavern door and caught or shut in (planner_lure; the bridge's `lures`)
    if "lures" not in errors:
        _guard(_lure_rule, s, cfg, proposals, notes, memory)
    # (0.105.40b) evil weather: the alarm while an evil cloud or rain is on the fort, lifted hours after
    # (fix41-ff) always: an unread weather report still keeps the spell's alarm up
    _guard(_weather_rules, s, memory, cfg, proposals, notes)
    # (0.105.41, item 7) spilt magma guarded and reclaimed, cave-ins, frost, heat
    if can_use("env_hazards"):
        _guard(_hazards_rule, s, memory, cfg, proposals, notes)
    # (item4) the alarm's minimum time on, the cooldown for the same cause, the month's cap
    # (enemies that can reach the dwarves always sound it)
    _guard(govern_alarm, s, memory, cfg, proposals, notes)

    # 1c. Health: who waits for care, and for how long
    if can_use("health"):
        _guard(_health_rules, s, memory, cfg, notes)
        _guard(_doctor_patient_rule, s, proposals)
        if can_use("locations"):
            _guard(_doctor_post_rule, s, cfg, proposals)        # (0.104.168)
    if can_use("infection"):
        _guard(_infection_rule, s, cfg, proposals, notes)       # (0.104.168)
        _guard(_traction_rest_rule, s, cfg, proposals, notes, memory)   # (0.105.24)
    # (0.104.167) the wounded kept inside; (review) outside the health gate:
    # a failed health section must not freeze the members (the rule reads it if there)
    _guard(_hospital_burrow_rule, s, cfg, proposals, memory)
    # (0.104.169) a dwarf in a tantrum kept apart till calm (outside the health gate, likewise)
    _guard(_calm_burrow_rule, s, cfg, proposals, notes, memory)

    # 2. Drink ------------------------------------------------------------
    def _drink_rule():
        if can_use("stocks", "orders"):
            per_job = cfg["drinks_per_job"]
            drink, pending = st.get("drink", 0), queued(s, BREW_RECIPES) * per_job
            target = citizens * cfg["drink_per_dwarf"] * buffer * winter
            # (0.104.169) in a crisis drink is a lever: a higher target, brewed sooner
            crisis_drink = memory is not None and drink_crisis(s, memory, cfg)
            if crisis_drink:
                target *= cfg["crisis_drink_share"]
            # (0.103) a Thirst-scarred fort keeps a third more
            if memory is not None and has_rule(memory.culture, "drink_hoard"):
                target *= cfg["drink_hoard_share"]
            if memory is not None and has_rule(memory.culture, "mead_hall"):
                target *= 1.25                          # (0.103.2) Mead Hall
            if drink + pending < target:
                urgent = drink < citizens * cfg["urgent_drink_per_dwarf"]
                sup_ = _d(s.get("supplies"))
                # (0.99.5) only what a still can brew (the bridge reads each
                # material's DRINK_MAT): region2's 325 growths were all leaves
                # and the like, and the fruit order's jobs were cancelled
                # ("Needs unrotten fermentable leaf or fruit") while drink fell.
                # (0.105.33) brewable_counts, as brew_recipe reads them
                plants, fruit = brewable_counts(s)
                # (0.99.3) one AI brew order per source at a time: the stills work
                # through one, and the copies waiting their turn looked stuck, were
                # cancelled and ordered again (region2: 78 orders, 86 cancels in
                # 1.5 h). Plants and fruit each get theirs (region2: plants 218 ->
                # 140 while 325 fruit sat unused). (0.100) one order already spreads
                # over every still, so this is about the two sources, not the stills
                # (0.103.4) a source whose order just got stuck and was cancelled
                # waits (Enxah: the fruit brew cancelled as stuck and ordered again
                # the next cycle); the drink rule itself is never held
                # (0.105.26) a short wait (drink_stuck_wait_days, not the 28 days
                # stuck_retry_days holds other orders), and none while drink is urgent
                stuck_wait = 0 if urgent else cfg["drink_stuck_wait_days"]

                def stuck_recently(r):
                    st_ = _d(_d(getattr(memory, "stuck_cancelled", None)).get(r))
                    return isinstance(st_.get("tick"), int) and 0 <= abs_tick(s) - st_["tick"] < stuck_wait * TICKS_PER_DAY
                # (0.104.169) in a crisis, far under the target, the next batch is
                # queued once the open one's remaining work is all on the stills
                # (crisis_brew_room), up to crisis_brew_orders_max orders a recipe:
                # the stills never wait between batches. (select's hold on an order
                # that hasn't moved in order_hold_days and the rule's cooldown still apply.)
                far = crisis_drink and drink + pending < target * cfg["crisis_drink_far_share"]

                def ai_orders(r):
                    return sum(1 for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
                               and o.get("recipe") == r and (o.get("amount_left") or 0) > 0)

                def room(r):
                    if not queued(s, {r}, ai_only=True):
                        return True
                    return far and ai_orders(r) < cfg["crisis_brew_orders_max"] and crisis_brew_room(s, r)
                sources = [(r, n) for r, n in (("brew_drink", plants), ("brew_drink_from_fruit", fruit))
                           if n > 0 and room(r) and not stuck_recently(r)]
                if plants <= 0 and fruit <= 0:
                    # (0.105.35) said, not Needs you: the AI's own rules answer it
                    notes.append(f"drink is low ({drink} for {citizens} dwarves) and there are no plants or fruit a "
                                 "still can brew: the AI gathers the wild shrubs and its farms grow brewable crops "
                                 "(plump helmets, and others by the season); the dwarves drink water meanwhile")
                elif not sources:
                    stuck_ = [r for r, n in (("brew_drink", plants), ("brew_drink_from_fruit", fruit))
                              if n > 0 and stuck_recently(r)]
                    if pending > 0 or queued(s, BREW_RECIPES):
                        notes.append(f"drink {drink} + ~{pending} queued is below the target of {round(target)}: "
                                     "the stills work through the brew orders there are before more")
                    else:
                        # (0.105.26) nothing ordered: say why ("the stills work
                        # through the brew orders there are" when there were none)
                        notes.append(f"drink {drink} is below the target of {round(target)} and nothing is brewing: "
                                     + (f"the last {' and '.join(r.replace('_', ' ') for r in stuck_)} order got stuck "
                                        f"and was cancelled; ordered again within {stuck_wait} days"
                                        if stuck_ else "no brew order can be placed now"))
                else:
                    # (0.105.23) the larger source first: 4 brewable plants made a
                    # brew of 4 while the fruit waited for the next cycle (B)
                    # (an older bridge's raw growths are mostly leaves: plants first then)
                    recipe, have = (max(sources, key=lambda x: x[1]) if isinstance(sup_.get("brewable_plants"), int)
                                    else sources[0])
                    jobs = _clamp(math.ceil((target - drink - pending) / per_job), cfg["min_order"], cfg["max_order"])
                    jobs = min(jobs, have)
                    kept_for_kitchen = False
                    if crisis_drink and recipe == "brew_drink":
                        # (0.104.169) the crisis's brewing leaves plants for the kitchen
                        # (beyond what the usual target would brew)
                        usual = math.ceil(max(0, target / cfg["crisis_drink_share"] - drink - pending) / per_job)
                        jobs = min(jobs, max(usual, have - citizens * cfg["crisis_plants_keep_per_dwarf"]))
                    kept_for_kitchen = jobs < 1
                    # (0.100) each brew job fills an empty barrel or pot: no more jobs than there are
                    # (0.104.169, review) less the AI's open brew orders' jobs still to
                    # finish: two orders never want more barrels than there are (a brew
                    # job that finds none is cancelled, and the order looks stalled)
                    if isinstance(sup_.get("empty_barrels"), int):
                        jobs = min(jobs, sup_["empty_barrels"] + int(sup_.get("empty_pots") or 0) - brew_jobs_open(s))
                    if jobs < 1 and crisis_drink and kept_for_kitchen and have > 0:
                        notes.append(f"drink {drink} is below the crisis's target of {round(target)}, but the "
                                     f"{have} brewable plants are kept for the kitchen (at most "
                                     f"{cfg['crisis_plants_keep_per_dwarf']} a dwarf go to the crisis's extra brewing)")
                    elif jobs < 1:
                        notes.append(f"drink {drink} is below the target of {round(target)} but there are no empty "
                                     "barrels or pots to brew into (more are ordered with the containers)")
                    else:
                        proposals.append(Proposal(
                            "drink", {"type": "work_order", "recipe": recipe, "amount": jobs},
                            f"drink {drink} + ~{pending} queued is below the target of {round(target)}"
                            + (" (stocking up for winter)" if winter > 1 else "")
                            + ("" if recipe == "brew_drink" else ", brewed from fruit")
                            + (f" (crisis: drink kept x{cfg['crisis_drink_share']:g}, being drunk eases stress"
                               + ("; the next batch queued while the stills work the last" if queued(s, {recipe}, ai_only=True)
                                  else "") + ")" if crisis_drink else "")
                            + (" (URGENT)" if urgent else ""), 1, True))
    _guard(_drink_rule)

    # (0.99.5) an AI fruit brew with no fermentable fruit only ties up the
    # stills (each job is made, then cancelled): cancel it
    def _drink_fruit_rule():
        sup_ = _d(s.get("supplies"))
        if can_use("orders") and sup_.get("brewable_growths") == 0:
            for o in _l(s.get("orders")):
                if (isinstance(o, dict) and o.get("by_ai") and o.get("recipe") == "brew_drink_from_fruit"
                        and (o.get("amount_left") or 0) > 0 and isinstance(o.get("id"), int)):
                    proposals.append(Proposal("drink_fruit", {"type": "cancel_work_order", "order_id": o["id"]},
                                              f"no fruit a still can brew ({st.get('plant_growths', 0)} growths, none "
                                              "fermentable): cancel the fruit brew, its jobs only tie up the stills", 2))
                    break
    _guard(_drink_fruit_rule)

    # 3. Food --------------------------------------------------------------
    def _food_rule():
        if can_use("stocks", "orders"):
            per_job = cfg["meals_per_job"]
            meals, pending = st.get("prepared_meals", 0), queued(s, MEAL_RECIPES) * per_job
            target = citizens * cfg["meals_per_dwarf"] * buffer * winter
            raw = sum(st.get(k, 0) or 0 for k in RAW_FOOD)
            # (0.104.138) three quarters stocked with an order still cooking: no
            # more on top (Teacheroar: 2,481 of 2,739, its kitchens kept to the best
            # cooks, fine meals ordered 6 times and cancelled as stuck 4)
            cooking = queued(s, MEAL_RECIPES) > 0 and meals >= 0.75 * target
            if meals + pending < target and not cooking:
                # Without readable settings, use the middle grade.
                welfare = traits.get("welfare", 0) if "settings" not in errors else 0
                recipe = ("prepare_lavish_meal" if welfare >= 50 else
                          "prepare_easy_meal" if welfare <= -50 else "prepare_fine_meal")
                ingredients = {"prepare_easy_meal": 2, "prepare_fine_meal": 3, "prepare_lavish_meal": 4}[recipe]
                jobs = _clamp(math.ceil((target - meals - pending) / per_job), cfg["min_order"], cfg["max_order"])
                # (0.100) each job takes whole ingredient stacks: the bridge's count
                # of raw food stacks when it sends one, else items / a typical stack
                stacks = _d(s.get("supplies")).get("food_stacks")
                if not isinstance(stacks, int) or isinstance(stacks, bool):
                    stacks = raw // cfg["food_stack_size"]
                jobs = min(jobs, stacks // ingredients)
                if jobs < 1:
                    # (0.105.35) said, not Needs you: gathering, fishing and the farms answer it
                    notes.append(f"meals are low ({meals} for {citizens} dwarves) and there is too little raw food "
                                 "to cook: the AI gathers, fishes and farms for more; the dwarves eat the raw food "
                                 "there is meanwhile")
                else:
                    proposals.append(Proposal(
                        "food", {"type": "work_order", "recipe": recipe, "amount": jobs},
                        f"meals {meals} + ~{pending} queued is below the target of {round(target)}", 2, True))
    _guard(_food_rule)

    # 4. Noble mandates -------------------------------------------------------
    def _mandate_rule():
        # (item5) a fort that holds nobles low (Deference under -50) still
        # meets a Make mandate while someone holds the guard's office: an unmet
        # one is a crime DF pins on one of the fort's own dwarves and jails them
        # (Hammerstirred, the Hermit hold at Deference -60: 14 "production order
        # violations" for the queen's bucklers, y263-269, office holders chained
        # one after another; 9 died of thirst in the jail). With nobody to
        # punish, the low Deference still leaves them unmet.
        if can_use("mandates", "orders", "settings"):
            if traits.get("deference", 0) < -50:
                due = any(isinstance(m, dict) and m.get("kind") == "Make" and (m.get("remaining") or 0) > 0
                          for m in _l(s.get("mandates")))
                if not (cfg.get("mandates_low_deference", True) and due and justice_held(s)):
                    return
                notes.append("Deference is low, but the noble's mandates are made anyway: unmet, DF jails one "
                             "of the fort's own dwarves for it")
            for m in s["mandates"]:
                if m.get("kind") != "Make" or (m.get("remaining") or 0) <= 0:
                    continue
                item = m.get("item")
                recipe = MANDATE_RECIPES.get(item)
                if item == "SHIELD" and cfg.get("mandate_shields", True):
                    recipe = "wooden_buckler" if m.get("subtype") == "ITEM_SHIELD_BUCKLER" else "wooden_shield"
                metal = None
                if item == "SHOES":
                    recipe = _shoes_recipe(m, st, notes)
                    if recipe is None:
                        continue
                    if recipe == "metal_high_boots":
                        metal = _best_metal(s, m.get("remaining") or 1, m.get("material_token"))
                        if metal is None:
                            # (0.105.35) the AI's call: left unmade until the bars are smelted
                            notes.append("mandate for high boots: not enough weapon-grade metal bars (2 a boot): "
                                         "made once the smelters have them, else the mandate lapses")
                            continue
                if not recipe:
                    notes.append(f"mandate for {item} has no approved recipe yet")
                    continue
                action = {"type": "work_order", "recipe": recipe, "amount": min(m["remaining"], cfg["mandate_max"])}
                if metal:
                    action["material"] = metal
                elif m.get("material"):
                    # "3 gold goblets" can't be met with stone; "granite tables" can,
                    # if we name that stone.
                    if recipe.startswith("stone_") and m.get("material_is_stone") and m.get("material_token"):
                        action["material"] = m["material_token"]
                    else:
                        # (0.105.35) the AI's call: no recipe takes that material, so it lapses
                        notes.append(f"mandate for {m['material']} {item.lower()}: no recipe the AI has takes that "
                                     "material, so it is left to lapse (the noble is upset and a dwarf may be blamed for it)")
                        continue
                if queued(s, {recipe}) > 0:
                    continue
                proposals.append(Proposal(
                    "mandate", action,
                    f"noble mandate: make {m['remaining']} {item.lower()}"
                    f" ({m.get('days_left', '?')} days left)", 3, True))
    _guard(_mandate_rule)

    # 5. Automation tools ---------------------------------------------------
    def _tools_rule():
        if can_use("tools", "settings"):
            tools = s["tools"]
            wood_low = ("stocks" not in errors
                        and st.get("wood", 0) < citizens * cfg["wood_per_dwarf"] * buffer)
            felled, cap = trees_this_year(s, memory)
            quota_near = bool(cap) and felled >= cap * cfg["tree_quota_share"]
            if quota_near:
                notes.append(f"{felled} trees felled this year, of the {cap} the elves allow: no more felling until "
                             "the new year")
                if tools.get("autochop") is True:
                    proposals.append(Proposal("tree_quota", {"type": "tool", "name": "autochop", "enabled": False},
                                              f"{felled} trees felled this year and the elves allow {cap}: turn off "
                                              "autochop until the new year (going over angers them)", 3))
            # (0.100.1, review) and at least 20 animals: an embark's 4 aren't a herd
            herds_big = ("others_on_map" not in errors
                         and s["others_on_map"].get("tame_animals", 0)
                         > max(20, citizens * 0.5 * factor(traits, "husbandry")))
            # (0.104.158) the herd past the fort's size: the eggs no longer hatched
            # (Teacheroar, 1 Nov: 1,121 tame animals for 150 dwarves, most of them
            # fowl from the nest boxes; 2,565 ducks and 950 geese dead, the game at
            # 17 FPS). DFHack's autobutcher keeps 2/4/2/4 of each kind; nestboxes
            # makes every fertile egg a chick.
            tame = int(s["others_on_map"].get("tame_animals", 0) or 0) if "others_on_map" not in errors else 0
            herd_max = max(cfg["herd_min"], citizens * cfg["herd_per_dwarf"]) * factor(traits, "husbandry")
            if tools.get("nestboxes") is True and tame > herd_max:
                proposals.append(Proposal("herd", {"type": "tool", "name": "nestboxes", "enabled": False},
                                          f"{tame} tame animals for {citizens} dwarves (the fort keeps about {int(herd_max)}): "
                                          "turn off nestboxes so not every egg hatches (the eggs are food instead)", 5))
            wanted = {
                "suspendmanager": (True, "keeps jobs from getting stuck"),
                "buildingplan": (True, "planned furniture waits for materials instead of vanishing"),
                "seedwatch": (traits.get("agriculture", 0) > -100, "keeps seeds from being eaten"),
                # without it, new farm plots have no crop chosen and grow nothing
                # (0.105.5) not once the AI sets the plots' crops itself (it rewrites them)
                # (0.105.7 review) back on when the AI's own crop logic can't run
                # (no plot list, only dead plots): crops_owned
                "autofarm": (traits.get("agriculture", 0) > -100 and has_farms(s)
                             and not crops_owned(s, memory) and not getattr(memory, "farm_crops_player", False),
                             "chooses crops for the farm plots by what the fort needs"),
                # (0.104.158) not while the herd is past the fort's size (it comes
                # back on under half of it): every egg hatched kept the butchers busy
                "nestboxes": (traits.get("husbandry", 0) >= 0 and tame <= herd_max * cfg["herd_resume_share"],
                              "lets eggs hatch for more animals"),
                "tailor": (traits.get("welfare", 0) >= -50, "replaces worn-out clothing"),
                "autochop": (wood_low and not quota_near, f"wood is low ({st.get('wood', 0)})"),
                # Slaughter is a big step: only when herds are large AND the player
                # hasn't asked for more animals.
                # (0.103.7) Beast-friends never slaughter (unless the game runs slowly)
                "autobutcher": ((herds_big and traits.get("husbandry", 0) <= 0
                                 and not (memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter")))
                                or (bool(s.get("fps_low")) and "others_on_map" not in errors
                                    and s["others_on_map"].get("tame_animals", 0) > max(20, citizens)),
                                "keeps herds from overrunning the fort"
                                + (" (and the game runs slowly: every creature costs)" if s.get("fps_low") else "")),
                # cuts rough gems at the jeweller's (they sell for far more cut)
                "autogems": ((st.get("rough_gems") or 0) >= cfg["gems_cut_at"]
                             and _has_shop(s["buildings"], "Jewelers"),
                             f"cuts the {st.get('rough_gems') or 0} rough gems at the jeweller's (cut gems sell well)"),
                "autoslab": (_d(s.get("dead")).get("ghosts", 0) > 0 and rules_["engrave_slabs"],
                             f"engraves memorial slabs for the {_d(s.get('dead')).get('ghosts', 0)} ghost(s)"),
            }
            for name, (want, why) in wanted.items():
                if not want or name in memory.tools_player_disabled or tools.get(name) is not False:
                    continue  # unwanted, switched off on purpose, already on, or state unknown
                if memory.tool_attempts.get(name, 0) >= 2:
                    notes.append(f"tried twice to switch on {name} but it stays off; not trying again")
                    continue
                proposals.append(Proposal("tools", {"type": "tool", "name": name, "enabled": True},
                                          f"turn on {name}: {why}", 4))
    _guard(_tools_rule)

    # 6a. Supplies: free containers, hospital and well supplies, water -----
    if can_use("stocks", "orders", "supplies", "locations"):
        found: list[Proposal] = []
        _guard(_supply_rules, s, citizens, cfg, found, notes,
               stonebound=has_rule(memory.culture, "stone_containers"), memory=memory)
        if rules_["order_supplies"]:
            proposals += found

    if can_use("projects", "buildings", "stocks"):
        _guard(_well_rule, s, memory, traits, cfg, proposals, notes)
        _guard(_well_lid_rule, s, proposals, notes)
        _guard(_planned_note, s, notes)
        _guard(_planned_parts_rule, s, proposals, notes)
        _guard(_water_zone_rule, s, proposals, notes, cfg)

    # 6b. Strange moods, the dead ------------------------------------------
    if can_use("moods", "buildings"):
        found = []
        _guard(_mood_rules, s, memory, cfg, found, notes)
        if rules_["mood_workshops"]:
            proposals += found
        else:
            notes += [f"{p.reason} (building it is switched off in the Rules tab)" for p in found]
    if can_use("stocks", "supplies", "buildings"):
        _guard(_mood_reserve_rule, s, memory, cfg, proposals, notes)     # (0.105.31) the mood reserves
    # (0.105.40b) the insane: who, where, the deadly ground near them, the
    # AI's own doors locked between; the near-breaking (planner_insane)
    if "insane" not in errors:
        _guard(_insane_rule, s, cfg, proposals, notes, memory)
    # (item3) a vampire, a werebeast or a murderer among the fort's own: the
    # evidence and its confidence, a cell or a squad (planner_killers)
    if "killers" not in errors:
        _guard(_killer_rule, s, cfg, proposals, notes, memory)
    # (0.105.41, item 11) syndromes beyond infection (carriers kept apart, the
    # syndrome spatter cleaned) and miasma indoors (what rots marked for the dump)
    if "syndromes" not in errors:
        _guard(_syndrome_rule, s, cfg, proposals, notes, memory, rules_)
    if "miasma" not in errors:
        _guard(_miasma_rule, s, cfg, proposals, notes, memory)
    if can_use("dead"):
        _guard(_dead_notes, s, notes, proposals, rules_, memory)

    # 6c-2. Set-ups the AI does itself: the alert shelter, pastures ----------
    def _shelter_rule():
        threat = bool(reachable_threats(s, traits, cfg)) if "others_on_map" not in errors else False
        intrusion_ = "others_on_map" not in errors and bool(unseen_intrusion(s, memory, cfg))
        if _shelter_due(s, memory, threat or intrusion_):
            threat = threat or intrusion_
            proposals.append(Proposal("shelter", {"type": "setup_shelter"},
                                      "no civilian-alert burrow: make an \"AI shelter\" burrow over the inside "
                                      "of the fort and use it for the alarm", 0 if threat else 4))
    _guard(_shelter_rule)
    # (0.105.45) the civilians' shelter away from the threat's way in, moved at
    # once from a great danger inside that comes close (planner_shelter); before
    # the squads' rule, which stations them between the threat and it
    if "shelter_plan" not in errors:
        _guard(_shelter_pick_rule, s, cfg, proposals, notes, memory)

    if can_use("society"):
        _guard(_pasture_rule, s, memory, traits, cfg, proposals, notes)

    # 6d. Society: offices, hunger and thirst, pastures, farms; the metal
    # industry through DFHack's own smelting orders --------------------------
    if can_use("society"):
        _guard(_society_notes, s, traits, citizens, cfg, notes, proposals)
    if can_use("offices"):
        _guard(_offices_refill_rule, s, cfg, notes, proposals, memory)  # (0.104.168)
    if can_use("farms", "projects", "settings"):
        _guard(_farm_rule, s, memory, traits, citizens, cfg, proposals, notes)
    if can_use("society"):
        _guard(_pop_cap_rule, s, memory, cfg, citizens, proposals, notes)
        _guard(_join_rule, s, memory, cfg, proposals)
        _guard(_shrink_rule, s, memory, cfg, citizens, proposals)
    if can_use("military", "buildings", "orders"):
        _guard(_smelting_rule, s, memory, cfg, rules_, proposals, notes)

    # 6c. Military: fill and train the player's squads, send them at threats,
    # close the gate ---------------------------------------------------------
    if can_use("military", "others_on_map"):
        _guard(_military_rules, s, memory, cfg, traits, citizens, proposals, notes)
        _guard(_gate_guard_rule, s, memory, cfg, proposals)
        _guard(_gate_dogs_rule, s, memory, cfg, proposals)
        # (0.105.0, round 2) an army that can fight (brain/planner_army.py)
        _guard(_army_gear_rule, s, memory, cfg, proposals, notes)
        _guard(_quiver_rule, s, memory, cfg, proposals, notes)
        _guard(_bolts_rule, s, memory, cfg, proposals, notes)
        _guard(_flask_rule, s, memory, cfg, proposals, notes)     # (0.105.26)
        _guard(_shelter_squads_rule, s, memory, cfg, proposals, notes)
        # (0.105.40b) a fire breather: no melee squad at it, crossbows from inside only
        _guard(_fire_breather_rule, s, memory, cfg, proposals, notes)
        # (item5) ballistae, the archers' fortifications and posts, the caravan guarded,
        # dangerous wild animals near the dwarves hunted (planner_siege)
        _guard(_siege_rules, s, memory, cfg, proposals, notes)
        # (0.105.45) kill zones: traps in the narrow way in, a drawbridge over a drop (planner_killzone)
        if "killzones" not in errors:
            _guard(_killzone_rule, s, memory, cfg, proposals, notes)
        if can_use("entrances"):
            _guard(_gate_cut_rule, s, memory, cfg, proposals, notes)
        # (item6) a necromancer siege: no squad at overwhelming dead, the alarm, the bodies outside rotted
        if "necro" not in errors:
            _guard(_necro_rule, s, cfg, proposals, notes, memory)
        # (0.105.45) hunting: a party sent after a threat it clearly beats, a reserve home, the retreat
        if "hunt" not in errors:
            _guard(_hunt_rule, s, cfg, proposals, notes, memory)
    # (item6) caged prisoners one by one (keep, or the AI's pit)
    if "captives" not in errors:
        _guard(_captives_rule, s, cfg, proposals, notes, memory)

    # 6. Idle hands ------------------------------------------------------------
    def _idle_rule():
        if can_use("stocks", "orders"):
            ind = factor(traits, "industriousness")
            # (0.105.33 fix) the line on the stricter measure (idle_blocks_share,
            # 0.14 for the old 0.25), still leaning with the strategist's idle_share
            idle_share = (idle_line(s, cfg, "idle_blocks_share") * cfg["idle_share"]
                          / PLANNER_CONFIG["idle_share"] / ind)
            # (0.105.33) the truly idle (no job, no prayer or tavern, not a
            # soldier) when the bridge counts them; else idle_adults, as before
            idle_now = _idle_share(s)
            idle = (dw.get("idle_free") if isinstance(dw.get("idle_free"), int) else dw.get("idle_adults", 0))
            per_job = cfg["blocks_per_job"]
            # (0.104.110) capped, and only from stone the masons may use: Teacheroar
            # (300 dwarves) held 1990 blocks while every boulder quarried went to
            # more of them and the quarry was dug 2,456 times in 87 hours, its
            # miners kept off the levels
            # (0.105.33) a driven fort keeps cutting blocks longer (the cap x Industriousness)
            blocks_target = min(citizens * cfg["blocks_per_dwarf"] * buffer, cfg["blocks_cap"] * ind)
            blocks, pending = st.get("blocks", 0), queued(s, {"stone_blocks"}) * per_job
            usable = _d(s.get("stone_use")).get("usable")
            stone_ok = st.get("boulders", 0) if not isinstance(usable, int) else usable
            if (idle_now > idle_share and stone_ok >= cfg["min_boulders_for_blocks"]
                    and blocks + pending < blocks_target):
                jobs = _clamp(math.ceil((blocks_target - blocks - pending) / per_job),
                              cfg["idle_order_min"], cfg["idle_order_max"])
                proposals.append(Proposal(
                    "idle", {"type": "work_order", "recipe": "stone_blocks", "amount": jobs},
                    f"{idle} of {adults} adults are idle; blocks {blocks} are below {round(blocks_target)}", 5, True))
    _guard(_idle_rule)

    # 6a. Who digs: enough miners for the digging waiting, while picks lie unused
    if can_use("labor"):
        _guard(_labor_rules, s, citizens, cfg, proposals, notes, memory)
        _guard(_free_time_rule, s, citizens, cfg, proposals, notes)
    # (0.105.40 M5) enough haulers for the haul jobs waiting; key workers off hauling
    if "hauling" not in errors:
        _guard(_hauling_labor_rule, s, cfg, citizens, proposals, notes, memory)
    # (item10) wood that lasts: cavern trees when safe, the grove kept; training benches; leather armour
    if "forestry" not in errors:
        _guard(_cavern_logging_rule, s, memory, cfg, citizens, proposals, notes)
        _guard(_grove_rule, s, cfg, citizens, proposals, notes)
    if "benches" not in errors:
        _guard(_bench_caps_rule, s, cfg, proposals, notes)
    if "leather_gear" not in errors:
        _guard(_leather_gear_rule, s, cfg, proposals, notes)

    # 6b. A fresh embark: the first staircase, everything else grows from it ----
    fd = _d(s.get("founding"))
    def _found_rule():
        if fd.get("stairs") is False and "founding" not in errors:
            # (0.105.35) nothing waits for the player: no spot near the wagon, the
            # shaft is looked for further out (found_fort wide); only when that
            # fails too is it Needs you, and the AI keeps trying meanwhile
            if memory.found_failure and memory.found_wide_failure:
                ask_player(notes, f"the AI can't start the fort: no spot for the first staircase near "
                                  f"{fd.get('near') or 'the dwarves'} ({memory.found_failure[:120]}) nor further out "
                                  f"({memory.found_wide_failure[:120]}). The AI digs no shaft into an aquifer, water, "
                                  "a cavern or open space below; it looks again, waiting longer each time, and "
                                  "builds the fort from any staircase down that appears")
            wide = bool(memory.found_failure)
            action = {"type": "found_fort", "wide": True} if wide else {"type": "found_fort"}
            proposals.append(Proposal("found", action,
                                      f"a new fort with no staircase: dig the first stair shaft down from beside "
                                      f"{fd.get('near') or 'the dwarves'}"
                                      + (" (further out: the ground near it won't take one)" if wide else "")
                                      + ", through the soil to the first rock", 1))
    _guard(_found_rule)

    # 6e. Basics outside: a refuse pile (rot indoors makes miasma), a trade depot
    if can_use("buildings", "projects"):
        _guard(_surface_basics, s, cfg, citizens, proposals)
        _guard(_deep_depot_watch, s, notes, proposals)   # (0.105.23) the underground depot's wagons (0.105.30: cleared)
    # 6e-0a. (0.101) Water cutting the fort off from land it would use: a bridge
    if can_use("crossings", "stocks"):
        _guard(_crossing_rule, s, cfg, citizens, traits, proposals, notes, memory)
    # 6e-0. Above ground: the keep round the way in (the Surface ambition)
    if can_use("buildings", "projects"):
        _guard(_keep_rule, s, cfg, citizens, traits, proposals, notes, memory)
        # 6e-0b. (0.105.30) the surface hall (one building above ground at a time)
        _guard(_hall_rule, s, cfg, citizens, traits, proposals, notes, memory, rules_)
    # 6e-0c. (0.105.30) blocks for what is to be built (after the idle hands: not ordered twice)
    if can_use("stocks", "orders", "buildings"):
        _guard(_construction_blocks_rule, s, cfg, citizens, traits, proposals, notes, memory, rules_)
    # 6e-1. Trade: goods to the depot for a caravan, crafts to sell; hauling
    if can_use("buildings", "orders"):
        _guard(_trade_rules, s, cfg, citizens, proposals, notes, traits, memory)
        _guard(_export_bans_notes, s, notes)                 # (0.105.41, item 8) the nobles' export bans
        _guard(_gems_rule, s, cfg, proposals, traits, memory, notes)
        _guard(_cloth_rule, s, cfg, citizens, proposals)
        _guard(_noble_rooms_rule, s, cfg, proposals, memory)
        _guard(_noble_value_rule, s, cfg, proposals, notes, memory)   # (0.105.41)
        _guard(_hauling_rule, s, cfg, citizens, proposals)
        _guard(_spare_mechanisms_rule, s, cfg, traits, proposals)

    # 6e-2. Gates at entrances that turned out not to be real
    if can_use("entrances"):
        _guard(_cleanup_rule, s, memory, proposals)

    # 6f. Metal: furnaces once ore is known, the vein mined, charcoal
    if can_use("buildings", "projects", "industry"):
        _guard(_industry_rules, s, memory, cfg, citizens, proposals, notes)
    if can_use("buildings", "military", "industry"):
        _guard(_alloy_rule, s, memory, cfg, proposals, notes)     # (0.105.40 M7) alloys at the smelter
    # 6f-1. (0.105.40b) adamantine and the underworld: never proposed, said why
    _guard(_deep_hazard_rule, s, proposals, notes)

    # 6g. The watchdog: work orders that don't move, a population that doesn't
    if memory is not None:
        _guard(_watchdog_notes, s, memory, cfg, notes)
        _guard(_deep_notes, s, notes)
        _guard(_needs_notes, s, cfg, notes, proposals, memory)
        _guard(_needs_rules, s, cfg, proposals, rules_, young_fort(s, cfg))
        _guard(_dairy_rule, s, cfg, citizens, proposals)
        _guard(_eggs_rule, s, cfg, proposals)
        _guard(_war_animal_rule, s, cfg, proposals)
        _guard(_stairwell_rule, s, memory, cfg, traits, proposals)
        _guard(_staff_rule, s, cfg, proposals)
        _guard(_traction_rule, s, cfg, proposals, notes)
        _guard(_alerts_rule, s, memory, cfg, proposals, rules_)
        _guard(_location_petition_rules, s, cfg, proposals, notes, rules_, memory)
        _guard(_location_value_rule, s, cfg, proposals, notes, memory)
        _guard(_grandeur_rule, s, cfg, proposals, notes, memory)
        _guard(_meeting_notes, s, notes)
        # (0.105.0, 12b/13b) the world outside: meetings answered, war and peace,
        # goods for export, the messenger and Make contact (brain/planner_world.py)
        if can_use("world"):
            _guard(_meeting_answer_rule, s, cfg, proposals, notes, memory)
            _guard(_world_notes, s, notes, memory)
            _guard(_peace_notes, s, cfg, notes, memory)               # (0.105.41, item 8) war and peace
            _guard(_export_rule, s, cfg, proposals, notes, memory)
        if can_use("offices"):
            _guard(_messenger_rule, s, cfg, proposals, notes)
            if can_use("missions"):
                _guard(_contact_rule, s, cfg, proposals, notes, memory)   # (0.105.24) proposals: send_mission
        if can_use("missions"):
            _guard(_mission_rule, s, cfg, proposals, notes, memory)   # (0.105.39) rescues, artifacts, ruins, raids
        _guard(_complaint_notes, s, cfg, notes)                     # (0.104.168)
        _guard(_vermin_rule, s, cfg, proposals, notes)              # (0.104.168)
        _guard(_location_supply_rules, s, cfg, proposals, notes)
        _guard(_comfort_rules, s, cfg, proposals, notes)
        _guard(_booze_variety_rule, s, memory, cfg, proposals, notes)   # (0.105.24) SameBooze
        _guard(_people_rules, s, cfg, proposals, notes)
        _guard(_kiln_rules, s, cfg, proposals, notes)
        if "paper" not in errors:
            _guard(_paper_rule, s, cfg, proposals, notes, memory)     # (item9) after the kiln: one paper step a cycle
        _guard(_glass_rule, s, cfg, proposals, notes)
        _guard(_petition_rules, s, cfg, proposals, notes)
        _guard(_residency_rule, s, memory, cfg, proposals, notes)         # (0.105.9)
        _guard(_location_access_rule, s, memory, cfg, proposals, notes)   # (0.105.12)
        _guard(_anvil_rule, s, cfg, proposals, notes)
        _guard(_excess_shops_rule, s, cfg, proposals)
        _guard(_water_rules, s, cfg, proposals, notes)
        _guard(_cistern_rule, s, memory, cfg, proposals, notes, rules_)
        _guard(_waterworks_rule, s, memory, cfg, proposals, notes)    # (0.105.0)
        _guard(_feeder_rule, s, cfg, proposals)
        _guard(_stone_rule, s, memory, cfg, proposals, notes)
        _guard(_unsuspend_rule, s, proposals)
        _guard(_water_traffic_rule, s, proposals)
        _guard(_jail_size_rule, s, memory, cfg, proposals, notes)
        _guard(_convict_rule, s, memory, cfg, proposals, notes)
        _guard(_prisoner_water_rule, s, cfg, proposals, notes)       # (item5) no water for the jail
        _guard(_break_fights_rule, s, memory, cfg, proposals)
        _guard(_orphan_jobs_rule, s, proposals)
        _guard(_room_repair_rule, s, proposals)
        _guard(_bench_coffins_rule, s, memory, proposals)
        _guard(_order_slots_rule, s, proposals)
        _guard(_stuck_orders_rule, s, memory, cfg, proposals)
        _guard(_stuck_again_rule, s, memory, cfg, proposals)     # (0.105.35) stuck again: cancelled again
        _guard(_approve_rule, s, memory, cfg, proposals, notes)
        _guard(_sync_offices_rule, s, proposals)
    if can_use("orders", "buildings", "projects"):
        _guard(_bottleneck_rule, s, cfg, citizens, proposals, memory)   # (0.104.169) memory: the crisis
        _guard(_fishery_rule, s, cfg, proposals)
    if can_use("stocks", "farms"):
        _guard(_crop_rules, s, memory, cfg, proposals, notes)
        _guard(_farm_crops_rule, s, memory, cfg, proposals, notes)   # (0.105.5) Hammerstirred: fallow plots
    if can_use("stocks"):
        _guard(_kitchen_rule, s, memory, cfg, proposals)   # (0.100) cooking leaves brewables to the stills
    # idle hands: finished levels smoothed, then engraved, one at a time
    def _polish_rule():
        if can_use("projects") and not young_fort(s, cfg):
            idle = _idle_share(s)          # (0.105.33) the truly idle when the bridge counts them
            # (0.105.33) the levels finished ever (done_total), not the 20 kept:
            # polishing stopped for good once that count saturated
            finished_n = levels_done(s)
            # (0.105.33) Industriousness: a driven fort polishes from fewer idle hands
            share = (idle_line(s, cfg, "polish_idle_share") / factor(traits, "industriousness")
                     / (2 if memory is not None and has_rule(memory.culture, "engrave_history") else 1))
            if idle >= share and not (memory is not None and memory.polished_upto is not None
                                                         and memory.polished_upto == finished_n) \
                    and not polish_paused(memory, abs_tick(s), cfg):
                proposals.append(Proposal("polish", {"type": "polish"},
                                          f"{round(100 * idle)}% of the dwarves are idle: smooth or engrave a "
                                          "finished level (nicer rooms, more wealth)", 7))
    _guard(_polish_rule)

    # 7. Building projects ------------------------------------------------------
    s.pop("_character_slot", None)          # (0.105.10 review) never a reservation from an earlier plan
    if can_use("projects"):
        _guard(_project_rules, s, traits, cfg, proposals, notes, can_use, memory)
    # 7a. (0.104.168) a bedroom per household (after the levels: no second bedrooms level)
    _guard(_homes_rules, s, cfg, traits, proposals, notes)
    # 7b. (0.105.10, 14.1 step 3) the last free slot is the fort's own: other
    # rules' ordinary new levels wait
    kept_ = _guard(character_slot_filter, s, proposals, notes)
    if kept_ is not None:
        proposals = kept_
    # 7c. (0.105.23) a temple goes to the bridge with a size it knows: fort E's
    # urgent temple went without one, "temple needs size" 83 times
    def _temple_size():
        for p_ in proposals:
            if (p_.action.get("type") == "start_project" and p_.action.get("kind") == "temple"
                    and p_.action.get("size") not in ("shrine", "grand")):
                p_.action["size"] = "shrine"
    _guard(_temple_size)

    # 8. The game runs slowly (the overseer measured it while unattended): no
    # newcomers and no new luxury levels until it recovers
    if s.get("fps_low"):
        def _slow_game_hold(proposals):
            keep = ("bedrooms", "dining", "storage", "workshops", "tombs", "hospital", "barracks", "memorial")
            dropped = [p for p in proposals if p.action.get("type") == "start_project"
                       and p.action.get("kind") not in keep and p.rule != "mood"]
            if dropped:
                proposals = [p for p in proposals if p not in dropped]
                notes.append(f"the game runs slowly (FPS {s.get('fps_low')}): {len(dropped)} new level(s) wait "
                             "until it recovers")
            return proposals
        kept = _guard(_slow_game_hold, proposals)
        if kept is not None:
            proposals = kept
        _guard(_slow_game_rules, s, citizens, cfg, proposals, notes, memory)
    else:
        # (0.105.3) a fresh census' clutter cleared at any speed (higher bars)
        _guard(_clutter_rules, s, cfg, proposals, notes, memory)
    # (0.105.27) forbidden items stored, melted, dumped or destroyed (after the
    # clutter rules: worn clothes they rot this cycle aren't marked for the dump)
    _guard(_disposal_rules, s, cfg, proposals, notes, memory, rules_)
    # (0.105.40, 13e) what no dwarf can clean up (unreachable items and
    # creatures, spatter, old dead units), past its thresholds
    if "cleanup" not in errors:
        _guard(_world_cleanup_rule, s, cfg, proposals, notes, memory, rules_)
    # (0.105.41, 13e) traffic zones on the AI's finished levels, a slice a cycle
    if "traffic" not in errors:
        _guard(_traffic_rule, s, cfg, proposals, rules_)
    # (0.105.40b, M6) a roofed food pile with barrels near the kitchen and still
    if "food_store" not in errors:
        _guard(_food_store_rule, s, cfg, proposals, notes, memory)
    # (0.105.41, item 2) wheelbarrows for the AI's stone piles (after the hauling
    # rule: not ordered twice), its feeders linked to its workshops
    if "pile_links" not in errors:
        _guard(_pile_links_rule, s, cfg, citizens, proposals, rules_)
    # (0.105.41, item 4) provisions from the land: hunters while safe, butchery
    # and tanning, a fruit zone, meals of more than one kind, cavern soil farms
    if "provisions" not in errors:
        _guard(_provisions_rules, s, cfg, citizens, proposals, notes, memory)
    # (item 12) the fort's artifacts on display in the AI's rooms behind doors
    if "artifacts" not in errors:
        _guard(_artifact_rule, s, cfg, proposals, notes, rules_)
    # (0.100.1, overnight run) any workshops level another rule starts (a well's
    # parts, the metal works, a bottleneck) brings the missing still, kitchen
    # and carpenter's with it
    def _survival_shops():
        if "buildings" not in errors:
            have_ = {**_d(s["buildings"].get("workshops")), **_d(s["buildings"].get("furnaces"))}
            missing_ = [w for w in SURVIVAL_SHOPS if not have_.get(w)]
            if missing_:
                for p in proposals:
                    a = p.action
                    if a.get("type") == "start_project" and a.get("kind") == "workshops":
                        shops_ = list(a.get("shops") or [])
                        add = [w for w in missing_ if w not in shops_]
                        if add:
                            # (0.105.36) marked: select() leaves an added shop out of the
                            # level when it is held, and never holds a level for it
                            p.action = dict(a, shops=add + shops_,
                                            added_shops=[str(w) for w in add] + list(a.get("added_shops") or []))
                            p.reason += f" (and {', '.join(add)}, which the fort lacks)"
    _guard(_survival_shops)
    # (0.100.1, review) a fresh embark before its first staircase: new levels
    # and wells are dug from the stairs, so asking now is only refused (and the
    # refusals' back-off then held the first levels for days); farm plots go
    # on the surface without digging a farm level
    def _stairs_wait(proposals):
        if fd.get("stairs") is False and "founding" not in errors:
            waiting = [p for p in proposals if p.action.get("type") in ("start_project", "place_well")]
            if waiting:
                proposals = [p for p in proposals if p not in waiting]
                notes.append(f"{len(waiting)} new level(s) or well(s) wait for the first staircase")
            for p in proposals:
                if p.action.get("type") == "farm_plots" and p.action.get("dig"):
                    p.action = {k: v for k, v in p.action.items() if k != "dig"}
        return proposals
    kept = _guard(_stairs_wait, proposals)
    if kept is not None:
        proposals = kept
    # (0.105.7 review) the AI sets the plots' crops (or will this cycle):
    # nothing that switches autofarm back on in the same plan (farm
    # thresholds enable it; the tools rule would too)
    def _autofarm_hold(proposals):
        if any(p.rule == "farm_crops" for p in proposals) or crops_owned(s, memory):
            proposals = [p for p in proposals if not (
                p.action.get("type") == "farm_thresholds"
                or (p.action.get("type") == "tool" and p.action.get("name") == "autofarm" and p.action.get("enabled")))]
        return proposals
    kept = _guard(_autofarm_hold, proposals)
    if kept is not None:
        proposals = kept
    # (0.105.3) no new pasture assignments while the AI's gates are shut (B's 26 pen jobs)
    if "entrances" not in errors:
        kept = _guard(_pasture_hold, s, memory, proposals, notes)
        if kept is not None:            # (0.105.4 review) [] is an answer (all held), not a failure
            proposals = kept
    # (0.105.45) the sweep for things stuck "in progress": after every other
    # rule, so a thing another rule acts on this cycle is left to it
    if "stuck" not in errors:
        _guard(_stuck_rule, s, memory, cfg, proposals, notes)
    # (0.105.29 customs fixes) the fort's customs on every new level the rules
    # proposed without them (one pass, after every rule; before the Hermit
    # hold's hidden_hold filter below, which stamps its own)
    _guard(customs_pass, proposals, memory, traits, citizens)
    # (0.105.23, 14.1 step 4c) Surface -80 or lower: nothing above ground, no level at or above the surface
    kept = _guard(_deep_surface_filter, s, traits, memory, proposals, notes)
    if kept is not None:
        proposals = kept
    # (0.105.0) no trade with a civilisation at war (brain/planner_world.py)
    # (0.105.33) [] is an answer (every proposal was trade with an enemy), not a failure
    if "world" not in errors:
        kept = _guard(_hostile_trade_filter, s, proposals, notes)
        if kept is None:      # (0.105.33 fix) the filter failed: no trade this cycle (fails closed)
            from planner_world import TRADE_ACTIONS
            kept = [p for p in proposals if p.action.get("type") not in TRADE_ACTIONS]
        proposals = kept
    # (0.105.40b) no squad sent out into evil weather at enemies outside (unless enemies are inside)
    if "threats" not in errors or isinstance(s.get("weather"), dict) and s["weather"]:
        kept = _guard(_weather_squad_filter, s, memory, cfg, proposals, notes)
        if kept is not None:
            proposals = kept
    # (0.104.137) crisis mode: expansion waits, recovery goes first
    why = _d(getattr(memory, "crisis", None)).get("why") if memory is not None else None
    if why:
        kept = _guard(crisis.apply, proposals, why, notes)
        if kept is not None:
            proposals = kept
    proposals.sort(key=lambda p: p.priority)
    return proposals, notes


def select(proposals: list[Proposal], state: dict, memory: Memory,
           cfg: dict = PLANNER_CONFIG) -> tuple[list[Proposal], list[str]]:
    """Apply the limits. Returns (allowed, held back with reasons)."""
    now = abs_tick(state)
    orders_today = memory.orders_by_day.get(str(game_day(state)), 0)
    allowed, held = [], []
    fired_this_cycle: set[str] = set()
    # (0.104.89) the strategist's word: a raised rule goes first and skips its
    # cooldown; a held one waits (never a survival or safety rule)
    def _steer(p):
        return steer_of(memory, p.rule, now)
    # (0.105.26) a waiting strange mood's materials: no other rule's work order
    # uses them up (bags, quivers, shoes, jewellery, crafts and cloth re-ordered
    # what a mood had just cancelled)
    mood_recipes, mood_mats = mood_blocked(state)
    # (0.105.31) and the mood reserves: no other rule's order takes the last few
    # (reserve fixes: held at or under the line, else capped at what lies over
    # it; the reserve rule tops a reserve up at the line, so nothing waits for
    # good while it can be made; a noble's mandate is never held by it)
    reserve_recipes = reserve_room(state, cfg)
    for p in sorted(proposals, key=lambda p: p.priority - (2 if (_steer(p) or {}).get("mode") == "raise" else 0)):
        st_ = _steer(p)
        if p.rule == "strategist" and p.action.get("type") == "civ_alert" and not p.action.get("on"):
            # (0.105.36) the strategist's alarm-off is added after plan(): the
            # plan's own holds on the alarm (a berserk dwarf, the undead,
            # citizens in the caverns with a beast) apply to it here
            why_ = alarm_held(normalize(state), memory, cfg)
            if why_:
                held.append(f"strategist: the alarm stays up ({why_[:100]})")
                continue
            # (item4) and its minimum time on
            kept_, gnotes_ = [p], []
            _gs = normalize(state)
            govern_alarm(_gs, memory, cfg, kept_, gnotes_)
            if not kept_:
                held.append(f"strategist: {(gnotes_ or ['the alarm stays up a while yet'])[0][:120]}")
                continue
        if st_ and st_["mode"] == "hold":
            held.append(f"{p.rule}: held by the strategist ({str(st_.get('why') or 'no reason')[:80]})")
            continue
        if p.action.get("type") == "work_order" and p.rule != "mood":
            r_, m_ = str(p.action.get("recipe")), str(p.action.get("material") or "").upper()
            what = mood_recipes.get(r_) or (mood_mats.get(m_) if m_ and not r_.startswith("smelt") else None)
            if what:
                held.append(f"{p.rule}: a strange mood waits for {what}; no {r_} order to use it up meanwhile")
                continue
            room = reserve_recipes.get(r_) if p.rule not in ("mood_reserve", "mandate") else None
            if room and room[0] <= 0:
                held.append(f"{p.rule}: no {r_} order: it would use up {room[1]}")
                continue
            if room and isinstance(p.action.get("amount"), int) and p.action["amount"] > room[0]:
                p.action = dict(p.action, amount=room[0])
                p.reason = f"{p.reason} (at most {room[0]}: {room[1]})"
        last = memory.last_fired.get(cooldown_key(p))      # (v35 fix) per entrance for "stranded"
        cooldown = cfg.get(COOLDOWN_KEYS.get(p.rule, f"{p.rule}_cooldown_ticks"), cfg["rule_cooldown_ticks"])
        if (p.rule not in NO_COOLDOWN and last is not None and not (st_ and st_["mode"] == "raise")
                and 0 <= now - last < cooldown):
            held.append(f"{p.rule}: waiting for its cooldown")
            continue
        if p.rule in LABOR_CAPS and p.action.get("type") == "assign_labor":
            # (v35 fix) at most the rule's cap of dwarves given its labour in a year
            cap = int(cfg.get(LABOR_CAPS[p.rule], 4))
            given = labor_given(memory, p.rule, now)
            if given >= cap:
                held.append(f"{p.rule}: the AI gave {given} dwarves the {p.action.get('job')} labour this year "
                            f"already (at most {cap})")
                continue
            if int(p.action.get("count") or 0) > cap - given:
                p.action = dict(p.action, count=cap - given)
        if cooldown_key(p) in fired_this_cycle and p.rule not in MULTI_PER_CYCLE:
            held.append(f"{p.rule}: already acted this cycle")
            continue
        sc = _d(_d(getattr(memory, "stuck_cancelled", None)).get(str(p.action.get("recipe"))))
        # (0.100.1, review) the fort's own drink and food are never held back by
        # an earlier stuck order of the same recipe (it stalled for want of a
        # still or barrels, which those rules check): brewing stopped 28 days
        hold_days = stuck_hold_days(sc, cfg)
        if (p.action.get("type") == "work_order" and p.rule not in STUCK_HOLD_EXEMPT
                and isinstance(sc.get("tick"), int)
                and 0 <= now - sc["tick"] < hold_days * TICKS_PER_DAY):
            # (0.104.138, 12l) made of something else, when there's one at hand
            alt = stuck_fallback(p, state, memory, cfg, now)
            if alt and not queued(state, {alt["recipe"]}):
                p = Proposal(p.rule, alt, f"{p.reason} (the {p.action.get('recipe')} order got stuck "
                                          f"{(now - sc['tick']) // TICKS_PER_DAY} day(s) ago: "
                                          f"{alt['recipe']} instead)", p.priority, p.is_order)
                sc = {}
        if (p.action.get("type") == "work_order" and p.rule not in STUCK_HOLD_EXEMPT
                and isinstance(sc.get("tick"), int)
                and 0 <= now - sc["tick"] < hold_days * TICKS_PER_DAY):
            held.append(f"{p.rule}: an order for {p.action.get('recipe')} got stuck and was cancelled "
                        f"{(now - sc['tick']) // TICKS_PER_DAY} day(s) ago; tried again after "
                        f"{hold_days} days")
            continue
        b = _d(state.get("buildings"))
        shop = recipe_shop(p.action.get("recipe")) if p.action.get("type") == "work_order" else None
        if shop and (b.get("workshops") is not None or b.get("furnaces") is not None) and not _has_shop(b, shop):
            held.append(f"{p.rule}: no {shop} workshop yet for {p.action.get('recipe')}: ordered once it's built")
            continue
        if not isinstance(getattr(memory, "shops_seen", None), dict):
            memory.shops_seen = {}
        seen = memory.shops_seen
        for w in set(p.action.get("shops") or []):
            # (0.99.4) a start that added a shop doesn't count toward "twice"
            # (region2: 1 -> 3 Craftsdwarfs from two starts, then held for good)
            if str(w) in seen and shop_count(b, str(w)) > int(seen[str(w)] or 0):
                memory.shops_started[str(w)] = 0
                seen.pop(str(w), None)
                if isinstance(getattr(memory, "shops_retried", None), dict):
                    memory.shops_retried.pop(str(w), None)     # (v35 fix) built: its re-starts begin again
                if isinstance(getattr(memory, "shops_held_since", None), dict):
                    memory.shops_held_since.pop(str(w), None)  # (0.105.36) and its hold's clock with them
            elif str(w) not in seen and (memory.shops_started or {}).get(str(w), 0) >= 2:
                # counted before 0.99.4, with nothing to tell a start that worked
                # from one that didn't: one more try, from today's count
                memory.shops_started[str(w)] = 1
                seen[str(w)] = shop_count(b, str(w))
        again = [w for w in (p.action.get("shops") or []) if (memory.shops_started or {}).get(str(w), 0) >= 2]
        # (0.105.36) a strange mood's level is never held by this guard: the
        # count is per shop, whoever started it, and a mood fails in 30-40 days
        if (p.action.get("type") == "start_project" and p.action.get("kind") == "workshops" and again
                and p.rule != "mood"):
            # (0.105.35) nothing waits for the player: held SHOPS_RETRY_DAYS, then
            # one more start (was held for good, "Needs you")
            if not isinstance(getattr(memory, "shops_held_since", None), dict):
                memory.shops_held_since = {}
            since = memory.shops_held_since
            for w in again:
                if not isinstance(since.get(str(w)), int) or since[str(w)] > now:
                    since[str(w)] = now
            # (v35 fix) re-started SHOPS_RETRY_MAX times at most (bounded in
            # total, not only in rate)
            if not isinstance(getattr(memory, "shops_retried", None), dict):
                memory.shops_retried = {}
            tried = memory.shops_retried
            spent = [w for w in again if int(tried.get(str(w)) or 0) >= SHOPS_RETRY_MAX]
            due = [w for w in again if w not in spent and now - since[str(w)] >= SHOPS_RETRY_DAYS * TICKS_PER_DAY]
            for w in due:
                memory.shops_started[str(w)] = 1
                tried[str(w)] = int(tried.get(str(w)) or 0) + 1
                since.pop(str(w), None)
            waiting = [w for w in again if w not in due and w not in spent]
            why = []
            if spent:
                why.append(f"a workshops level for {', '.join(spent)} was started "
                           f"{2 + SHOPS_RETRY_MAX} times and the fort report never showed it built: the AI "
                           "starts it no more (it starts again once one is seen built)")
            if waiting:
                left = max(1, SHOPS_RETRY_DAYS - min((now - since[str(w)]) // TICKS_PER_DAY for w in waiting))
                why.append(f"a workshops level for {', '.join(waiting)} was started twice already and "
                           f"the fort report doesn't show it built: started once more in {left} day(s)")
            out = {str(w) for w in spent + waiting}
            if out:
                # (0.105.36) only the held shops are left out (was: the whole
                # level, so two starts that carried the added Still held every
                # workshops level); held whole when none of its own shops is left
                shops = list(p.action.get("shops") or [])
                added = {str(w) for w in (p.action.get("added_shops") or [])}
                kept = [w for w in shops if str(w) not in out]
                own = [w for w in shops if str(w) not in added]
                if not kept or (own and not [w for w in kept if str(w) not in added]):
                    held.append(f"{p.rule}: {'; '.join(why)}")
                    continue
                held.append(f"{p.rule}: {', '.join(sorted(out))} left out of this level ({'; '.join(why)}); "
                            "the rest of it goes ahead")
                p.action = dict(p.action, shops=kept,
                                added_shops=[w for w in (p.action.get("added_shops") or []) if str(w) not in out])
        loop = _loop_count(memory, p, now)
        if loop is not None:
            held.append(f"{p.rule}: done {loop} times in the last year, a possible loop: held "
                        f"{cfg['loop_hold_days']} days (see the run summary)")
            continue
        ne = no_effect_wait(memory, p, now, cfg)
        if ne is not None:
            held.append(f"{p.rule}: done {cfg.get('no_effect_max', 4)}+ times for the same reason and nothing changed: "
                        f"held {ne} more day(s); {NO_EFFECT_WHY.get(p.rule, 'look in the game')}")
            continue
        stalled = _stalled_days(memory, str(p.action.get("recipe")), now)
        if (p.action.get("type") == "work_order" and p.rule not in EMERGENCY
                and p.rule not in ORDER_HOLD_EXEMPT and stalled is not None and stalled >= cfg["order_hold_days"]):
            held.append(f"{p.rule}: the AI's {p.action.get('recipe')} order hasn't moved in {stalled} days; "
                        "no more until it does")
            continue
        if p.action.get("type") == "place_in_zone" and p.rule not in EMERGENCY:
            zf = zone_full_days(memory, p.action.get("zone_id"), now)
            if zf is not None:
                held.append(f"{p.rule}: zone {p.action.get('zone_id')} has no free floor for a "
                            f"{p.action.get('what') or 'piece'}; looked at again in {zf} day(s)")
                continue
        wait = _refused_wait(memory, p, now, state.get("bridge_version"))
        if wait is not None:
            n = _d(memory.refusals.get(refusal_key(p))).get("n")
            held.append(f"{p.rule}: the game refused it {n} time(s) in a row; tries again in {wait} day(s)" if n
                        else f"{p.rule}: waiting on the game (its last answer was to wait); asks again in "
                             f"{wait} day(s)")      # (0.97: it said "refused 0 time(s)")
            continue
        # (0.104.137) in a crisis, recovery gets extra action slots
        limit = cfg["max_actions_per_cycle"]
        if _d(getattr(memory, "crisis", None)).get("why") and crisis.is_recovery(p):
            limit += cfg["crisis_extra_actions"]
        if (p.rule not in LIMIT_EXEMPT
                and len([a for a in allowed if a.rule not in LIMIT_EXEMPT]) >= limit):
            held.append(f"{p.rule}: action limit for this cycle reached")
            continue
        if (p.is_order and p.rule not in ORDER_HOLD_EXEMPT
                and orders_today >= cfg["max_orders_per_game_day"]):
            held.append(f"{p.rule}: work-order limit for today reached")
            continue
        kind = p.action.get("kind") if p.action.get("type") == "start_project" else None
        if kind in ONE_A_CYCLE and any(a.action.get("type") == "start_project" and a.action.get("kind") == kind
                                       for a in allowed):
            held.append(f"{p.rule}: one new {kind} level a cycle; this one waits its turn")
            continue
        allowed.append(p)
        fired_this_cycle.add(cooldown_key(p))
        if p.is_order:
            orders_today += 1
    return allowed, held


def record(results: list[tuple[Proposal, dict]], state: dict, memory: Memory,
           cfg: dict = PLANNER_CONFIG) -> None:
    """Update memory after acting. ok=True: done. ok=False: refused, nothing
    happened. ok=None: unknown (e.g. the connection timed out mid-action), so
    the cooldown and counts start anyway, to be safe against doing it twice."""
    now = abs_tick(state)
    today = game_day(state)
    crops_set_now = any(p.action.get("type") == "set_farm_crops" and r.get("ok") is True for p, r in results)
    for p, r in results:
        ok = r.get("ok")
        brief_timeout_now = brief_timeout(memory, p, r)       # (0.105.26) a search cut short
        note_labor_given(memory, p, r, now)                   # (v35 fix) LABOR_CAPS
        _record_any_outcome(p.action, r, state, memory, now, brief=brief_timeout_now)
        note_refusal(memory, p, r, now, state.get("bridge_version"))
        note_no_effect(memory, p, ok, now)                 # (0.105.24)
        note_construct(p, r, state, memory, now)           # (0.105.30) wings, seals, soil floors, the hall
        note_reserve_swap(p, r, state, memory)             # (0.105.31 reserve fixes) a fibre swap that did nothing
        note_gate_stuck(p, r, state, memory, now)          # (0.105.32) the unstick step tried, a way dug in
        note_cleanup(p, r, state, memory, now)             # (0.105.40) a cleanup's trial done, what it removed
        note_captives(p, r, memory, now)                   # (item6) the pit's trial done, the prisoners sent
        note_syndromes(p, r, memory, now)                  # (0.105.41, item 11) the contaminant clean's trial done
        note_food_level(p, r, memory)                      # (fix41) one food storage level a kitchen or still
        note_stuck(p, r, memory, now)                      # (0.105.45) the stuck sweep's step done
        if p.action.get("type") == "weather_burrow":
            note_keep_in(memory, now, p.action, ok)        # (item4) evil weather: kept in by the burrow
        note_quarry_dug(p, r, state, memory, now)          # (item7) the quarry marked, the stone then
        note_zone_full(memory, p, r, now)                  # (item7) a zone with no free floor for furniture
        try:
            note_design(p, r, state, memory, now)          # (D0) sites kept, a landmark's refusals and fallback
        except Exception:  # noqa: BLE001  (the design record never stops the cycle's record)
            pass
        if p.action.get("type") == "squad_swap" and p.action.get("unit_id") is not None:
            # (0.104.78) sent home, or found already out: not asked for again a week
            memory.swapped[str(p.action["unit_id"])] = now
            # (0.104.138) kept a year (was 28 days): never swapped twice a year
            for k in [k for k, t in memory.swapped.items() if not isinstance(t, int) or now - t > 336 * TICKS_PER_DAY]:
                del memory.swapped[k]
        if p.action.get("type") == "squad_release" and ok is True and p.action.get("unit_id") is not None:
            # (0.104.164) released for stress or a baby: the fill passes them over 168 days
            memory.released[str(p.action["unit_id"])] = now
            for k in [k for k, t in memory.released.items() if not isinstance(t, int) or now - t > 168 * TICKS_PER_DAY]:
                del memory.released[k]
        if p.rule == "siege_cleanup" and ok is not None:
            memory.pruned_after = int(memory.last_threat_tick or 0)        # (0.104.140) once an attack, done or not
        if (p.action.get("type") == "squad_orders" and isinstance(p.action.get("kill"), list)
                and p.action.get("squad_id") is not None and ok is not False):
            # (0.105.36) not for a refused send: it held a new send a day
            # (0.104.140) what each squad was last sent after (the second wave's memory)
            if not isinstance(getattr(memory, "kill_sent", None), dict):
                memory.kill_sent = {}
            memory.kill_sent[str(p.action["squad_id"])] = [i for i in p.action["kill"] if isinstance(i, int)][:50]
            if not isinstance(getattr(memory, "kill_sent_at", None), dict):
                memory.kill_sent_at = {}
            memory.kill_sent_at[str(p.action["squad_id"])] = now          # (v35 fix) the berserk re-send's cooldown
        if p.action.get("type") == "squad_orders" and p.action.get("clear") and isinstance(
                getattr(memory, "kill_sent", None), dict):
            memory.kill_sent.pop(str(p.action.get("squad_id")), None)
            if isinstance(getattr(memory, "kill_sent_at", None), dict):
                memory.kill_sent_at.pop(str(p.action.get("squad_id")), None)
        if p.action.get("type") == "unstick_uniforms" and ok is True:
            sig = spare_sig(_d(_d(state.get("military")).get("gear")))   # (0.104.138)
            prev = _d(memory.unstick_seen)
            memory.unstick_seen = {"sig": sig, "n": (int(prev.get("n") or 0) + 1) if prev.get("sig") == sig else 1}
        if p.action.get("type") in ("squad_swap", "squad_fill") and ok is True:
            # (0.104.138) who was drafted when: not sent home again for 84 days
            added = _l(_d(r.get("filled")).get("added")) if p.action["type"] == "squad_swap" else _l(r.get("added"))
            for x in added:
                if isinstance(x, dict) and x.get("unit_id") is not None:
                    memory.drafted[str(x["unit_id"])] = now
            for k in [k for k, t in memory.drafted.items() if not isinstance(t, int) or now - t > 336 * TICKS_PER_DAY]:
                del memory.drafted[k]
        left_ = r.get("removable_left") if isinstance(r.get("removable_left"), int) else (
            r.get("removable") if r.get("rejected") else None)
        if p.action.get("type") == "remove_webs" and isinstance(left_, int) and not p.action.get("dry_run"):
            # (0.105.3) a batch of webs removed (or none left to take): the
            # census' count follows, so the next batch comes in days while
            # more are left, not in a week, and none while all are kept
            cen_ = _d(memory.census)
            ic_ = cen_.setdefault("items", {}).setdefault("counts", {})
            if isinstance(ic_, dict):
                ic_["webs_removable"] = left_
                if isinstance(r.get("webs"), int):
                    ic_["webs"] = r["webs"]
                cen_["webs_left"] = {"more": bool(r.get("more")), "tick": now}
        if p.action.get("type") == "dig_stairwell" and ok is True and isinstance(r.get("x"), int):
            # (0.104.82) the district's levels grow from it
            masterplan.note_stairwell(memory, str(p.action.get("district")), r["x"], r["y"])
        if p.action.get("type") == "polish" and "every finished level is polished" in str(r.get("error") or ""):
            memory.polished_upto = levels_done(state)   # again once a level is finished
            # (item7) ...and polish_recheck_days on, doubled each time in a row
            # (D, 13 Nov: refused 20 times, a store or farm level finishing
            # each time: only halls and rooms are polished)
            ps_ = _d(getattr(memory, "polish_seen", None))
            memory.polish_seen = {"n": int(ps_.get("n") or 0) + 1, "tick": now}
        elif p.action.get("type") == "polish" and r.get("ok") is True and int(r.get("designated") or 0) > 0:
            memory.polish_seen = {}
        if ok is False:
            if p.rule == "build":
                # No safe site, the dry run disagreed, or the game refused it
                # (e.g. an older bridge): asking again every cycle won't help;
                # try again in a day.
                cooldown = cfg.get("build_cooldown_ticks", cfg["rule_cooldown_ticks"])
                memory.last_fired[p.rule] = now - cooldown + TICKS_PER_DAY
            elif p.rule == "found" and not brief_timeout_now:
                memory.last_fired[p.rule] = now          # the ground won't allow it: ask again in 3 days
            continue
        memory.last_fired[cooldown_key(p)] = now
        if p.rule not in LOOP_EXEMPT:
            log = memory.action_log.setdefault(refusal_key(p), [])
            log.append(now)
            memory.action_log[refusal_key(p)] = [t for t in log if 0 <= now - t < TICKS_PER_YEAR][-ACTION_LOG_MAX:]
        if p.is_order:
            memory.orders_by_day[str(today)] = memory.orders_by_day.get(str(today), 0) + 1
        memory.recent_actions = (memory.recent_actions
                                 + [{"rule": p.rule, "action": p.action, "ok": ok,
                                     "reason": p.reason[:80]}])[-10:]
        a = p.action
        if a["type"] == "start_project" and a.get("kind") == "workshops":
            for shop in set(a.get("shops") or []):
                memory.shops_started[str(shop)] = memory.shops_started.get(str(shop), 0) + 1
                if str(shop) not in memory.shops_seen:          # the count before the first unanswered start
                    memory.shops_seen[str(shop)] = shop_count(_d(state.get("buildings")), str(shop))
        # (0.105.7 review) a set_farm_crops in this batch wins: a threshold
        # recorded after it put the mode back to "drink"
        if a["type"] == "farm_thresholds" and ok is True and not crops_set_now:
            memory.farm_steer = str(a.get("steer") or "")
        if a["type"] == "tool" and a.get("name") == "autofarm" and a.get("enabled") and ok is True \
                and memory.farm_steer == "crops" and not crops_set_now:
            memory.farm_steer = ""       # (0.105.7 review) autofarm is the fallback again
        if a["type"] == "farm_plots" and a.get("underground") and ok is True:
            memory.farm_under_asked = {"tick": now, "tiles": int(r.get("tiles") or a.get("tiles") or 0)}
        if a["type"] == "set_farm_crops" and ok is True:
            # (0.105.5) the AI sets the crops: autofarm stays off (switched
            # off by the AI, not the player: may come back if this is undone)
            memory.farm_steer = "crops"
            for lst in (memory.tools_seen_on, memory.tools_confirmed_on):
                while "autofarm" in lst:
                    lst.remove("autofarm")
        if a["type"] == "kitchen_brewables" and ok is True:   # (0.100) remember the ban to lift it later
            memory.kitchen_ban = a.get("ban") is True
        if a["type"] == "kitchen_fat" and ok is True:          # (0.104.30)
            memory.fat_ban = a.get("ban") is True
        if a["type"] == "slaughter_one" and ok is True and a.get("mood_unit") is not None:
            memory.mood_slaughter[str(a["mood_unit"])] = now     # (0.105.30) one animal a mood
        if a["type"] == "start_project" and a.get("kind") == "memorial":
            # recorded even when the result is unknown: better one memorial than two
            built = memory.culture.setdefault("memorials_built", [])
            if a.get("name") and a["name"] not in built:
                built.append(a["name"])
            if ok is not False:
                memory.last_memorial_tick = abs_tick(state)
        if ok is None and a["type"] == "civ_alert":
            # (0.105.33) the alarm changed but no reply came: the next report
            # says whether it went through (note_cycle takes ownership then)
            memory.alert_asked = {"on": bool(a.get("on")), "tick": now}
        if ok is None and a["type"] == "tool" and a.get("enabled") is False and a.get("name"):
            # (0.105.33) likewise the AI's own switch-off: not booked as the player's
            memory.tool_off_asked = dict(_d(memory.tool_off_asked), **{str(a["name"]): now})
        if ok is not True:
            continue
        if a["type"] == "cancel_project" and a.get("cavern_well"):
            # (0.104.12) not dug again: the shaft crept for years
            memory.cavern_well_failure = "the last cavern well's shaft was under half dug in a game year: given up"
        if a["type"] == "start_project" and a.get("kind") == "storage":
            memory.storage_started = now                 # (0.104.38)
        if (a["type"] == "start_project" and a.get("kind") == "temple" and a.get("size") == "grand"
                and isinstance(memory.culture, dict)):
            memory.culture["grand_temple"] = now         # (0.105.23) the report keeps no temple's size
        if a["type"] == "start_project" and a.get("growth") and isinstance(memory.culture, dict):
            # (0.104.161) a further hall of a kind: one a season, a lifetime cap (growth_wait)
            gl = memory.culture.setdefault("growth_levels", {})
            prev = _d(gl.get(str(a.get("kind"))))
            gl[str(a.get("kind"))] = {"tick": now, "n": int(prev.get("n") or 0) + 1}
        if a["type"] == "cancel_work_order" and a.get("stuck"):
            # (0.104.37) stuck again soon after the last time: held longer each
            # time (Enxah: gauntlets ordered 43 times, cancelled stuck 11)
            prev = _d(memory.stuck_cancelled.get(str(a["stuck"])))
            n = 1
            if isinstance(prev.get("tick"), int) and now - prev["tick"] < cfg["stuck_again_days"] * TICKS_PER_DAY:
                n = int(prev.get("n") or 1) + 1
            memory.stuck_cancelled[str(a["stuck"])] = {"tick": now, "n": n}
        if a["type"] == "trade_deal" and isinstance(memory.culture, dict) and r.get("traded"):
            memory.culture["trades"] = int(memory.culture.get("trades") or 0) + 1     # (0.103.5) Merchant Princes
            memory.culture["last_trade_year"] = int(_d(state.get("date")).get("year") or 0)   # (0.103.18)
        if a["type"] == "quick_location" and a.get("kind"):
            memory.quick_locations[str(a["kind"])] = now
        if a["type"] == "start_project" and r.get("ok") is True and isinstance(r.get("project_id"), int):
            if is_character_level(a):
                # (0.105.10 review) the report doesn't carry growth or set_piece: remembered here
                memory.character_projects = (list(memory.character_projects or []) + [r["project_id"]])[-40:]
        if a["type"] == "location_access" and r.get("ok") is True and isinstance(r.get("changed"), list):
            ids = [i for i in r["changed"] if isinstance(i, int)]
            mine = [i for i in (memory.locations_closed or []) if isinstance(i, int)]
            memory.locations_closed = (sorted(set(mine) | set(ids)) if a.get("visitors") is False
                                       else [i for i in mine if i not in ids])
            # (0.105.26) when the AI acted (a report older than this reads stale), and the
            # mayor's rest (or the reopen's mark) the action carried: kept only now it went through
            memory.locations_acted = dict(memory.locations_acted or {}, **{str(i): now for i in ids})
            if isinstance(a.get("visitor_shut"), dict) and ids:
                memory.visitor_shut = dict(a["visitor_shut"])
        if (a["type"] == "answer_petition" and a.get("residency") and a.get("accept") and r.get("ok") is True
                and not a.get("ids")):
            # (0.105.9) the probe: is the applicant DF's resident within a few days?
            memory.residency["probe"] = {"id": a.get("id"), "unit": r.get("unit"), "tick": now}
        if a["type"] == "answer_petition" and a.get("accept") and a.get("wish"):
            memory.wishes_agreed[str(a["wish"])] = now
            for k in [k for k, t in memory.wishes_agreed.items() if not isinstance(t, int) or now - t > 2 * TICKS_PER_YEAR]:
                del memory.wishes_agreed[k]
        if a["type"] == "start_project" and a.get("kind") == "garden":
            memory.last_garden_tick = now
            if a.get("name") and a["name"] not in memory.gardens_built:
                memory.gardens_built.append(a["name"])
                if isinstance(memory.culture, dict) and memory.culture.get("set_piece_name") == a["name"]:
                    memory.culture.pop("set_piece_name", None)      # (0.103.20) used
        if a["type"] == "cancel_project" and a.get("memorial"):
            built = memory.culture.get("memorials_built", [])
            if a["memorial"] in built:
                built.remove(a["memorial"])
        if a["type"] == "pull_gate":
            # (0.105.33) a pull only queues a job (a dwarf may never reach the
            # lever): note_cycle reads the lever's state. Only a lever the
            # report gives no state for (an older bridge) is toggled here
            lever = next((g for g in _l(_d(state.get("military")).get("gates"))
                          if isinstance(g, dict) and g.get("id") == a.get("lever_id")), None)
            if not (isinstance(lever, dict) and _lever_state(lever) is not None):
                memory.gate_closed_by_ai = not memory.gate_closed_by_ai
            memory.gate_pull_asked = now          # (0.105.36) a shut read after this is the AI's
        if a["type"] == "set_population_cap":
            slow, strained = "runs slowly" in p.reason, "is strained" in p.reason
            memory.fps_cap = (memory.fps_cap or a.get("cap")) if slow else None
            memory.strain_hold = strained
            # (0.104.120) its own; (0.104.138) only ever lower while the strain lasts
            memory.strain_cap = (min(memory.strain_cap or a.get("cap"), a.get("cap") or 10 ** 6)
                                 if strained else None)
        if a["type"] == "convict" and isinstance(memory.convict_watch, dict):   # (0.104.138)
            got_ = len(r.get("convicted") or []) or int(a.get("max") or 0)
            memory.convict_watch["given"] = int(memory.convict_watch.get("given") or 0) + got_
        if a["type"] == "prioritize_dig" and isinstance(memory.dig_seen, dict):   # (0.104.129)
            rec = memory.dig_seen.setdefault(str(a.get("project_id")), {"dug": None, "tick": now})
            if isinstance(rec, dict):
                rec["raised_ok"] = now
        # (0.105.33) a stalled level's jobs freed, a well's channel renewed:
        # marked here, once done (plan() marked them, so one held by the
        # cycle's limits was never asked again)
        mark_ = {"free_dig_jobs": "freed", "renew_well_dig": "renewed"}.get(a["type"])
        if mark_ and isinstance(memory.dig_seen, dict):
            rec = memory.dig_seen.get(str(a.get("project_id")))
            if isinstance(rec, dict):
                rec[mark_] = now
        if a["type"] == "allow_stone" and a.get("ore") and a.get("stone") not in memory.ores_freed:
            memory.ores_freed.append(a["stone"])                    # (0.104.124)
        if a["type"] == "allow_stone" and a.get("keep") and a.get("stone") in memory.ores_freed:
            memory.ores_freed.remove(a["stone"])
        if a["type"] == "import_orders" and a.get("library") not in memory.libraries_imported:
            memory.libraries_imported.append(a.get("library"))
        if a["type"] == "make_squad" and isinstance(r.get("squad_id"), int) and r["squad_id"] not in memory.squads_made:
            memory.squads_made.append(r["squad_id"])
        if a["type"] == "squad_routine":
            sid = a["squad_id"]
            if "off duty" in str(a.get("routine") or "").lower():
                if sid not in memory.squads_rested:
                    memory.squads_rested.append(sid)        # the AI's own rest: it trains again later
            else:
                if sid not in memory.squads_trained:
                    memory.squads_trained.append(sid)
                if sid in memory.squads_rested:
                    memory.squads_rested.remove(sid)
                memory.last_train_tick = now
        if a["type"] == "civ_alert":
            if a["on"] and r.get("already_on"):
                pass  # someone else's alert: don't take ownership of it
            else:
                memory.ai_alert_raised = bool(a["on"])
                memory.quiet_cycles = 0
                if r.get("on") is None or bool(r.get("on")) == bool(a["on"]):
                    note_alarm_change(memory, now, bool(a["on"]), p.reason)      # (item4)
        if a["type"] == "tool" and a.get("enabled") is False:
            # (0.89) the AI switched it off itself (the elves' quota): not the
            # player's choice, so it may come back on later
            for lst in (memory.tools_seen_on, memory.tools_confirmed_on):
                while a["name"] in lst:
                    lst.remove(a["name"])
            memory.tool_attempts[a["name"]] = 0
        if a["type"] == "tool" and a.get("enabled"):
            name = a["name"]
            memory.tool_attempts[name] = memory.tool_attempts.get(name, 0) + 1
            if name in memory.tools_player_disabled and p.rule == "strategist":
                memory.tools_player_disabled.remove(name)
            if r.get("enabled") is not False and name not in memory.tools_enabled_by_ai:
                memory.tools_enabled_by_ai.append(name)
            if r.get("enabled") is True:
                for lst in (memory.tools_confirmed_on, memory.tools_seen_on):
                    if name not in lst:
                        lst.append(name)
    for k in list(memory.orders_by_day):
        if not k.isdigit() or int(k) < today - 4:
            del memory.orders_by_day[k]


# (0.105.33) a year's ticks kept for each loop key: room for the highest loop
# limit (dismiss_alerts and answer_petition at 400 were never reached at 200)
ACTION_LOG_MAX = max(200, *LOOP_LIMITS.values(), LOOP_LIMIT_DEFAULT)
ASKED_TICKS = TICKS_PER_DAY      # (0.105.33) an unanswered alarm change or switch-off: read off the reports this long


def note_gate_lever(s: dict, memory: Memory) -> None:
    """(0.105.33) Whether the AI's gate is shut, read from the lever (the
    report's `military.gates`, each lever's `state`), not toggled on each
    pull: a pull only queues a job (no dwarf may reach the lever, the job may
    be dropped), and a pull whose reply never came may still happen. Either
    way the toggle was inverted from then on, and the next attack's "close"
    opened the gate. A lever's state when the gate is open is learnt the
    first time it is seen (the current state, or the other one if the memory
    already says the AI shut it); a lever with a pull on its way keeps the
    last reading. The levers the gate watcher pulls (an entrance's
    drawbridge) are not this gate's, as in _military_rules."""
    mil = _d(s.get("military"))
    watched = watched_gate_levers(s)           # (0.105.33 fix) the outer bridge's lever too
    levers = [g for g in _l(mil.get("gates")) if isinstance(g, dict) and g.get("id") is not None]
    opens = {k: v for k, v in _d(memory.gate_open_state).items()
             if k in {str(g["id"]) for g in levers} and isinstance(v, int)}
    closed = None
    for g in levers:
        st = _lever_state(g)
        if st is None or not g.get("linked") or g["id"] in watched:
            continue
        k = str(g["id"])
        shut = g.get("shut")
        if isinstance(shut, bool) and not g.get("pending"):
            # (0.105.36) the report reads the gate itself: the lever's open
            # state is learnt from it, and the gate counts as the AI's shut
            # only if the AI shut it (it pulled, or held it shut before). A
            # gate the player had shut is never learnt as "open" (and opened)
            if not shut:
                opens[k] = st
            elif k not in opens:
                opens[k] = 1 - st
            if closed is None:
                asked = getattr(memory, "gate_pull_asked", None)
                closed = shut and bool(memory.gate_closed_by_ai or (
                    isinstance(asked, int) and 0 <= abs_tick(s) - asked < GATE_PULL_SEEN_DAYS * TICKS_PER_DAY))
            continue
        if k not in opens:
            opens[k] = (1 - st) if memory.gate_closed_by_ai else st
        if closed is None and not g.get("pending"):
            closed = st != opens[k]
    memory.gate_open_state = opens
    if closed is not None:
        memory.gate_closed_by_ai = closed


def polish_paused(memory, now: int, cfg: dict = PLANNER_CONFIG) -> bool:
    """(item7) "every finished level is polished" twice or more in a row (the
    levels finished meanwhile were stores, farms or stairs, which are never
    polished): no polish for polish_recheck_days, doubled for each further
    such answer (at most polish_recheck_max_days), even when another level
    is finished meanwhile. The first answer waits only for a new level."""
    ps = _d(getattr(memory, "polish_seen", None)) if memory is not None else {}
    n, t = ps.get("n"), ps.get("tick")
    if not isinstance(n, int) or n < 2 or not isinstance(t, int):
        return False
    days = min(cfg["polish_recheck_max_days"], cfg["polish_recheck_days"] * 2 ** (n - 2))
    return 0 <= now - t < days * TICKS_PER_DAY


def note_cycle(state: dict, memory: Memory, cfg: dict = PLANNER_CONFIG) -> list[str]:
    """Bookkeeping from a fresh report, BEFORE planning. Returns notes.
    (0.105.33) Each step runs on its own: one failing on an odd report value
    becomes a note and the others run (as plan()'s rules do)."""
    s = normalize(state)
    errors = s["_errors"]
    notes: list[str] = []
    now = abs_tick(state)
    today = game_day(state)

    def _step(fn, *args):
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            notes.append(f"bookkeeping {getattr(fn, '__name__', fn)} failed ({type(e).__name__}: {str(e)[:120]}); "
                         "the rest ran")
            return None

    if "dwarves" not in errors and isinstance(s.get("dwarves"), dict) and "idle_adults" in s["dwarves"]:
        _step(update_idle, s, memory, cfg)
    h = _d(s.get("health"))
    if h and not h.get("error"):
        waits = _step(patient_waits, s, memory, now)            # (0.104.81) moved out of plan()
        if waits is not None:
            memory.patient_since = waits
    if "dwarves" not in errors:
        _step(crisis.update, s, memory, cfg, notes)             # (0.104.137) crisis mode
    if "world" not in errors:
        _step(note_world, s, memory)                            # (0.105.0) grudges, export wishes
    if "missions" not in errors:
        notes += _step(note_missions, s, memory) or []          # (0.105.39) missions followed out and back
    if "stone_use" not in errors:
        notes += _step(note_quarry, s, memory, cfg) or []       # (item7) the last quarry dug and counted
    if "food_store" not in errors:
        notes += _step(note_food, s, memory, cfg) or []         # (0.105.40b, M6) the rotten food followed
    if "hauling" not in errors:
        _step(note_hauling, s, memory, cfg)                     # (0.105.40b fix) haulers to spare since when
    if "others_on_map" not in errors:
        notes += _step(note_lockdown, s, memory, cfg) or []     # (0.105.3) B's sealed hatch: lone intruders, the cap
    if "locations" not in errors:
        _step(note_locations, s, memory, cfg)                   # (0.105.26) moved out of plan()
    if "entrances" not in errors:
        _step(note_gate_stuck_cycle, s, memory)                 # (0.105.32) a gate piece no longer split: forgotten
    _step(note_construct_cycle, s, memory, cfg)                 # (0.105.30) the hall's wait for blocks
    if "military" not in errors:
        _step(note_gate_lever, s, memory)                       # (0.105.33) the AI gate read from its lever
    if "hunt" not in errors:
        notes += _step(note_hunt_cycle, s, memory, cfg) or []   # (0.105.45) hunts' outcomes learned once each
    # (0.104.89) the strategist's raised and held rules run out
    if isinstance(getattr(memory, "steer", None), dict):
        for k in [k for k, v in memory.steer.items() if not (isinstance(v, dict) and isinstance(v.get("until"), int)
                                                              and now < v["until"])]:
            del memory.steer[k]
        # (0.105.33 fix) a raise or hold stored before the strategist refused it
        # (a raised slaughter, a held containers) goes now, not when it runs out
        try:
            from strategist import BUILD_HOLD_MAX_DAYS, HOLD_PROTECTED, RAISE_FORBIDDEN
        except Exception:  # noqa: BLE001
            BUILD_HOLD_MAX_DAYS, HOLD_PROTECTED, RAISE_FORBIDDEN = 14, set(), set()
        b_ = memory.steer.get("build")
        if b_ and b_.get("mode") == "hold":       # and an older, longer hold of build is cut to its two weeks
            b_["until"] = min(b_["until"], now + BUILD_HOLD_MAX_DAYS * TICKS_PER_DAY)
        for k in [k for k, v in memory.steer.items()
                  if (v.get("mode") == "raise" and k in RAISE_FORBIDDEN)
                  or (v.get("mode") == "hold" and (k in HOLD_PROTECTED or k in STEER_PROTECTED))]:
            del memory.steer[k]
    # (0.104.81) one-off keys (a zone, a dwarf, an order) left in the loop
    # log: each key's ticks are kept a year, but the keys themselves grew
    log = getattr(memory, "action_log", None)
    if isinstance(log, dict):
        for k in [k for k, v in log.items() if not any(isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR
                                                        for t in (v or []))]:
            del log[k]
    # An older save of the same fort was loaded: forget "future" timestamps,
    # or every rule would wait until game time caught up. (0.105.33) A
    # value that isn't a tick (a hand-edited or old save) goes too.
    for rule, t in list(memory.last_fired.items()):
        if not isinstance(t, int) or isinstance(t, bool) or t > now:
            del memory.last_fired[rule]
    for k in list(memory.orders_by_day):
        if not k.isdigit() or int(k) > today:
            del memory.orders_by_day[k]

    def settings_and_climate():
        st = s["settings"] if isinstance(s.get("settings"), dict) else {}
        if "settings" not in errors:
            if st.get("fort_goal") == "maintain":
                if memory.maintain_pop is None:
                    memory.maintain_pop = _d(s.get("dwarves")).get("total") or None
            else:
                memory.maintain_pop = None

        # (0.89) the elves' quota counts a year's felling: the count at the year's start
        tr = _d(s.get("diplomacy")).get("trees_removed")
        year = _d(s.get("date")).get("year")
        if isinstance(tr, int) and isinstance(year, int):
            ty = _d(memory.tree_year)
            if ty.get("year") != year or not isinstance(ty.get("base"), int) or tr < ty["base"]:
                memory.tree_year = {"year": year, "base": tr}

        if (_d(s.get("labor")).get("ice") or 0) > 0 and not memory.climate_freezes:
            memory.climate_freezes = True
            notes.append("ice near the fort: water freezes here in winter; the AI stocks up more before it and "
                         "won't rely on a well over surface water")

    _step(settings_and_climate)

    def moods_seen():
        if "moods" not in errors:
            current = {str(m.get("unit_id")) for m in _l(s["moods"].get("list")) if m.get("craft")}
            memory.moods_seen = {k: v for k, v in memory.moods_seen.items() if k in current}
            for k in current:
                memory.moods_seen.setdefault(k, now)
            # (0.105.30) a mood's progress: the items it has fetched, and since when
            # that count last changed (a mood that fetches nothing for a week is
            # said in Needs you, whatever the counts read: D, 8 Nov)
            have = {str(m.get("unit_id")): m.get("items_have") for m in _l(s["moods"].get("list"))
                    if m.get("craft") and m.get("workshop")}
            prog = {k: v for k, v in _d(memory.mood_progress).items() if k in current and isinstance(v, dict)}
            for k, n in have.items():
                if not isinstance(n, int):
                    continue
                if _d(prog.get(k)).get("have") != n:
                    prog[k] = {"have": n, "since": now}
            memory.mood_progress = prog
            memory.mood_slaughter = {k: v for k, v in _d(memory.mood_slaughter).items() if k in current}
            memory.mood_logged = {k: v for k, v in _d(memory.mood_logged).items() if k in current}

    _step(moods_seen)

    def threats_seen():
        if "others_on_map" not in errors:
            ids = reachable_threats(s, _traits(s), cfg)
            now_t = abs_tick(s)
            if ids and isinstance(now_t, int):
                memory.last_threat_tick = now_t           # (0.104.100)
            if great_present(s) and isinstance(now_t, int):
                memory.last_great_tick = now_t
            if ids or (_holding_off(s, memory) and held_off_threats(s)):
                # (0.100.1, review) behind a raised bridge the siege can't walk in,
                # so it stops counting as "can reach": while the AI holds the alarm
                # or the gates, invaders and surface dangers still on the map keep
                # the fort shut (before, the gates opened onto them after 3 cycles)
                memory.quiet_cycles = 0
            else:
                memory.quiet_cycles += 1
                memory.alert_suppressed = []
            # (0.105.36) a failed or missing civ_alert read is not "off": the
            # alarm's ownership and an unanswered change wait for a good read
            # (one bad read read as the player's lowering: the AI never lowered
            # its own alarm again, and the fort stayed in the shelter)
            if "civ_alert" in errors:
                return
            asked = _d(memory.alert_asked)
            if isinstance(asked.get("tick"), int):
                # (0.105.33) an alarm change that got no reply: the report says
                # it went through, so it is the AI's (raised: lowered by the AI
                # later; lowered: not the player's lowering), else forgotten after a day
                if bool(s.get("civ_alert")) == bool(asked.get("on")):
                    memory.ai_alert_raised = bool(asked.get("on"))
                    memory.quiet_cycles = 0
                    memory.alert_asked = {}
                elif not 0 <= now - asked["tick"] < ASKED_TICKS:
                    memory.alert_asked = {}
            if not s.get("civ_alert"):
                if memory.ai_alert_raised:
                    # Our alert is off and we didn't lower it: the player did. Don't
                    # re-raise for the threats they've seen; a NEW threat still counts.
                    memory.alert_suppressed = list(ids)
                    # (0.105.30 live fixes) nor for DF's invasion record (a new one still counts)
                    if isinstance(memory.intrusion, dict) and memory.intrusion:
                        memory.intrusion = dict(memory.intrusion, cleared=True)
                memory.ai_alert_raised = False

    _step(threats_seen)

    def tools_seen():
        if "tools" not in errors:
            # (0.105.7 review) autofarm on again while the AI set the crops (it
            # switched autofarm off, and its own enables leave "crops" first):
            # the player's choice, kept; the AI's crops resume once it's off again
            af = s["tools"].get("autofarm")
            if af is True and memory.farm_steer == "crops" and not memory.farm_crops_player:
                memory.farm_crops_player = True
                notes.append("autofarm was switched back on: it chooses the crops again (the AI stops setting them)")
            elif af is False and memory.farm_crops_player:
                memory.farm_crops_player = False
                memory.farm_steer = "crops"
            # (0.105.36) matched on this good read first, however old: the
            # tools section failing for a day after the ask no longer lets it
            # expire unmatched (the AI's switch-off then read as the player's)
            off_asked = {k: t for k, t in _d(memory.tool_off_asked).items() if isinstance(t, int)}
            for name, on in s["tools"].items():
                if on is True:
                    if name not in memory.tools_seen_on:
                        memory.tools_seen_on.append(name)
                    if name in memory.tools_enabled_by_ai and name not in memory.tools_confirmed_on:
                        memory.tools_confirmed_on.append(name)
                elif on is False and name in off_asked:
                    # (0.105.33) the AI's own switch-off whose reply never came: it went through
                    for lst in (memory.tools_seen_on, memory.tools_confirmed_on):
                        while name in lst:
                            lst.remove(name)
                    memory.tool_attempts[name] = 0
                elif on is False and name in memory.tools_seen_on and name not in memory.tools_player_disabled:
                    # It was running and now it's off: someone chose that. Respect it.
                    memory.tools_player_disabled.append(name)
                    notes.append(f"{name} was switched off; the AI will leave it off")
            # an asked switch-off is settled by this report (off: the AI's; on: it didn't happen)
            memory.tool_off_asked = {k: t for k, t in off_asked.items() if not isinstance(s["tools"].get(k), bool)
                                     and 0 <= now - t < ASKED_TICKS}

    _step(tools_seen)

    def caverns_seen():
        # A cavern newly joined to the fort's ground: map the entrances now
        # (the walls go up from that scan), not at the weekly scan
        d = state.get("deep")
        if isinstance(d, dict) and "error" not in d:
            now_open = sorted(str(c.get("name")) for c in _l(d.get("caverns")) if isinstance(c, dict) and c.get("open"))
            if [c for c in now_open if c not in memory.caverns_open]:
                memory.rescan_entrances = True
                notes.append(f"{', '.join(c for c in now_open if c not in memory.caverns_open)} newly open to the fort: "
                             "the entrances are mapped again now")
            memory.caverns_open = now_open

    _step(caverns_seen)

    def orders_seen():
        # Work orders that don't move, and a population that doesn't (the
        # watchdog: _watchdog_notes reads these)
        if "orders" not in errors:
            seen = set()
            for o in _l(s.get("orders")):
                if not isinstance(o, dict) or o.get("repeats") or o.get("id") is None:
                    continue                      # (a repeating order waits on its conditions by design)
                k = str(o["id"])
                seen.add(k)
                left = o.get("amount_left")
                w = memory.order_watch.get(k)
                if not isinstance(w, dict) or w.get("left") != left or not isinstance(w.get("since"), int) \
                        or w["since"] > now:
                    memory.order_watch[k] = {"left": left, "since": now, "by_ai": bool(o.get("by_ai")),
                                             "what": o.get("recipe") or o.get("reaction") or o.get("job") or "?",
                                             "job": o.get("job")}
                # (0.104.141) a dwarf at work on one of its jobs: moving, however
                # slowly (Teacheroar's ring orders were cancelled at 4-6 left with
                # their last jobs on the benches, and held 28 days)
                if int(_d(o.get("jobs")).get("working") or 0) > 0:
                    memory.order_watch[k]["worked"] = now
            for k in [k for k in memory.order_watch if k not in seen]:
                del memory.order_watch[k]

    _step(orders_seen)

    def pop_seen():
        pop = _d(s.get("dwarves")).get("total")
        if isinstance(pop, int) and pop > 0:
            pw = memory.pop_watch
            if pw.get("pop") != pop or not isinstance(pw.get("since"), int) or pw["since"] > now:
                memory.pop_watch = {"pop": pop, "since": now}

    _step(pop_seen)

    def gear_seen():
        # Gear lying unused (see the arms rule): since when.
        gear = _d(_d(s.get("military")).get("gear"))
        if "military" not in errors and gear and "error" not in gear:
            for k in ("weapons", "body", "helms"):
                if (_d(gear.get("spare")).get(k) or 0) >= cfg["gear_spare_stop"]:
                    memory.gear_spare_since.setdefault(k, now)
                else:
                    memory.gear_spare_since.pop(k, None)
            # (0.104.60) soldiers' places left without a weapon while free ones lie about
            if _weapon_gaps(gear):
                memory.gear_spare_since.setdefault("weapon_gaps", now)
            else:
                memory.gear_spare_since.pop("weapon_gaps", None)
            # (0.105.8) armour places the bridge's own dry run could fill
            if int(_d(gear.get("kit")).get("fillable") or 0) > 0 and int(gear.get("on_duty") or 0) > 0:
                memory.gear_spare_since.setdefault("kit_gaps", now)
            elif isinstance(_d(gear.get("kit")).get("fillable"), int):
                memory.gear_spare_since.pop("kit_gaps", None)

    _step(gear_seen)
    return notes
