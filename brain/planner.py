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
import steer_guard  # noqa: E402  (r4 k1) the strategist's holds and raises judged by class and action kind
from planner_moods import mood_blocked  # noqa: E402  (0.105.26) a waiting mood's materials held from other orders
from planner_moods import reserve_room, note_reserve_swap, _mood_reserve_rule  # noqa: E402  (0.105.31) the mood reserves
from planner_gates import note_gate_stuck, note_gate_stuck_cycle  # noqa: E402  (0.105.32) a gate the game holds shut
from planner_guards import (guard_fail, guard_lines, guard_ok, outdoor_filter,  # noqa: E402,F401  (0.105.48, K6)
                            unknown_filter)
from planner_building import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
import planner_design  # noqa: E402  (D0) the Design track's loop
from planner_design import design_rule, note_design  # noqa: E402
from planner_guided import guided_pass  # noqa: E402  (0.105.47, D1) Guided live
from planner_care import _doctor_post_rule, _infection_rule, _offices_refill_rule, _traction_rest_rule  # noqa: E402  (0.104.168)
from planner_water import _waterworks_rule  # noqa: E402  (0.105.0) moat, pumps, irrigation, magma workshops
from planner_homes import *  # noqa: E402,F401,F403  (0.104.168: homes and households)
from planner_threats import _threat_rules, unseen_intrusion, alarm_held, lone_sneaker  # noqa: E402  (0.105.0 round 3; 0.105.36)
from planner_world import note_contact_sent  # noqa: E402  (0.105.48, K9)
from planner_world import (_contact_rule, _export_rule, _hostile_trade_filter, _meeting_answer_rule,  # noqa: E402
                           _messenger_rule, _world_notes, note_world)  # (0.105.0: the world outside, 12b and 13b)
from planner_peace import _peace_notes  # noqa: E402  (0.105.41, item 8: war and peace)
from planner_bans import _export_bans_notes  # noqa: E402  (0.105.41, item 8: the nobles' export bans)
from planner_missions import _mission_rule, note_missions  # noqa: E402  (0.105.39) missions on the world map
from planner_cleanup import _world_cleanup_rule, note_cleanup  # noqa: E402  (0.105.40) world cleanup for the game's speed
from planner_captives import _captives_rule, _necro_rule, note_captives  # noqa: E402  (item6) prisoners' outcomes, necromancer sieges
from planner_weather import _weather_rules, _weather_squad_filter, note_keep_in  # noqa: E402  (0.105.40b) evil weather
from planner_alarm import govern_alarm, note_alarm_change, reach_alarm_over, reach_raise_held, snatch_alarm  # noqa: E402  (item4) the alarm kept from flapping
from planner_war_hold import (book_unfought, lone_hunted, note_war_hold, unfought,  # noqa: E402  (r1g5)
                             unfought_raise_held, war_hold_filter)
from planner_firebreath import _fire_breather_rule  # noqa: E402  (0.105.40b) no melee squad at a fire breather
from planner_siege import _siege_rules  # noqa: E402  (item5) siege engines, archer posts, caravan guard, wildlife hunts
from planner_hazards import _hazards_rule, magma_alarm  # noqa: E402  (0.105.41, item 7) spilt magma, cave-ins, frost, heat
from planner_insane import _insane_rule  # noqa: E402  (0.105.40b) the insane: deadly ground near them, the AI's doors
from planner_killers import _killer_rule  # noqa: E402  (item3) a killer among the fort's own: cells, a squad
from planner_way_out import _way_out_rule, note_way_out, note_way_out_cycle  # noqa: E402  (0.105.47, J16) a fort never left sealed in
from planner_tantrums import _tantrum_rules, note_tantrum_book  # noqa: E402,F401  (0.105.47) tantrums one dwarf at a time
from planner_training import (_training_squad_rule, guard_training_orders, note_never_draft,  # noqa: E402
                               note_training, prepare_training)  # (0.105.47) the training squad, never draft
from planner_husbandry import _husbandry_rules  # noqa: E402  (0.105.47) the herd by Husbandry: breeders, taming, wool, milk
from order_check import order_gate, note_order_loop, approve_on_place, hold_lifted  # noqa: E402  (0.105.46, I3) the order loop
from planner_mood_help import mood_shelter_rule, note_mood_help  # noqa: E402  (0.105.47, J1) the moods' failures
from planner_hunt import _hunt_rule, note_hunt_cycle  # noqa: E402  (0.105.45) hunting threats the squads can beat
from planner_shelter import _shelter_pick_rule  # noqa: E402  (0.105.45) the shelter away from the threat
from planner_stuck import _stuck_rule, note_stuck  # noqa: E402  (0.105.45) the sweep for things stuck "in progress"
from planner_slots import needs_pass, slots_rules  # noqa: E402  (R2 h3) building slots
from planner_thirst import _thirst_rule, note_thirst, thirst_journal  # noqa: E402,F401  (0.105.46, I2) the thirst watch
from planner_near_gates import _near_gates_rule  # noqa: E402  (0.105.47, I7d) surface work near the gates under a titan
from planner_ice import _ice_rule  # noqa: E402  (0.105.47, I7d) surface water zones, shore wells, traffic before the ice
import fields  # noqa: E402  (0.105.47) the Garden fort's surface fields (masterplan's field customs)
from planner_garden import _garden_court_rule, garden_pace  # noqa: E402,F401  (0.105.47) the garden court
from planner_floor_notes import floors_view, floors_line, _floor_notes  # noqa: E402,F401  (layout B) what the floors are doing, in words
from planner_killzone import _killzone_rule  # noqa: E402  (0.105.45) kill zones at the gates and cavern openings
from planner_lure import _lure_rule  # noqa: E402  (0.105.45) a sealed cavern beast lured into a pocket, cut off
from planner_wells import _winter_water_rule  # noqa: E402  (r1 g3) water that works in winter
from planner_wellsafe import _well_safety_rule  # noqa: E402  (0.105.47) cavern wells made safe, the stranded under one let out
from planner_recovery import _migrants_rule, note_recovery, recovery_apply  # noqa: E402  (0.105.46, I4) collapse recovery
import planner_refusal_streak as refusal_streak  # noqa: E402  (r5 p3) repeated refusals backed off
from planner_outside import _drought_rule, note_outside  # noqa: E402  (r2 h9) the migrant drought, a caravan that never left
from planner_growth import note_pop_cap  # noqa: E402  (r2 h9) the population cap's hold booked
from planner_visitors import note_residency  # noqa: E402  (r2 h9) petitions to stay first seen
from planner_meetings import meeting_open_due, meeting_open_said  # noqa: E402,F401  (0.105.47) meetings opened unattended
from planner_welfare import _welfare_rules  # noqa: E402  (0.105.47, I7b) coffins anywhere, slabs ahead, a cook trained
from planner_hauling import _hauling_labor_rule, note_hauling  # noqa: E402  (0.105.40 M5) hauling balanced
from planner_traffic import _traffic_rule  # noqa: E402  (0.105.41) traffic zones on the AI's own levels
from planner_food import _food_store_rule, note_food  # noqa: E402  (0.105.40b, M6) the food store
from planner_descent import _descent_rule, deep_pass  # noqa: E402  (0.105.47) the stair past the first cavern, the deep levels
from planner_reserves import stock_factor, reserve_cfg, _reserve_storage_rule, reserves_pass  # noqa: E402  (0.105.47) Stockpile
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
from planner_holdfast import (_destroyer_gate_rule, _intruder_guard_rule,  # noqa: E402  (0.105.47, R2 item 7) titans and thieves
                              _kill_hold_filter, _squad_matchup_filter, note_holdfast, note_holdfast_cycle)
from planner_army import (_army_gear_rule, _quiver_rule, _bolts_rule, _flask_rule,  # noqa: E402  (0.105.0, round 2)
                          _shelter_squads_rule, _gate_cut_rule)
from planner_select import (SHOPS_RETRY_DAYS, SHOPS_RETRY_MAX, SQUAD_ORDER_KEYS, SQUAD_WHOLE,  # noqa: E402,F401  (r7 d2)
                            ordered_squads, _is_kill, squad_claim, free_squad_for, select)
from planner_record import record, RECORD_STEPS, ACTION_LOG_MAX  # noqa: E402,F401  (r7 d2)
from planner_cycle import GATE_PULL_SEEN_DAYS, ASKED_TICKS, note_gate_lever, note_cycle  # noqa: E402,F401  (r7 d2)


# (0.105.36) SHELTER_RETRY_DAYS, _shelter_due and _no_shelter_note moved to
# planner_military, beside no_shelter, so every caller paces the shelter alike


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


# (0.105.51) the idle hands' stock furniture once the blocks are at their cap:
# (recipe, the supplies count of free ones)
IDLE_STOCK_FURNITURE = (("stone_door", "doors"), ("stone_cabinet", "cabinets"),
                        ("stone_table", "tables"), ("stone_chair", "chairs"))
IDLE_CRAFTS = ("stone_crafts", "metal_crafts", "wood_crafts", "bone_crafts")


def _idle_at_cap(s: dict, cfg: dict, memory, traits: dict, proposals: list, notes: list, why: str) -> None:
    """(0.105.51) Idle hands with the blocks at their cap: rock crafts in a
    larger batch while the goods to sell are fewer than `idle_crafts_per_dwarf`
    a dwarf (under the trade rule's own line its crafts come first), else stone furniture for
    stock (doors, cabinets, tables, chairs: whichever is fewest) up to
    `idle_furniture_stock` free of each, else said."""
    b = _d(s.get("buildings"))
    sup = _d(s.get("supplies"))
    goods = int(_d(s.get("trade")).get("goods") or 0)
    small = memory is not None and has_rule(getattr(memory, "culture", None), "small_storage")
    if small:
        return          # Waste Not: nothing made for its own sake
    proposed = {_d(p.action).get("recipe") for p in proposals}
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    trade_line = citizens * 2 * factor(traits or {}, "trade")      # planner_trade's crafts rule
    if goods < trade_line:
        return          # the trade rule's crafts come first (its own idle line)
    if (_has_shop(b, "Craftsdwarfs") and goods < citizens * cfg["idle_crafts_per_dwarf"]
            and not queued(s, set(IDLE_CRAFTS)) and not proposed & set(IDLE_CRAFTS)):
        n = cfg["idle_order_min"]
        proposals.append(Proposal("idle", {"type": "work_order", "recipe": "stone_crafts", "amount": n},
                                  f"{why}: {n} rock crafts instead ({goods} goods to sell)", 5, True))
        return
    if not _has_shop(b, "Masons"):
        notes.append(f"{why}; no Masons' workshop for stock furniture: idle hands stay idle")
        return
    recipes = {r for r, _ in IDLE_STOCK_FURNITURE}
    if queued(s, recipes) or proposed & recipes:
        return          # one stock order at a time
    cap = cfg["idle_furniture_stock"]
    counted = [(int(sup[k]), r, k) for r, k in IDLE_STOCK_FURNITURE if isinstance(sup.get(k), int)]
    if len(counted) < len(IDLE_STOCK_FURNITURE):
        return          # an older bridge: the free furniture isn't counted
    have = [c for c in counted if c[0] < cap]
    if not have:
        notes.append(f"{why}, the goods to sell number {goods} and the free furniture is stocked "
                     f"({cap} of each): idle hands stay idle")
        return
    n0, recipe, key = min(have)
    n = min(cap - n0, cfg["idle_order_min"])
    proposals.append(Proposal("idle", {"type": "work_order", "recipe": recipe, "amount": n},
                              f"{why}: {n} stone {key} for stock instead ({n0} free)", 5, True))


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
    early: list[str] = []

    def _pre(fn, fallback, *args):
        """(0.105.48, K6) The plan's preamble guarded: a neutral value on an
        odd report (no sliders, the reserves as configured) and the rules run."""
        try:
            return fn(*args)
        except Exception as e:  # noqa: BLE001
            early.append(f"rule {getattr(fn, '__name__', 'preamble')} failed ({type(e).__name__}: {str(e)[:120]}); "
                         "planned with neutral values")
            return fallback
    traits = _pre(_traits, {}, s)
    cfg = _pre(reserve_cfg, cfg, cfg, traits)          # (0.105.47) the reserves kept follow the Stockpile slider
    dw = s["dwarves"]
    citizens = max(1, dw.get("total", 0))
    adults = max(1, dw.get("adults", 0))
    st = s["stocks"]
    proposals: list[Proposal] = []
    notes: list[str] = early
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

    rules_ = _pre(player_rules, None, s) or player_rules({"settings": {}})   # the Rules tab, read once a plan
    # (0.105.47) the training squad out of the fort's squads and soldiers before any rule
    _guard(prepare_training, s, cfg)
    # (D0, Design track) the fort's design language kept, its landmarks moved
    # on; then the customs it adopts. At Scripts: nothing adopted, nothing proposed
    _guard(design_rule, s, traits, cfg, proposals, notes, memory)
    _guard(_set_adopted, s, memory, traits)
    buffer = stock_factor(traits, cfg)              # (0.105.47) 2^(Stockpile/50): was 2^(Stockpile/100)
    _guard(fields.note, s, cfg.get("garden_fort", True))   # (0.105.47) the surface fields for the field customs
    winter = _pre(winter_factor, 1.0, s, memory)    # stock up before winter (and through it)

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
            # (r1g5) B (y262): lowered "a squad on them" 11 s after "no squad has
            # anyone armed to send": a lone intruder's alarm comes down only while
            # an AI squad's kill order names them (or once they are gone)
            if lone and stand_down and not lone_hunted(s, lone):
                stand_down = False
                if alert_on and memory.ai_alert_raised:
                    notes.append(f"{len(lone)} enemy/enemies inside the fort and no squad's kill order names them: "
                                 "the alarm stays up (it comes down once a squad is on them or they are gone)")
            # (r1g5) E (y256-259): 812 days of alarm for a titan nobody fought:
            # after r1g5_unfought_alarm_days the fort fights or lifts the alarm
            uf = unfought(s, memory, cfg, ids) if ids and alert_on and not stand_down else {}
            if uf.get("mode"):
                book_unfought(s, memory, uf)
            # (0.105.48, K1) the "can reach" alarm's maximum time (planner_alarm)
            capped = "" if stand_down or not alert_on else reach_alarm_over(s, memory, cfg, ids)
            if uf.get("mode") == "lift":
                capped = uf["why"]
            held = reach_raise_held(s, memory, cfg, fresh) if fresh and not alert_on else ""
            if fresh and not alert_on and not held:
                held = unfought_raise_held(s, memory, cfg, fresh)
            # (0.105.48, K16) a snatcher (out of reach like a thief): the alarm, not the gates
            snatch = snatch_alarm(s, memory, cfg) if not ids else {}
            if uf.get("mode") == "fight":
                notes.append(f"the alarm stays up: {uf['why']}")
            elif uf.get("mode") == "keep":
                notes.append(uf["why"])          # (x4) a great danger inside near the civilians: never lifted
            if capped and not hazard_alert(s, cfg):
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False}, capped, 0))
            elif held:
                notes.append(held)
            elif stand_down:
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
            elif snatch.get("cap") and memory.ai_alert_raised and not hazard_alert(s, cfg):
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False}, snatch["cap"], 0))
            elif snatch.get("raise"):
                if ready:
                    proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True}, snatch["raise"], 0))
                elif _shelter_due(s, memory, True):
                    notes.append(f"{len(snatch['ids'])} snatcher(s) among the dwarves: setting up a shelter so "
                                 "the alarm can sound")
                else:
                    notes.append(_no_shelter_note(s, memory, f"{len(snatch['ids'])} snatcher(s) among the dwarves"))
            elif snatch.get("keep"):
                notes.append(snatch["keep"])
            elif not ids and not alert_on and intrusion and lone_sneaker(intrusion):
                # (0.105.51) R3 (15 Nov): every record was one hero of no civ
                # (an artifact seeker); B 4, C 5, F 1 alarms kept the fort from
                # work for one sneaker. The guard (intruder_guard) waits at the
                # stair and the artifact; the alarm sounds once enemies are seen
                # in reach as ever
                notes.append(f"DF reports a lone intruder on the map "
                             f"({max(0, (abs_tick(s) - intrusion['tick']) // 50)} game hour(s) ago), nobody seen "
                             "yet: one sneaker of no civilisation (an artifact seeker or a thief), so no alarm; a "
                             "squad guards the main stair and the artifact it named until it is seen")
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
            elif (not ids and alert_on and memory.ai_alert_raised and not hazard_alert(s, cfg) and intrusion
                  and not lone_sneaker(intrusion)):
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
    # (0.105.47) cavern wells made safe: the watcher, the column, the door, the
    # next level; a dwarf stranded under a well let out before any alarm (planner_wellsafe)
    if "well_safety" not in errors:
        _guard(_well_safety_rule, s, cfg, proposals, notes, memory)
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
               stonebound=bool(_guard(has_rule, memory.culture, "stone_containers")), memory=memory)
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
    # (0.105.47, J1) a gathering mood's workshop and materials inside the shelter while the alarm is up
    if "mood_help" not in errors:
        _guard(mood_shelter_rule, s, memory, cfg, proposals, notes)
    # (0.105.40b) the insane: who, where, the deadly ground near them, the
    # AI's own doors locked between; the near-breaking (planner_insane)
    if "insane" not in errors:
        _guard(_insane_rule, s, cfg, proposals, notes, memory)
    # (item3) a vampire, a werebeast or a murderer among the fort's own: the
    # evidence and its confidence, a cell or a squad (planner_killers)
    if "killers" not in errors:
        _guard(_killer_rule, s, cfg, proposals, notes, memory)
    # (0.105.47, J16) the fort sealed in: the AI's gate opened once the cause
    # is gone, checked, then a way dug out (planner_way_out)
    if "way_out" not in errors:
        _guard(_way_out_rule, s, cfg, proposals, notes, memory)
    # (0.105.41, item 11) syndromes beyond infection (carriers kept apart, the
    # syndrome spatter cleaned) and miasma indoors (what rots marked for the dump)
    if "syndromes" not in errors:
        _guard(_syndrome_rule, s, cfg, proposals, notes, memory, rules_)
    if "miasma" not in errors:
        _guard(_miasma_rule, s, cfg, proposals, notes, memory)
    if can_use("dead"):
        _guard(_dead_notes, s, notes, proposals, rules_, memory)
    # (0.105.47, I7b) coffins anywhere when no tomb level comes, memorial slabs
    # ahead for the dead nobody can reach (each needs the dead section: checked
    # inside), a cook trained (planner_welfare)
    _guard(_welfare_rules, s, cfg, proposals, notes, memory, rules_)

    # 6c-2. Set-ups the AI does itself: the alert shelter, pastures ----------
    def _shelter_rule():
        threat = bool(reachable_threats(s, traits, cfg)) if "others_on_map" not in errors else False
        intrusion_ = "others_on_map" not in errors and bool(unseen_intrusion(s, memory, cfg))
        intrusion_ = intrusion_ or bool(snatcher_ids(s))        # (0.105.48, K16) a snatcher sounds it too
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
    # (0.105.47) the herd by Husbandry (after the waiting grazers' pasture rule)
    if "herd" not in errors:
        _guard(_husbandry_rules, s, memory, traits, cfg, citizens, proposals, notes)

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
        _guard(_migrants_rule, s, memory, cfg, proposals, notes)   # (0.105.46, I4) no migrants to a fallen fort
        _guard(_drought_rule, s, memory, cfg, proposals, notes)    # (r2 h9) no migrants for seasons: why, and what the AI can do
    if can_use("military", "buildings", "orders"):
        _guard(_smelting_rule, s, memory, cfg, rules_, proposals, notes)

    # 6c. Military: fill and train the player's squads, send them at threats,
    # close the gate ---------------------------------------------------------
    # (0.105.48, K6) the gates (the entrances, citizens shut outside, a stuck
    # gate, a way dug in) under their own guard, needing the entrances and the
    # threats but not the military section: one failing squad rule, or an
    # unread military section, no longer silences them
    # (an older bridge sends no entrances section: normalize's empty default isn't one)
    if _d(s.get("entrances")) and "entrances" not in errors and can_use("others_on_map"):
        def _gates_rule():
            any_reach = bool(reachable_threats(s, traits, cfg))
            _gate_rules(s, memory, cfg, rules_, any_reach, proposals, notes, traits)
        _guard(_gates_rule)
    if can_use("military", "others_on_map"):
        _guard(_military_rules, s, memory, cfg, traits, citizens, proposals, notes, gate_rules=False)
        _guard(_training_squad_rule, s, memory, cfg, proposals, notes)    # (0.105.47)
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
        # (0.105.47, R2 item 7) a gate a building destroyer breaks; a squad on the stair for an unseen intruder
        if "entrances" not in errors:
            _guard(_destroyer_gate_rule, s, cfg, proposals, notes, memory)
        _guard(_intruder_guard_rule, s, cfg, proposals, notes, memory)
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
            elif idle_now > idle_share and stone_ok >= cfg["min_boulders_for_blocks"]:
                # (0.105.51) the blocks at their cap: the rule fell silent (R3:
                # F 535 blocks, C 534, half the adults idle for years)
                _idle_at_cap(s, cfg, memory, traits, proposals, notes, f"{idle} of {adults} adults are idle; "
                             f"blocks {blocks} are at {round(blocks_target)}")
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
        # 6e-0b2. (0.105.47) the Garden fort's garden court by the fields
        if "garden_court" not in errors:
            _guard(_garden_court_rule, s, cfg, citizens, traits, proposals, notes, memory, rules_)
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
        _guard(_needs_rules, s, cfg, proposals, rules_, bool(_guard(young_fort, s, cfg)))
        _guard(_dairy_rule, s, cfg, citizens, proposals)
        _guard(_eggs_rule, s, cfg, proposals)
        _guard(_war_animal_rule, s, cfg, proposals, traits)   # (0.105.47) by Militarism
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
        _guard(_petition_rules, s, cfg, proposals, notes, memory)        # (r10 p1) memory: your orders left alone
        _guard(_residency_rule, s, memory, cfg, proposals, notes)         # (0.105.9)
        _guard(_location_access_rule, s, memory, cfg, proposals, notes)   # (0.105.12)
        _guard(_anvil_rule, s, cfg, proposals, notes)
        _guard(_excess_shops_rule, s, cfg, proposals)
        _guard(_water_rules, s, cfg, proposals, notes)
        _guard(_cistern_rule, s, memory, cfg, proposals, notes, rules_)
        _guard(_winter_water_rule, s, memory, cfg, proposals, notes, rules_)   # (r1 g3) water in winter
        _guard(_waterworks_rule, s, memory, cfg, proposals, notes)    # (0.105.0)
        _guard(_feeder_rule, s, cfg, proposals)
        _guard(_stone_rule, s, memory, cfg, proposals, notes)
        _guard(_unsuspend_rule, s, proposals)
        _guard(_water_traffic_rule, s, proposals)
        _guard(_jail_size_rule, s, memory, cfg, proposals, notes)
        _guard(_convict_rule, s, memory, cfg, proposals, notes)
        _guard(_prisoner_water_rule, s, cfg, proposals, notes)       # (item5) no water for the jail
        _guard(_break_fights_rule, s, memory, cfg, proposals)
        # (0.105.47, R2 item 3) the loyalty fix on every tantrum report, posts taken
        # from tantrum-throwers, a guard at the hospitals, the chronic cases (planner_tantrums)
        _guard(_tantrum_rules, s, memory, cfg, proposals, notes)
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
    if can_use("farms", "orders"):
        _guard(_seed_reserve_rule, s, memory, cfg, proposals, notes)   # (r2h6) seeds kept from the cooks
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
        # (R2 h3) a level waiting on the same pieces parked; a dig that never began re-checked
        _guard(slots_rules, s, memory, cfg, proposals, notes)
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
                    # (r2h4) never onto the crossbow squad's lone Bowyer's (it takes no
                    # project slot only alone: lua/ai-builder-projects.lua start_project)
                    if a.get("type") == "start_project" and a.get("kind") == "workshops" and not a.get("crossbows"):
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
    # (0.105.46, I2) the thirst watch: each thirsty dwarf's reason and remedy;
    # after the other rules, so a remedy another rule proposes this cycle (the
    # gates, the prisoners' water, the interrupter's squad) isn't doubled
    if "thirst" not in errors:
        _guard(_thirst_rule, s, cfg, proposals, notes, memory)
    # (0.105.47, I7d) surface work near the gates while a great danger the squads
    # can't beat is about (planner_near_gates); the surface water left alone
    # before it freezes (planner_ice: after planner_wells, whose monthly
    # water_traffic it replaces in ice season)
    if "near_gates" not in errors:
        _guard(_near_gates_rule, s, memory, cfg, proposals, notes)
    _guard(_ice_rule, s, memory, cfg, proposals, notes)
    # (0.105.45) the sweep for things stuck "in progress": after every other
    # rule, so a thing another rule acts on this cycle is left to it
    if "stuck" not in errors:
        _guard(_stuck_rule, s, memory, cfg, proposals, notes)
    # (0.105.29 customs fixes) the fort's customs on every new level the rules
    # proposed without them (one pass, after every rule; before the Hermit
    # hold's hidden_hold filter below, which stamps its own)
    _guard(customs_pass, proposals, memory, traits, citizens)
    # (0.105.47) Verticality: the stair past the first cavern, and the deep
    # districts' new levels under it once it stands (planner_descent); the
    # Stockpile slider's storage levels and their size (planner_reserves)
    if "descent" not in errors:
        _guard(_descent_rule, s, memory, cfg, proposals, notes)
        _guard(deep_pass, proposals, s, memory, cfg, citizens)
    _guard(_reserve_storage_rule, s, memory, cfg, traits, proposals, notes)
    _guard(reserves_pass, proposals, memory, traits, cfg)
    _guard(guided_pass, proposals, s, memory, traits, cfg)   # (0.105.47, D1) every new level in the language
    _guard(_floor_notes, s, memory, cfg, notes)   # (layout B) the floors in words: a fallback, a full floor
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
    # (0.105.47, R2 item 7) never recruits alone at an enemy (the matchup), and no recall flapping
    if "military" not in errors and "others_on_map" not in errors:
        kept = _guard(_squad_matchup_filter, s, memory, cfg, proposals, notes)
        if kept is not None:
            proposals = kept
        kept = _guard(_kill_hold_filter, s, memory, cfg, proposals, notes)
        if kept is not None:
            proposals = kept
        # (r1g5) B, F: no trim, swap or off duty while danger is about
        kept = _guard(war_hold_filter, s, memory, cfg, proposals, notes)
        if kept is not None:
            proposals = kept
    # (0.105.40b) no squad sent out into evil weather at enemies outside (unless enemies are inside)
    if "threats" not in errors or isinstance(s.get("weather"), dict) and s["weather"]:
        kept = _guard(_weather_squad_filter, s, memory, cfg, proposals, notes)
        if kept is not None:
            proposals = kept
    # (0.105.47) no proposal sends the training squad to fight (unless the fort needs it)
    kept = _guard(guard_training_orders, s, proposals, notes)
    if kept is not None:
        proposals = kept
    # (0.105.48, K6) a rule planned on a section that couldn't be read waits
    # (unknown is not zero); no work outside while danger is about
    kept = _guard(unknown_filter, s, proposals, notes)
    if kept is not None:
        proposals = kept
    kept = _guard(outdoor_filter, s, memory, traits, cfg, proposals, notes)
    if kept is not None:
        proposals = kept
    # (0.104.137) crisis mode: expansion waits, recovery goes first
    why = _d(getattr(memory, "crisis", None)).get("why") if memory is not None else None
    if why:
        kept = _guard(crisis.apply, proposals, why, notes, cfg)
        if kept is not None:
            proposals = kept
    # (0.105.46, I4) collapse recovery: survival first, the rest waits (planner_recovery)
    if memory is not None:
        kept = _guard(recovery_apply, proposals, memory, notes)
        if kept is not None:
            proposals = kept
    # (R2 h3) the small needs (paper shop, mood workshops, wells, a still or kitchen
    # while drink or meals are short) marked for the bridge's pool of their own
    _guard(needs_pass, s, cfg, proposals, memory)
    # (r5 p3) a refusal streak's wait, said once when it begins (select() clears it)
    said = _guard(refusal_streak.notes, memory, cfg)
    notes.extend(n for n in (said or []) if n not in notes)
    proposals.sort(key=lambda p: p.priority)
    return proposals, notes


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
