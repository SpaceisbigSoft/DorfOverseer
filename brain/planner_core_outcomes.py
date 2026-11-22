"""planner_core_outcomes: part of planner_core (split out of planner_core.py in r7, which re-exports
every name): recording what each action did (_record_any_outcome) into memory."""

from __future__ import annotations
from digest import _d, _l
from planner_config import PLANNER_CONFIG
from planner_core_base import TICKS_PER_DAY


def _entrance_spot(state: dict, entrance_id) -> str | None:
    for e in _l(_d(state.get("entrances")).get("entrances")):
        if isinstance(e, dict) and e.get("id") == entrance_id:
            return f"{e.get('x')},{e.get('y')},{e.get('z')}"
    return None


def _record_any_outcome(a: dict, r: dict, state: dict, memory, now: int, brief: bool = False) -> None:
    """Bookkeeping that holds whether the action worked or was refused, so a
    refusal is never simply asked again every cycle. brief (0.105.26): a
    search the bridge cut short, to be tried again in a day or two (see
    TIMEOUT_TRIES): no failure booked for Needs you, the rule's wait short."""
    t = a.get("type")
    if brief:
        rule_ = {"make_pasture": "new_pasture", "farm_plots": "farms", "found_fort": "found"}.get(
            t, "extra_well" if t == "place_well" and a.get("extra") else "well" if t == "place_well" else None)
        if rule_:
            cd = PLANNER_CONFIG.get(f"{rule_}_cooldown_ticks", PLANNER_CONFIG["rule_cooldown_ticks"])
            memory.last_fired[rule_] = now - max(0, cd - TICKS_PER_DAY)       # again in a day
        if t == "farm_plots":
            memory.farm_failure_tick = now - max(0, PLANNER_CONFIG["farm_dig_retry_days"] - 1) * TICKS_PER_DAY
        if t in ("make_pasture", "place_well", "farm_plots", "found_fort"):
            return
    if t == "clear_gate" and r.get("ok") is False and isinstance(a.get("spot"), str):
        # nothing left, or the game says it's real: don't ask again
        reg = _d(_d(memory.atlas).get("registry"))
        for prefix in ("gate:", "doors:"):
            rec = reg.get(prefix + a["spot"])
            if isinstance(rec, dict):
                rec["status"] = "taken down" if "nothing" in str(r.get("error")) else "kept"
    # (0.105.36, D5) what the AI shelter holds, from each fill of it (made,
    # made again, or made again as the AI sounds the alarm): read by
    # planner_society's _shelter_supply_rule
    sh = r if t in ("setup_shelter", "refresh_shelter") else (
        r.get("shelter") if t == "civ_alert" and a.get("on") is True else None)
    if isinstance(sh, dict) and sh.get("ok") is not False and isinstance(sh.get("tiles"), int):
        memory.shelter_supply = {"tick": now, "tiles": sh["tiles"],
                                 **{k: sh[k] for k in ("drink_short", "no_water", "no_food", "drink_units",
                                                       "food_units", "well_tiles", "dry", "widened_for_drink",
                                                       "water_short")
                                    if sh.get(k) is not None}}
    # (0.105.52) the AI's alarm lowered for the thirsty (a shelter with no
    # drink even over the whole fort): not sounded again for half a day
    if t == "civ_alert" and a.get("on") is False and a.get("why") == "thirst" and r.get("ok") is not False:
        memory.thirst_alarm_off_until = now + TICKS_PER_DAY // 2
    # (0.105.36 fix) the alarm's burrow isn't the AI shelter (the player set
    # their own): its fill record forgotten (the AI no longer fills it)
    if t == "refresh_shelter" and r.get("ok") is False and "not the AI shelter" in str(r.get("error") or ""):
        memory.shelter_supply = {}
    if t == "setup_shelter":
        memory.shelter_attempts += 1          # refused or not: two tries, then again after a wait (0.105.35)
        memory.shelter_tick = now
        if r.get("ok") is True:
            # (0.105.36) one that worked isn't a refusal: two good set-ups over a
            # fort's life (the player removed one) read as "refused twice"
            memory.shelter_attempts = 0
    elif t == "scan_entrances":
        memory.rescan_entrances = False
    elif t == "expel_dwarf":
        memory.last_expel_tick = now             # refused or not: wait the full spell
    elif t == "census":
        if r.get("ok"):
            memory.census = {"tick": now, "units": _d(r.get("units")), "items": _d(r.get("items")),
                             "jobs": r.get("jobs")}
    elif t == "join_levels":
        # (0.104.108) a corridor dug: look again soon; every level seen and
        # nothing to join: wait a fortnight (new levels come slowly)
        memory.last_join_tick = now
        memory.join_wait_days = 2 if r.get("joined") or r.get("widened") or not r.get("wrapped") else 14
    elif t == "make_pasture":
        memory.last_fired["new_pasture"] = now   # refused or not: wait the full spell
        if r.get("ok") is True:
            memory.pasture_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            memory.pasture_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_well" and a.get("extra"):
        # (0.104.141) another well beside one standing: its failure never says
        # "no well can be placed" (the cavern well and Needs you hang on that)
        memory.last_fired["extra_well"] = now
        if r.get("ok") is True:
            memory.extra_well_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            # (r1 g3) a refusal for a full slot list says nothing of the water
            # (the cavern well now follows any other refusal)
            memory.extra_well_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_well" and a.get("filled"):
        # (r2 h2) the winter cistern: its refusal says nothing of an ordinary
        # well or a cavern well (their waits hang on those)
        if r.get("ok") is True:
            memory.filled_well_failure, memory.filled_well_failure_at = "", None
        elif r.get("ok") is False and not r.get("rejected"):
            memory.filled_well_failure = str(r.get("error") or "refused")[:300]
            memory.filled_well_failure_at = now
    elif t == "place_well":
        memory.last_fired["well"] = now          # refused or not: wait the full spell
        if a.get("cavern"):
            # (0.105.4 review) a cavern well tried with a gallery: the old refusal's one retry is spent
            if a.get("gallery"):
                memory.cavern_gallery_retried = True
            if r.get("ok") is False and not r.get("rejected"):
                memory.cavern_well_failure = str(r.get("error") or "refused")[:300]
                memory.cavern_well_failure_at = now       # (K48-K4) not for the fort's life
            elif r.get("ok") is True:
                memory.cavern_well_failure = ""
                memory.cavern_well_failure_at = None
        elif r.get("ok") is True:
            memory.well_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            memory.well_failure = str(r.get("error") or "refused")[:300]
    elif t == "furnish_project" and r.get("ok") is False and "well" in str(r.get("error") or ""):
        # (0.105.24) a well the game refused that the bridge tries again (a
        # floor dug beside it, or a day later) is not "no well can be placed"
        if not r.get("retry"):
            memory.well_failure = str(r.get("error"))[:300]
            # (0.105.36) the well_retry_days wait counts from this refusal (the
            # dig may have taken longer than the wait), not from the place_well
            memory.last_fired["well"] = now
    elif t == "farm_plots":
        memory.last_fired["farms"] = now         # refused or not: wait the full spell
        if r.get("ok") is True:
            memory.farm_failure = ""
        elif r.get("ok") is False:
            # nothing placed: not tried again for a while (see _farm_rule); and
            # when no farm level could be dug either, it's shown under Needs you
            memory.farm_failure_tick = now
            if a.get("dig"):
                memory.farm_failure = str(r.get("error") or "refused")[:300]
            else:
                # (0.100.1, review) only plots were tried (no farm level: before
                # the first staircase, or the surface farm): again in 3 days,
                # not the 4 weeks a level that couldn't be dug waits
                memory.farm_failure_tick = now - max(0, PLANNER_CONFIG["farm_dig_retry_days"] - 3) * TICKS_PER_DAY
    elif t == "found_fort":
        if r.get("ok") is True:
            memory.found_failure = memory.found_wide_failure = ""
        elif r.get("ok") is False and not r.get("rejected"):
            # (0.105.35) a refusal near the wagon is tried further out (wide); only
            # a wide refusal is Needs you
            if a.get("wide"):
                # (v35 nit) a search that ran out of time isn't "no spot further out"
                if not r.get("timed_out"):
                    memory.found_wide_failure = str(r.get("error") or "refused")[:300]
            else:
                memory.found_failure = str(r.get("error") or "refused")[:300]
    elif t == "place_traps":
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot and r.get("ok") is None:
            # no answer: they may be placed; not asked again for 2 weeks (never twice at once)
            memory.gate_failures["traps:" + spot] = "no answer from the game; looked at again later"
            memory.gate_failure_ticks["traps:" + spot] = now
        elif spot and r.get("ok") is False:
            memory.gate_failures["traps:" + spot] = str(r.get("error") or "refused")[:300]
            memory.gate_failure_ticks["traps:" + spot] = now
        elif spot:
            memory.gate_failures.pop("traps:" + spot, None)
            memory.gate_failure_ticks.pop("traps:" + spot, None)
    elif t == "build_gatehouse" and not a.get("dry_run"):
        # (0.105.23) built once at a spot: never again there (a second would
        # stand beside the first); a refusal waits gate_retry_ticks
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot and r.get("ok") is True:
            memory.gatehouses[spot] = {"tick": now, "bridge": r.get("bridge"), "dir": r.get("dir")}
            memory.gate_failures.pop("gatehouse:" + spot, None)
            memory.gate_failure_ticks.pop("gatehouse:" + spot, None)
        elif spot:
            err = str(r.get("error") or "no answer from the game")
            if r.get("wagon") and not err.startswith("the embark wagon"):
                err = "the embark wagon: " + err      # (0.105.51) asked again once the wagon is gone
            memory.gate_failures["gatehouse:" + spot] = err[:300]
            memory.gate_failure_ticks["gatehouse:" + spot] = now
    elif t == "link_lever" and not a.get("dry_run"):
        key = f"lever:{a.get('lever_id')}>{a.get('target_id')}"
        if r.get("ok") is False:
            memory.gate_failures[key] = str(r.get("error") or "refused")[:300]
            memory.gate_failure_ticks[key] = now
        else:
            memory.gate_failures.pop(key, None)
            memory.gate_failure_ticks.pop(key, None)
            memory.rescan_entrances = True        # the link shows in the next scan once it's made
    elif t in ("build_gate_doors", "fortify_entrance", "cut_entrance"):   # (0.105.0 cut_entrance)
        spot = _entrance_spot(state, a.get("entrance_id"))
        if not spot:
            return
        if t == "cut_entrance":
            # (0.105.0 review) the cut's refusal under its own key: the wall's
            # refusal (why the cut was tried) is kept, not overwritten
            if a.get("dry_run"):
                return
            if r.get("ok") is False:
                memory.gate_failures["cut:" + spot] = str(r.get("error") or "refused")[:400]
                memory.gate_failure_ticks["cut:" + spot] = now
                return
            memory.gate_failures.pop("cut:" + spot, None)
            memory.gate_failure_ticks.pop("cut:" + spot, None)
        if r.get("ok") is False:
            # refused: remembered with the game's reason (shown under Needs you)
            # and when, so it's tried again later
            memory.gate_failures[spot] = str(r.get("error") or "refused")[:400]
            memory.gate_failure_ticks[spot] = now
        else:
            memory.gate_failures.pop(spot, None)        # worked this time
            memory.gate_failure_ticks.pop(spot, None)
            if t == "build_gate_doors":
                if spot not in memory.gate_doors_requested:
                    memory.gate_doors_requested.append(spot)
            else:
                if r.get("water_gate"):
                    # deep water is the gate: nothing to build. Looked at again
                    # each season (water freezes, dries, rises)
                    memory.gates_fortified[spot] = f"water@{now}"
                else:
                    memory.gates_fortified[spot] = (r.get("style") or a.get("style") or "plain") + (
                        ", doors later" if r.get("doors_later") or r.get("support_walls") else "")
                    memory.gates_fortified_ticks[spot] = now
