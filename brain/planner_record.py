"""planner_record: part of the planner (split out of planner.py in r7 d2; see planner.py).

record(): what was actually done, remembered after acting. planner.py
re-exports every name."""

from __future__ import annotations

import masterplan
import planner_refusal_streak as refusal_streak
from planner_core import (LOOP_EXEMPT, LOOP_LIMITS, LOOP_LIMIT_DEFAULT, PLANNER_CONFIG, TICKS_PER_DAY,
                          TICKS_PER_YEAR, _lever_state, _record_any_outcome, abs_tick, brief_timeout,
                          cooldown_key, game_day, levels_done, note_labor_given, note_no_effect,
                          note_refusal, note_zone_full, refusal_key, shop_count, spare_sig)  # noqa: F401
from digest import (_d, _l)  # noqa: F401
from planner_guards import (guard_fail, guard_ok)  # noqa: F401
from planner_building import (is_character_level)  # noqa: F401
from planner_alarm import (note_alarm_change)  # noqa: F401
from planner_captives import (note_captives)  # noqa: F401
from planner_cleanup import (note_cleanup)  # noqa: F401
from planner_construct import (note_construct)  # noqa: F401
from planner_world import (note_contact_sent)  # noqa: F401
from planner_design import (note_design)  # noqa: F401
from planner_food import (note_food_level)  # noqa: F401
from planner_weather import (note_keep_in)  # noqa: F401
from planner_mood_help import (note_mood_help)  # noqa: F401
from order_check import (note_order_loop)  # noqa: F401
from planner_industry import (note_quarry_dug)  # noqa: F401
from planner_moods import (note_reserve_swap)  # noqa: F401
from planner_stuck import (note_stuck)  # noqa: F401
from planner_syndromes import (note_syndromes)  # noqa: F401
from planner_thirst import (note_thirst)  # noqa: F401
from planner_training import (note_training)  # noqa: F401


# (r7 d2) Names the tests patch on `planner` (planner.<name> = fake): looked up there
# at call time, so a patch on planner still reaches the moved code.
def _late(name):
    def call(*a, **k):
        import planner
        return getattr(planner, name)(*a, **k)
    call.__name__ = call.__qualname__ = name
    return call


note_gate_stuck = _late('note_gate_stuck')
note_holdfast = _late('note_holdfast')
note_way_out = _late('note_way_out')


def record(results: list[tuple[Proposal, dict]], state: dict, memory: Memory,
           cfg: dict = PLANNER_CONFIG) -> None:
    """Update memory after acting. ok=True: done. ok=False: refused, nothing
    happened. ok=None: unknown (e.g. the connection timed out mid-action), so
    the cooldown and counts start anyway, to be safe against doing it twice."""
    now = abs_tick(state)
    today = game_day(state)
    from planner_outside import note_caravan_try as _caravan_try   # (0.105.97) local: planner's names stay as they were
    crops_set_now = any(p.action.get("type") == "set_farm_crops" and isinstance(r, dict) and r.get("ok") is True
                        for p, r in results)
    failed: set[str] = set()

    def _hook(name, fn, *args, **kw):
        """(0.105.48, K6) Each of record()'s steps on its own: one raising no
        longer loses the rest (the alarm's and the gate's ownership, the
        cooldown, the action log). The failure is counted (memory.guard_fails)
        and said as a "rule record_<step> failed" note until it runs again."""
        try:
            return fn(*args, **kw)
        except Exception as e:  # noqa: BLE001
            failed.add(name)
            guard_fail(memory, "record_" + name, e, now)
            return None

    def _squads(p, r, ok, a):
        """The squads, the census, polish: whatever the answer."""
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
        if p.action.get("type") == "squad_trim" and ok is True:
            # (item8) who the trim sent home, when: a squad's worth a season, and the fill passes them over
            if not isinstance(getattr(memory, "trimmed", None), dict):
                memory.trimmed = {}
            for x in _l(_d(r).get("removed")):
                if isinstance(x, dict) and x.get("unit_id") is not None:
                    memory.trimmed[str(x["unit_id"])] = now
            for k in [k for k, t in memory.trimmed.items() if not isinstance(t, int) or now - t > 168 * TICKS_PER_DAY]:
                del memory.trimmed[k]
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

    def _booked(p, r, ok, a):
        """The cooldown, the loop log, the order count, the recent actions (False: refused)."""
        if ok is False:
            if p.rule == "build":
                # No safe site, the dry run disagreed, or the game refused it
                # (e.g. an older bridge): asking again every cycle won't help;
                # try again in a day.
                cooldown = cfg.get("build_cooldown_ticks", cfg["rule_cooldown_ticks"])
                memory.last_fired[p.rule] = now - cooldown + TICKS_PER_DAY
            elif p.rule == "found" and not brief_timeout_now:
                memory.last_fired[p.rule] = now          # the ground won't allow it: ask again in 3 days
            elif p.rule in ("burial_others",):     # (item4) its own cooldown begins at a refusal too
                # (item4) the rule's own cooldown begins at a refusal too (it
                # began only at a success: burial_others_cooldown_ticks never
                # held a refused mark_dump, B 24 Nov, 16 refusals)
                memory.last_fired[cooldown_key(p)] = now
            return False
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
        return True

    def _starts(p, r, ok, a):
        """What a start, a memorial or a farm setting books, done or unknown."""
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
        if a["type"] == "kitchen_drinks" and ok is True:       # (0.105.113 item10)
            memory.drink_cook_ban = a.get("ban") is True
        if a["type"] == "kitchen_cheap" and ok is True:        # (0.105.119 item37) short: the bridge let go
            memory.cheap_cook_ban = a.get("ban") is True and not _d(r).get("short")
        if a["type"] == "slaughter_one" and ok is True and a.get("mood_unit") is not None:
            memory.mood_slaughter[str(a["mood_unit"])] = now     # (0.105.30) one animal a mood
        if a["type"] == "start_project" and a.get("kind") == "memorial":
            # recorded even when the result is unknown: better one memorial than two
            built = memory.culture.setdefault("memorials_built", [])
            if a.get("name") and a["name"] not in built:
                built.append(a["name"])
            if ok is not False:
                memory.last_memorial_tick = abs_tick(state)

    def _asked(p, r, ok, a):
        """An alarm change or a switch-off with no reply: read off the next reports."""
        if ok is None and a["type"] == "civ_alert":
            # (0.105.33) the alarm changed but no reply came: the next report
            # says whether it went through (note_cycle takes ownership then)
            memory.alert_asked = {"on": bool(a.get("on")), "tick": now}
        if ok is None and a["type"] == "tool" and a.get("enabled") is False and a.get("name"):
            # (0.105.33) likewise the AI's own switch-off: not booked as the player's
            memory.tool_off_asked = dict(_d(memory.tool_off_asked), **{str(a["name"]): now})

    def _done(p, r, ok, a):
        """What a done action books."""
        if a["type"] == "cancel_project" and a.get("cavern_well"):
            # (0.104.12) not dug again: the shaft crept for years
            memory.cavern_well_failure = "the last cavern well's shaft was under half dug in a game year: given up"
            memory.cavern_well_failure_at = now          # (K48-K4) tried again well_retry_days later
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
            if a.get("visitors") is False and set(ids) & set(memory.locations_yours or []):
                # (0.105.51) shut again after a theft (planner_visitors): the AI's
                # again until you open it once more
                memory.locations_yours = [i for i in memory.locations_yours if i not in ids]
                memory.locations_yours_at = {k: t for k, t in _d(memory.locations_yours_at).items()
                                             if k not in {str(i) for i in ids}}
            # (0.105.26) when the AI acted (a report older than this reads stale), and the
            # mayor's rest (or the reopen's mark) the action carried: kept only now it went through
            memory.locations_acted = dict(memory.locations_acted or {}, **{str(i): now for i in ids})
            if isinstance(a.get("visitor_shut"), dict) and ids:
                memory.visitor_shut = dict(a["visitor_shut"])
        if (a["type"] == "answer_petition" and a.get("residency") and a.get("accept") and r.get("ok") is True
                and not a.get("ids")):
            # (0.105.9) the probe: is the applicant DF's resident within a few days?
            memory.residency["probe"] = {"id": a.get("id"), "unit": r.get("unit"), "tick": now}
        if a["type"] == "petition_orders" and r.get("ok") is True and not a.get("dry_run"):
            # (r10 p1) what the AI set (a later other reading is yours) and what waited then
            from planner_visitors import orders_set_by_ai
            orders_set_by_ai(state, memory, _d(a.get("orders")), now)
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

    def _gate_owned(p, r, ok, a):
        """The AI gate's ownership: a pull asked for."""
        if a["type"] == "pull_gate":
            # (0.105.33) a pull only queues a job (a dwarf may never reach the
            # lever): note_cycle reads the lever's state. Only a lever the
            # report gives no state for (an older bridge) is toggled here
            lever = next((g for g in _l(_d(state.get("military")).get("gates"))
                          if isinstance(g, dict) and g.get("id") == a.get("lever_id")), None)
            if not (isinstance(lever, dict) and _lever_state(lever) is not None):
                memory.gate_closed_by_ai = not memory.gate_closed_by_ai
            memory.gate_pull_asked = now          # (0.105.36) a shut read after this is the AI's

    def _done2(p, r, ok, a):
        """What a done action books (2)."""
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
                ra = getattr(memory, "rested_at", None)
                if isinstance(ra, dict) and "another squad trains" in str(getattr(p, "reason", "")):
                    ra[str(sid)] = now                      # (0.105.99) the rotation's rest month (E: put back at once)
            else:
                if sid not in memory.squads_trained:
                    memory.squads_trained.append(sid)
                if sid in memory.squads_rested:
                    memory.squads_rested.remove(sid)
                ra = getattr(memory, "rested_at", None)
                if isinstance(ra, dict):
                    ra.pop(str(sid), None)
                memory.last_train_tick = now

    def _alarm_owned(p, r, ok, a):
        """The alarm's ownership: raised or lowered by the AI."""
        if a["type"] == "civ_alert":
            if a["on"] and r.get("already_on"):
                pass  # someone else's alert: don't take ownership of it
            else:
                memory.ai_alert_raised = bool(a["on"])
                memory.quiet_cycles = 0
                if r.get("on") is None or bool(r.get("on")) == bool(a["on"]):
                    note_alarm_change(memory, now, bool(a["on"]), p.reason)      # (item4)

    def _tools(p, r, ok, a):
        """The tools the AI switched on or off."""
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

    for p, r in results:
        if not isinstance(r, dict):
            r = {"ok": None, "error": f"no answer read ({type(r).__name__})"}
        ok = r.get("ok")
        brief_timeout_now = bool(_hook("brief_timeout", brief_timeout, memory, p, r))   # (0.105.26) a search cut short
        _hook("note_labor_given", note_labor_given, memory, p, r, now)              # (v35 fix) LABOR_CAPS
        _hook("record_outcome", _record_any_outcome, p.action, r, state, memory, now, brief=brief_timeout_now)
        _hook("note_refusal", note_refusal, memory, p, r, now, state.get("bridge_version"), state=state)
        _hook("note_refusal_streak", refusal_streak.note, memory, p, r, state, now, cfg,
              brief=brief_timeout_now)                                               # (r5 p3) the same no in a row
        _hook("note_no_effect", note_no_effect, memory, p, ok, now)                 # (0.105.24)
        _hook("note_construct", note_construct, p, r, state, memory, now)           # (0.105.30) wings, seals, soil floors, the hall
        _hook("note_reserve_swap", note_reserve_swap, p, r, state, memory)          # (0.105.31 reserve fixes) a fibre swap that did nothing
        _hook("note_gate_stuck", note_gate_stuck, p, r, state, memory, now)         # (0.105.32) the unstick step tried, a way dug in
        _hook("note_way_out", note_way_out, p, r, state, memory, now)               # (0.105.47, J16) the way-out guard's try counted
        _hook("note_cleanup", note_cleanup, p, r, state, memory, now)               # (0.105.40) a cleanup's trial done, what it removed
        _hook("note_captives", note_captives, p, r, memory, now)                    # (item6) the pit's trial done, the prisoners sent
        _hook("note_order_loop", note_order_loop, p, r, state, memory, now, cfg)    # (0.105.46, I3) a stuck cancel's missing thing; approvals
        _hook("note_mood_help", note_mood_help, p, r, state, memory, now)           # (0.105.47, J1) free-items "nothing", a shop past the cap
        _hook("note_syndromes", note_syndromes, p, r, memory, now)                  # (0.105.41, item 11) the contaminant clean's trial done
        from planner_husbandry import note_pasture as _note_pasture     # (item39) local: no new global
        _hook("note_pasture", _note_pasture, p, r, state, memory, now)               # (item39) no grass for a pasture, in a row
        _hook("note_food_level", note_food_level, p, r, memory)                     # (fix41) one food storage level a kitchen or still
        _hook("note_training", note_training, p, r, memory, now)                    # (0.105.47) stress care's release: never drafted again
        _hook("note_stuck", note_stuck, p, r, memory, now)                          # (0.105.45) the stuck sweep's step done
        _hook("note_holdfast", note_holdfast, p, r, state, memory, now)             # (0.105.47, R2 item 7) a guard posted, a destroyer's gate tried
        _hook("note_contact_sent", note_contact_sent, p, r, state, memory)          # (0.105.48, K9) Make contact sent: named again next season
        if p.action.get("type") == "weather_burrow":
            _hook("note_keep_in", note_keep_in, memory, now, p.action, ok)          # (item4) evil weather: kept in by the burrow
        _hook("note_quarry_dug", note_quarry_dug, p, r, state, memory, now)         # (item7) the quarry marked, the stone then
        _hook("note_zone_full", note_zone_full, memory, p, r, now)                  # (item7) a zone with no free floor for furniture
        _hook("note_design", note_design, p, r, state, memory, now)                 # (D0) sites kept, a landmark's refusals and fallback
        _hook("note_thirst", note_thirst, p, r, memory, now)                        # (R1 g2) the thirst remedies' answers
        _hook("note_caravan_try", _caravan_try, p, r, memory, now)                 # (0.105.97) a stuck caravan's step and answer
        a = p.action if isinstance(p.action, dict) else {}
        _hook("squads", _squads, p, r, ok, a)
        _hook("booked", _booked, p, r, ok, a)      # the cooldown and the log, after the hooks as before
        if ok is False:
            continue
        _hook("starts", _starts, p, r, ok, a)
        _hook("asked", _asked, p, r, ok, a)
        if ok is not True:
            continue
        _hook("done", _done, p, r, ok, a)
        _hook("gate", _gate_owned, p, r, ok, a)
        _hook("done2", _done2, p, r, ok, a)
        _hook("alarm", _alarm_owned, p, r, ok, a)
        _hook("tools", _tools, p, r, ok, a)
    for k in list(memory.orders_by_day):
        if not str(k).isdigit() or int(k) < today - 4:
            del memory.orders_by_day[k]
    if results:
        for name in RECORD_STEPS:
            if name not in failed:
                guard_ok(memory, "record_" + name)


RECORD_STEPS = ("brief_timeout", "note_labor_given", "record_outcome", "note_refusal", "note_refusal_streak",
                "note_no_effect",
                "note_construct", "note_reserve_swap", "note_gate_stuck", "note_way_out", "note_cleanup",
                "note_captives", "note_order_loop", "note_mood_help", "note_syndromes", "note_food_level",
                "note_training", "note_stuck", "note_holdfast", "note_contact_sent", "note_keep_in", "note_quarry_dug",
                "note_zone_full", "note_design", "note_thirst", "note_caravan_try", "squads", "booked", "starts", "asked", "done", "gate",
                "done2", "alarm", "tools")


# (0.105.33) a year's ticks kept for each loop key: room for the highest loop
# limit (dismiss_alerts and answer_petition at 400 were never reached at 200)
ACTION_LOG_MAX = max(200, *LOOP_LIMITS.values(), LOOP_LIMIT_DEFAULT)
