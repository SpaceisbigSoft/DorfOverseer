"""planner_cycle: part of the planner (split out of planner.py in r7 d2; see planner.py).

note_cycle(): the bookkeeping from a fresh report before planning, and
note_gate_lever. planner.py re-exports every name."""

from __future__ import annotations

import crisis
import steer_guard
from planner_core import (PLANNER_CONFIG, TICKS_PER_DAY, TICKS_PER_YEAR, _holding_off, _lever_state, _traits,
                          _weapon_gaps, abs_tick, game_day, great_present, held_off_threats,
                          reachable_threats, steer_protected, update_idle)  # noqa: F401
from digest import (_d, _l, normalize)  # noqa: F401
from planner_construct import (note_construct_cycle)  # noqa: F401
from planner_food import (note_food)  # noqa: F401
from planner_gates import (note_gate_stuck_cycle)  # noqa: F401
from planner_hauling import (note_hauling)  # noqa: F401
from planner_holdfast import (note_holdfast_cycle)  # noqa: F401
from planner_hunt import (note_hunt_cycle)  # noqa: F401
from planner_society import (note_locations, patient_waits)  # noqa: F401
from planner_military import (note_lockdown, watched_gate_levers)  # noqa: F401
from planner_missions import (note_missions)  # noqa: F401
from planner_training import (note_never_draft)  # noqa: F401
from planner_outside import (note_outside)  # noqa: F401
from planner_growth import (note_pop_cap)  # noqa: F401
from planner_industry import (note_quarry)  # noqa: F401
from planner_recovery import (note_recovery)  # noqa: F401
from planner_visitors import (note_residency)  # noqa: F401
from planner_war_hold import (note_war_hold)  # noqa: F401
from planner_way_out import (note_way_out_cycle)  # noqa: F401
from planner_world import (note_world)  # noqa: F401


GATE_PULL_SEEN_DAYS = 3        # (0.105.36) a gate read shut this soon after the AI pulled its lever is the AI's
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

    from planner_switch import note_switches
    _step(note_switches, state, memory)                         # (F2a) the Switch's cycle count
    if "dwarves" not in errors and isinstance(s.get("dwarves"), dict) and "idle_adults" in s["dwarves"]:
        _step(update_idle, s, memory, cfg)
    h = _d(s.get("health"))
    if h and not h.get("error"):
        waits = _step(patient_waits, s, memory, now)            # (0.104.81) moved out of plan()
        if waits is not None:
            memory.patient_since = waits
    if "dwarves" not in errors:
        _step(crisis.update, s, memory, cfg, notes)             # (0.104.137) crisis mode
        _step(note_recovery, s, memory, cfg, notes)             # (0.105.46, I4) collapse recovery
        _step(note_outside, s, memory, cfg)                     # (r2 h9) waves seen, a caravan leaving, the drought
        _step(note_pop_cap, s, memory, cfg)                     # (r2 h9) the cap's hold (no flip-flop)
        _step(note_residency, s, memory)                        # (r2 h9) petitions to stay first seen
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
        _step(note_war_hold, s, memory, cfg)                    # (r1g5) the lifted long alarm's enemies forgotten
    if "locations" not in errors:
        _step(note_locations, s, memory, cfg)                   # (0.105.26) moved out of plan()
    if "entrances" not in errors:
        _step(note_gate_stuck_cycle, s, memory)                 # (0.105.32) a gate piece no longer split: forgotten
    if "way_out" not in errors:
        notes += _step(note_way_out_cycle, s, memory) or []     # (0.105.47, J16) sealed since, the cause last seen
    _step(note_construct_cycle, s, memory, cfg)                 # (0.105.30) the hall's wait for blocks
    if "military" not in errors:
        _step(note_gate_lever, s, memory)                       # (0.105.33) the AI gate read from its lever
    if "hunt" not in errors:
        notes += _step(note_hunt_cycle, s, memory, cfg) or []   # (0.105.45) hunts' outcomes learned once each
    _step(note_never_draft, s, memory, cfg)                     # (0.105.47) "never draft" forgotten in time
    _step(note_holdfast_cycle, s, memory, cfg)                  # (0.105.47, R2 item 7) kill orders' age, guards
    if "others_on_map" not in errors:
        from planner_defence_floor import note_defence_floor
        _step(note_defence_floor, s, memory, cfg)               # (0.105.54) the biggest threat seen: the defence floor
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
                  if (v.get("mode") == "raise" and (k in RAISE_FORBIDDEN or steer_guard.raise_refused(k)))
                  or (v.get("mode") == "hold" and (k in HOLD_PROTECTED or steer_protected(k)
                                                   or steer_guard.hold_refused(k)))]:
            del memory.steer[k]     # (r4 k1) and one steer_guard refuses now (an older save's hold of arms)
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
                # (r1g8) days under the alarm aren't "stuck": the dwarves are
                # held in the shelter, away from the workshops (E: the brew
                # orders cancelled 9 times during an 812-day alarm)
                w = memory.order_watch[k]
                last = w.get("seen")
                if s.get("civ_alert") is True and isinstance(last, int) and 0 < now - last:
                    w["paused"] = int(w.get("paused") or 0) + (now - last)
                w["seen"] = now
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
