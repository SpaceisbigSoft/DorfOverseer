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
planner_homes, planner_water, planner_threats, planner_world, planner_army.
"""

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

from planner_core import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_military import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_industry import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_society import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
import crisis  # noqa: E402  (0.104.137)
from planner_moods import mood_blocked  # noqa: E402  (0.105.26) a waiting mood's materials held from other orders
from planner_building import *  # noqa: E402,F401,F403  (0.104.83: the planner in parts)
from planner_care import _doctor_post_rule, _infection_rule, _offices_refill_rule, _traction_rest_rule  # noqa: E402  (0.104.168)
from planner_water import _waterworks_rule  # noqa: E402  (0.105.0) moat, pumps, irrigation, magma workshops
from planner_homes import *  # noqa: E402,F401,F403  (0.104.168: homes and households)
from planner_threats import _threat_rules  # noqa: E402  (0.105.0 round 3: threats answered)
from planner_world import (_contact_rule, _export_rule, _hostile_trade_filter, _meeting_answer_rule,  # noqa: E402
                           _messenger_rule, _world_notes, note_world)  # (0.105.0: the world outside, 12b and 13b)
from planner_construct import (_hall_rule, _construction_blocks_rule,  # noqa: E402  (0.105.30) construction
                               note_construct, note_construct_cycle)
from planner_army import (_army_gear_rule, _quiver_rule, _bolts_rule, _flask_rule,  # noqa: E402  (0.105.0, round 2)
                          _shelter_squads_rule, _gate_cut_rule)


def plan(state: dict, memory: Memory, cfg: dict = PLANNER_CONFIG) -> tuple[list[Proposal], list[str]]:
    """Return (proposals, notes). Notes say what the planner wanted but couldn't do.
    Reads memory; never changes it."""
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
    buffer = factor(traits, "stockpile")
    winter = winter_factor(s, memory)               # stock up before winter (and through it)

    # 1. Threat alert ------------------------------------------------------
    if can_use("others_on_map"):
        ids = reachable_threats(s, traits, cfg)
        fresh = [i for i in ids if i not in memory.alert_suppressed]
        alert_on = bool(s.get("civ_alert"))
        ready = s.get("civ_alert_ready") is True
        # (0.105.3) B (2 Nov): the alarm stayed up 2.5 hours for one thief
        # inside. For a lone intruder it is held `lone_intruder_alert_ticks`
        # at most (the squad deals with them); after a lifted lockdown it
        # waits for a new enemy (note_lockdown)
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
            elif _shelter_possible(s, memory):
                notes.append(f"{len(fresh)} threat(s) can reach the dwarves: setting up a shelter so the "
                             "alarm can sound")
            else:
                ask_player(notes, f"{len(fresh)} threat(s) can reach the dwarves, but no civilian-alert "
                             "burrow is set up, so the AI can't sound the alarm")
        elif ids and not fresh and not alert_on:
            notes.append(f"{len(ids)} threat(s) can reach the dwarves; you cleared the alert for "
                         "them, so the AI is leaving it off")
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

    # 1b. Hazards: fire, clouds, flooding, berserk citizens, cursed, prisoners
    if can_use("hazards"):
        _guard(_hazard_rules, s, memory, cfg, proposals, notes, rules_)
    # (0.105.0) round 3: fire guarded, prisoners, thieves, the undead, werebeasts, cavern beasts, the wounded
    if can_use("threats"):
        _guard(_threat_rules, s, memory, cfg, proposals, notes)

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
            plants, fruit = st.get("plants", 0) or 0, st.get("plant_growths", 0) or 0
            sup_ = _d(s.get("supplies"))
            if isinstance(sup_.get("brewable_plants"), int):
                # (0.99.5) only what a still can brew (the bridge reads each
                # material's DRINK_MAT): region2's 325 growths were all leaves
                # and the like, and the fruit order's jobs were cancelled
                # ("Needs unrotten fermentable leaf or fruit") while drink fell
                plants, fruit = sup_["brewable_plants"], int(sup_.get("brewable_growths") or 0)
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
                ask_player(notes, f"drink is low ({drink} for {citizens} dwarves) but there are no plants or "
                           "fruit a still can brew (farm brewable crops: plump helmets, and others by the season)")
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

    # (0.99.5) an AI fruit brew with no fermentable fruit only ties up the
    # stills (each job is made, then cancelled): cancel it
    sup_ = _d(s.get("supplies"))
    if can_use("orders") and sup_.get("brewable_growths") == 0:
        for o in _l(s.get("orders")):
            if (isinstance(o, dict) and o.get("by_ai") and o.get("recipe") == "brew_drink_from_fruit"
                    and (o.get("amount_left") or 0) > 0 and isinstance(o.get("id"), int)):
                proposals.append(Proposal("drink_fruit", {"type": "cancel_work_order", "order_id": o["id"]},
                                          f"no fruit a still can brew ({st.get('plant_growths', 0)} growths, none "
                                          "fermentable): cancel the fruit brew, its jobs only tie up the stills", 2))
                break

    # 3. Food --------------------------------------------------------------
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
                ask_player(notes, f"meals are low ({meals} for {citizens} dwarves) but there is too little raw food")
            else:
                proposals.append(Proposal(
                    "food", {"type": "work_order", "recipe": recipe, "amount": jobs},
                    f"meals {meals} + ~{pending} queued is below the target of {round(target)}", 2, True))

    # 4. Noble mandates -------------------------------------------------------
    if can_use("mandates", "orders", "settings") and traits.get("deference", 0) >= -50:
        for m in s["mandates"]:
            if m.get("kind") != "Make" or (m.get("remaining") or 0) <= 0:
                continue
            item = m.get("item")
            recipe = MANDATE_RECIPES.get(item)
            metal = None
            if item == "SHOES":
                recipe = _shoes_recipe(m, st, notes)
                if recipe is None:
                    continue
                if recipe == "metal_high_boots":
                    metal = _best_metal(s, m.get("remaining") or 1, m.get("material_token"))
                    if metal is None:
                        ask_player(notes, "mandate for high boots: not enough weapon-grade metal bars")
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
                    ask_player(notes, f"mandate for {m['material']} {item.lower()} needs a material "
                                 "the AI can't choose yet")
                    continue
            if queued(s, {recipe}) > 0:
                continue
            proposals.append(Proposal(
                "mandate", action,
                f"noble mandate: make {m['remaining']} {item.lower()}"
                f" ({m.get('days_left', '?')} days left)", 3, True))

    # 5. Automation tools ---------------------------------------------------
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

    # 6a. Supplies: free containers, hospital and well supplies, water -----
    if can_use("stocks", "orders", "supplies", "locations"):
        found: list[Proposal] = []
        _supply_rules(s, citizens, cfg, found, notes, stonebound=has_rule(memory.culture, "stone_containers"),
                      memory=memory)
        if rules_["order_supplies"]:
            proposals += found

    if can_use("projects", "buildings", "stocks"):
        _guard(_well_rule, s, memory, traits, cfg, proposals, notes)
        _guard(_well_lid_rule, s, proposals, notes)
        _guard(_planned_note, s, notes)
        _guard(_planned_parts_rule, s, proposals, notes)
        _guard(_water_zone_rule, s, proposals, notes)

    # 6b. Strange moods, the dead ------------------------------------------
    if can_use("moods", "buildings"):
        found = []
        _guard(_mood_rules, s, memory, cfg, found, notes)
        if rules_["mood_workshops"]:
            proposals += found
        else:
            notes += [f"{p.reason} (building it is switched off in the Rules tab)" for p in found]
    if can_use("dead"):
        _guard(_dead_notes, s, notes, proposals, rules_, memory)

    # 6c-2. Set-ups the AI does itself: the alert shelter, pastures ----------
    if _shelter_possible(s, memory):
        threat = bool(reachable_threats(s, traits, cfg)) if "others_on_map" not in errors else False
        proposals.append(Proposal("shelter", {"type": "setup_shelter"},
                                  "no civilian-alert burrow: make an \"AI shelter\" burrow over the inside "
                                  "of the fort and use it for the alarm", 0 if threat else 4))
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
        if can_use("entrances"):
            _guard(_gate_cut_rule, s, memory, cfg, proposals, notes)

    # 6. Idle hands ------------------------------------------------------------
    if can_use("stocks", "orders"):
        idle_share = cfg["idle_share"] / factor(traits, "industriousness")
        idle = dw.get("idle_adults", 0)
        per_job = cfg["blocks_per_job"]
        # (0.104.110) capped, and only from stone the masons may use: Teacheroar
        # (300 dwarves) held 1990 blocks while every boulder quarried went to
        # more of them and the quarry was dug 2,456 times in 87 hours, its
        # miners kept off the levels
        blocks_target = min(citizens * cfg["blocks_per_dwarf"] * buffer, cfg["blocks_cap"])
        blocks, pending = st.get("blocks", 0), queued(s, {"stone_blocks"}) * per_job
        usable = _d(s.get("stone_use")).get("usable")
        stone_ok = st.get("boulders", 0) if not isinstance(usable, int) else usable
        if (idle > adults * idle_share and stone_ok >= cfg["min_boulders_for_blocks"]
                and blocks + pending < blocks_target):
            jobs = _clamp(math.ceil((blocks_target - blocks - pending) / per_job),
                          cfg["idle_order_min"], cfg["idle_order_max"])
            proposals.append(Proposal(
                "idle", {"type": "work_order", "recipe": "stone_blocks", "amount": jobs},
                f"{idle} of {adults} adults are idle; blocks {blocks} are below {round(blocks_target)}", 5, True))

    # 6a. Who digs: enough miners for the digging waiting, while picks lie unused
    if can_use("labor"):
        _guard(_labor_rules, s, citizens, cfg, proposals, notes, memory)
        _guard(_free_time_rule, s, citizens, cfg, proposals, notes)

    # 6b. A fresh embark: the first staircase, everything else grows from it ----
    fd = _d(s.get("founding"))
    if fd.get("stairs") is False and "founding" not in errors:
        if memory.found_failure:
            ask_player(notes, f"the AI can't start the fort: {memory.found_failure}. Dig a staircase down from "
                              "the surface into the ground yourself, and the AI builds everything from it")
        proposals.append(Proposal("found", {"type": "found_fort"},
                                  f"a new fort with no staircase: dig the first stair shaft down from beside "
                                  f"{fd.get('near') or 'the dwarves'}, through the soil to the first rock", 1))

    # 6e. Basics outside: a refuse pile (rot indoors makes miasma), a trade depot
    if can_use("buildings", "projects"):
        _guard(_surface_basics, s, cfg, citizens, proposals)
        _guard(_deep_depot_watch, s, notes)      # (0.105.23) the underground depot's wagons
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
        _guard(_construction_blocks_rule, s, cfg, citizens, traits, proposals, notes, memory)
    # 6e-1. Trade: goods to the depot for a caravan, crafts to sell; hauling
    if can_use("buildings", "orders"):
        _guard(_trade_rules, s, cfg, citizens, proposals, notes, traits, memory)
        _guard(_gems_rule, s, cfg, proposals)
        _guard(_cloth_rule, s, cfg, citizens, proposals)
        _guard(_noble_rooms_rule, s, cfg, proposals, memory)
        _guard(_hauling_rule, s, cfg, citizens, proposals)
        _guard(_spare_mechanisms_rule, s, cfg, traits, proposals)

    # 6e-2. Gates at entrances that turned out not to be real
    if can_use("entrances"):
        _guard(_cleanup_rule, s, memory, proposals)

    # 6f. Metal: furnaces once ore is known, the vein mined, charcoal
    if can_use("buildings", "projects", "industry"):
        _guard(_industry_rules, s, memory, cfg, citizens, proposals, notes)

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
        _guard(_location_value_rule, s, cfg, proposals, notes)
        _guard(_grandeur_rule, s, cfg, proposals, notes)
        _guard(_meeting_notes, s, notes)
        # (0.105.0, 12b/13b) the world outside: meetings answered, war and peace,
        # goods for export, the messenger and Make contact (brain/planner_world.py)
        if can_use("world"):
            _guard(_meeting_answer_rule, s, cfg, proposals, notes, memory)
            _guard(_world_notes, s, notes, memory)
            _guard(_export_rule, s, cfg, proposals, notes, memory)
        if can_use("offices"):
            _guard(_messenger_rule, s, cfg, proposals, notes)
            if can_use("missions"):
                _guard(_contact_rule, s, cfg, proposals, notes, memory)   # (0.105.24) proposals: send_mission
        _guard(_complaint_notes, s, cfg, notes)                     # (0.104.168)
        _guard(_vermin_rule, s, cfg, proposals, notes)              # (0.104.168)
        _guard(_location_supply_rules, s, cfg, proposals, notes)
        _guard(_comfort_rules, s, cfg, proposals, notes)
        _guard(_booze_variety_rule, s, memory, cfg, proposals, notes)   # (0.105.24) SameBooze
        _guard(_people_rules, s, cfg, proposals, notes)
        _guard(_kiln_rules, s, cfg, proposals, notes)
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
        _guard(_break_fights_rule, s, memory, cfg, proposals)
        _guard(_orphan_jobs_rule, s, proposals)
        _guard(_room_repair_rule, s, proposals)
        _guard(_bench_coffins_rule, s, memory, proposals)
        _guard(_order_slots_rule, s, proposals)
        _guard(_stuck_orders_rule, s, memory, cfg, proposals)
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
    if can_use("projects") and not young_fort(s, cfg):
        dw = _d(s.get("dwarves"))
        idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
        finished_n = _d(s.get("projects")).get("finished")
        share = cfg["polish_idle_share"] / (2 if memory is not None and has_rule(memory.culture, "engrave_history") else 1)
        if idle >= share and not (memory is not None and memory.polished_upto is not None
                                                     and memory.polished_upto == finished_n):
            proposals.append(Proposal("polish", {"type": "polish"},
                                      f"{round(100 * idle)}% of the dwarves are idle: smooth or engrave a "
                                      "finished level (nicer rooms, more wealth)", 7))

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
    for p_ in proposals:
        if (p_.action.get("type") == "start_project" and p_.action.get("kind") == "temple"
                and p_.action.get("size") not in ("shrine", "grand")):
            p_.action["size"] = "shrine"

    # 8. The game runs slowly (the overseer measured it while unattended): no
    # newcomers and no new luxury levels until it recovers
    if s.get("fps_low"):
        keep = ("bedrooms", "dining", "storage", "workshops", "tombs", "hospital", "barracks", "memorial")
        dropped = [p for p in proposals if p.action.get("type") == "start_project"
                   and p.action.get("kind") not in keep and p.rule != "mood"]
        if dropped:
            proposals = [p for p in proposals if p not in dropped]
            notes.append(f"the game runs slowly (FPS {s.get('fps_low')}): {len(dropped)} new level(s) wait "
                         "until it recovers")
        _guard(_slow_game_rules, s, citizens, cfg, proposals, notes, memory)
    else:
        # (0.105.3) a fresh census' clutter cleared at any speed (higher bars)
        _guard(_clutter_rules, s, cfg, proposals, notes, memory)
    # (0.105.27) forbidden items stored, melted, dumped or destroyed (after the
    # clutter rules: worn clothes they rot this cycle aren't marked for the dump)
    _guard(_disposal_rules, s, cfg, proposals, notes, memory, rules_)
    # (0.100.1, overnight run) any workshops level another rule starts (a well's
    # parts, the metal works, a bottleneck) brings the missing still, kitchen
    # and carpenter's with it
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
                        p.action = dict(a, shops=add + shops_)
                        p.reason += f" (and {', '.join(add)}, which the fort lacks)"
    # (0.100.1, review) a fresh embark before its first staircase: new levels
    # and wells are dug from the stairs, so asking now is only refused (and the
    # refusals' back-off then held the first levels for days); farm plots go
    # on the surface without digging a farm level
    if fd.get("stairs") is False and "founding" not in errors:
        waiting = [p for p in proposals if p.action.get("type") in ("start_project", "place_well")]
        if waiting:
            proposals = [p for p in proposals if p not in waiting]
            notes.append(f"{len(waiting)} new level(s) or well(s) wait for the first staircase")
        for p in proposals:
            if p.action.get("type") == "farm_plots" and p.action.get("dig"):
                p.action = {k: v for k, v in p.action.items() if k != "dig"}
    # (0.105.7 review) the AI sets the plots' crops (or will this cycle):
    # nothing that switches autofarm back on in the same plan (farm
    # thresholds enable it; the tools rule would too)
    if any(p.rule == "farm_crops" for p in proposals) or crops_owned(s, memory):
        proposals = [p for p in proposals if not (
            p.action.get("type") == "farm_thresholds"
            or (p.action.get("type") == "tool" and p.action.get("name") == "autofarm" and p.action.get("enabled")))]
    # (0.105.3) no new pasture assignments while the AI's gates are shut (B's 26 pen jobs)
    if "entrances" not in errors:
        kept = _guard(_pasture_hold, s, memory, proposals, notes)
        if kept is not None:            # (0.105.4 review) [] is an answer (all held), not a failure
            proposals = kept
    # (0.105.29 customs fixes) the fort's customs on every new level the rules
    # proposed without them (one pass, after every rule; before the Hermit
    # hold's hidden_hold filter below, which stamps its own)
    _guard(customs_pass, proposals, memory, traits, citizens)
    # (0.105.23, 14.1 step 4c) Surface -80 or lower: nothing above ground, no level at or above the surface
    kept = _guard(_deep_surface_filter, s, traits, memory, proposals, notes)
    if kept is not None:
        proposals = kept
    # (0.105.0) no trade with a civilisation at war (brain/planner_world.py)
    if "world" not in errors:
        proposals = _guard(_hostile_trade_filter, s, proposals, notes) or proposals
    # (0.104.137) crisis mode: expansion waits, recovery goes first
    why = _d(getattr(memory, "crisis", None)).get("why") if memory is not None else None
    if why:
        proposals = crisis.apply(proposals, why, notes)
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
    for p in sorted(proposals, key=lambda p: p.priority - (2 if (_steer(p) or {}).get("mode") == "raise" else 0)):
        st_ = _steer(p)
        if st_ and st_["mode"] == "hold":
            held.append(f"{p.rule}: held by the strategist ({str(st_.get('why') or 'no reason')[:80]})")
            continue
        if p.action.get("type") == "work_order" and p.rule != "mood":
            r_, m_ = str(p.action.get("recipe")), str(p.action.get("material") or "").upper()
            what = mood_recipes.get(r_) or (mood_mats.get(m_) if m_ and not r_.startswith("smelt") else None)
            if what:
                held.append(f"{p.rule}: a strange mood waits for {what}; no {r_} order to use it up meanwhile")
                continue
        last = memory.last_fired.get(p.rule)
        cooldown = cfg.get(COOLDOWN_KEYS.get(p.rule, f"{p.rule}_cooldown_ticks"), cfg["rule_cooldown_ticks"])
        if (p.rule not in NO_COOLDOWN and last is not None and not (st_ and st_["mode"] == "raise")
                and 0 <= now - last < cooldown):
            held.append(f"{p.rule}: waiting for its cooldown")
            continue
        if p.rule in fired_this_cycle and p.rule not in MULTI_PER_CYCLE:
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
            elif str(w) not in seen and (memory.shops_started or {}).get(str(w), 0) >= 2:
                # counted before 0.99.4, with nothing to tell a start that worked
                # from one that didn't: one more try, from today's count
                memory.shops_started[str(w)] = 1
                seen[str(w)] = shop_count(b, str(w))
        again = [w for w in (p.action.get("shops") or []) if (memory.shops_started or {}).get(str(w), 0) >= 2]
        if p.action.get("type") == "start_project" and p.action.get("kind") == "workshops" and again:
            held.append(f"{p.rule}: a workshops level for {', '.join(again)} was started twice already; "
                        "the fort report doesn't show it built (Needs you)")
            continue
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
        fired_this_cycle.add(p.rule)
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
        _record_any_outcome(p.action, r, state, memory, now, brief=brief_timeout_now)
        note_refusal(memory, p, r, now, state.get("bridge_version"))
        note_no_effect(memory, p, ok, now)                 # (0.105.24)
        note_construct(p, r, state, memory, now)           # (0.105.30) wings, seals, soil floors, the hall
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
                and p.action.get("squad_id") is not None):
            # (0.104.140) what each squad was last sent after (the second wave's memory)
            if not isinstance(getattr(memory, "kill_sent", None), dict):
                memory.kill_sent = {}
            memory.kill_sent[str(p.action["squad_id"])] = [i for i in p.action["kill"] if isinstance(i, int)][:50]
        if p.action.get("type") == "squad_orders" and p.action.get("clear") and isinstance(
                getattr(memory, "kill_sent", None), dict):
            memory.kill_sent.pop(str(p.action.get("squad_id")), None)
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
            memory.polished_upto = _d(state.get("projects")).get("finished")   # again once a level is finished
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
        memory.last_fired[p.rule] = now
        if p.rule not in LOOP_EXEMPT:
            log = memory.action_log.setdefault(refusal_key(p), [])
            log.append(now)
            memory.action_log[refusal_key(p)] = [t for t in log if 0 <= now - t < TICKS_PER_YEAR][-200:]
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
        if a["type"] == "start_project" and a.get("kind") == "memorial":
            # recorded even when the result is unknown: better one memorial than two
            built = memory.culture.setdefault("memorials_built", [])
            if a.get("name") and a["name"] not in built:
                built.append(a["name"])
            if ok is not False:
                memory.last_memorial_tick = abs_tick(state)
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
            memory.gate_closed_by_ai = not memory.gate_closed_by_ai
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


def note_cycle(state: dict, memory: Memory, cfg: dict = PLANNER_CONFIG) -> list[str]:
    """Bookkeeping from a fresh report, BEFORE planning. Returns notes."""
    s = normalize(state)
    errors = s["_errors"]
    notes: list[str] = []
    now = abs_tick(state)
    today = game_day(state)

    if "dwarves" not in errors and isinstance(s.get("dwarves"), dict) and "idle_adults" in s["dwarves"]:
        update_idle(s, memory, cfg)
    h = _d(s.get("health"))
    if h and not h.get("error"):
        memory.patient_since = patient_waits(s, memory, now)     # (0.104.81) moved out of plan()
    if "dwarves" not in errors:
        crisis.update(s, memory, cfg, notes)                     # (0.104.137) crisis mode
    if "world" not in errors:
        note_world(s, memory)                                    # (0.105.0) grudges, export wishes
    if "others_on_map" not in errors:
        notes += note_lockdown(s, memory, cfg)                   # (0.105.3) B's sealed hatch: lone intruders, the cap
    if "locations" not in errors:
        note_locations(s, memory, cfg)                           # (0.105.26) moved out of plan()
    try:
        note_construct_cycle(s, memory, cfg)                     # (0.105.30) the hall's wait for blocks
    except Exception as e:  # noqa: BLE001
        notes.append(f"construction bookkeeping failed ({type(e).__name__}: {str(e)[:120]})")
    # (0.104.89) the strategist's raised and held rules run out
    if isinstance(getattr(memory, "steer", None), dict):
        for k in [k for k, v in memory.steer.items() if not (isinstance(v, dict) and isinstance(v.get("until"), int)
                                                              and now < v["until"])]:
            del memory.steer[k]
    # (0.104.81) one-off keys (a zone, a dwarf, an order) left in the loop
    # log: each key's ticks are kept a year, but the keys themselves grew
    log = getattr(memory, "action_log", None)
    if isinstance(log, dict):
        for k in [k for k, v in log.items() if not any(isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR
                                                        for t in (v or []))]:
            del log[k]
    # An older save of the same fort was loaded: forget "future" timestamps,
    # or every rule would wait until game time caught up.
    for rule, t in list(memory.last_fired.items()):
        if t > now:
            del memory.last_fired[rule]
    for k in list(memory.orders_by_day):
        if not k.isdigit() or int(k) > today:
            del memory.orders_by_day[k]

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

    if "moods" not in errors:
        current = {str(m.get("unit_id")) for m in _l(s["moods"].get("list")) if m.get("craft")}
        memory.moods_seen = {k: v for k, v in memory.moods_seen.items() if k in current}
        for k in current:
            memory.moods_seen.setdefault(k, now)

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
        if not s.get("civ_alert"):
            if memory.ai_alert_raised:
                # Our alert is off and we didn't lower it: the player did. Don't
                # re-raise for the threats they've seen; a NEW threat still counts.
                memory.alert_suppressed = list(ids)
            memory.ai_alert_raised = False

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
        for name, on in s["tools"].items():
            if on is True:
                if name not in memory.tools_seen_on:
                    memory.tools_seen_on.append(name)
                if name in memory.tools_enabled_by_ai and name not in memory.tools_confirmed_on:
                    memory.tools_confirmed_on.append(name)
            elif on is False and name in memory.tools_seen_on and name not in memory.tools_player_disabled:
                # It was running and now it's off: someone chose that. Respect it.
                memory.tools_player_disabled.append(name)
                notes.append(f"{name} was switched off; the AI will leave it off")
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
    pop = _d(s.get("dwarves")).get("total")
    if isinstance(pop, int) and pop > 0:
        pw = memory.pop_watch
        if pw.get("pop") != pop or not isinstance(pw.get("since"), int) or pw["since"] > now:
            memory.pop_watch = {"pop": pop, "since": now}
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
    return notes
