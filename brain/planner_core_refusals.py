"""planner_core_refusals: part of planner_core (split out of planner_core.py in r7, which re-exports
every name): the back-offs: refusals, labor caps, timeouts, full zones, loop limits and no-effect
holds."""

from __future__ import annotations
import json
from digest import _d, _l
from planner_config import PLANNER_CONFIG
from planner_core_base import EMERGENCY, TICKS_PER_DAY, TICKS_PER_YEAR, watch_since


# One back-off for everything the game refuses: the same action refused
# again waits twice as long each time (1 day, 2, 4 ... up to 4 weeks), and a
# success clears it. Responses to an attack never wait.
REFUSAL_FIRST_DAYS = 1
REFUSAL_MAX_DAYS = 84                # (the overnight run: a spot that never fits was asked about every 28 days)
REFUSAL_IDLE_DAYS = 336              # (0.104.138) refused as nothing to do (every chair paired, all water restricted)
REFUSAL_KEYS = ("type", "kind", "recipe", "job", "entrance_id", "project_id", "name", "squad_id",
                "lever_id", "target_id", "tool", "unit_id",      # (0.103.12) unit_id: one dwarf's refusal isn't another's
                "zone_id", "order_id", "location_id",            # (0.104.81) nor one zone's, order's or location's
                "building_id",                                   # (0.104.138) nor one workshop's feeder another's
                "accept",                                        # (0.105.9) declining isn't agreeing
                "pile_id",                                       # (0.105.41, item 2) nor one pile's barrows or link another's
                # (0.105.48, K6) nor one target's refusal another target's: a site, a
                # mission's goal, an item, a landmark, a stone, a metal, a district, a
                # library, an entrance or lever by "id", a group of units (lists sorted)
                "id", "ids", "units", "site_id", "goal", "item_id", "landmark_id", "stone", "metal",
                "district", "library",
                # (0.105.48, K3) a release isn't the confine of the same rule:
                # calm_burrow / calm_burrow release were one key, so the confine's
                # loop hold and refusals held the letting-out for weeks
                "release", "on")


def is_release(a) -> bool:
    """(0.105.48, K3) An action that only lets go (a burrow emptied, the
    alarm lowered, a keep-in or a lock lifted): {"release": true} or
    {"on": false}. Never loop-held."""
    a = _d(a)
    return a.get("release") is True or a.get("on") is False


# (v35 fix) labour rules that add dwarves every cooldown while their need
# lasts: each gives at most its config key's dwarves in a game year
LABOR_CAPS = {"care_feed": "care_feed_labor_cap", "care_clean": "care_clean_labor_cap",
              "care_diagnose": "care_diagnose_labor_cap", "ghost_mason": "ghost_mason_labor_cap",
              "waterworks_pump_labor": "pump_labor_cap"}


def labor_given(memory, rule: str, now: int) -> int:
    """(v35 fix) Dwarves the AI gave this rule's labour in the last game year."""
    rows = _l(_d(getattr(memory, "labor_given", None)).get(rule))
    return sum(int(r[1]) for r in rows if isinstance(r, list) and len(r) == 2 and isinstance(r[0], int)
               and isinstance(r[1], int) and 0 <= now - r[0] < TICKS_PER_YEAR)


def note_labor_given(memory, p, r: dict, now: int) -> None:
    """(v35 fix) A LABOR_CAPS rule's labour given: booked (the dwarves named,
    else the count asked). (0.105.36) An unknown answer (ok None: a timeout
    that may have gone through) books the count asked, to be safe against
    passing the yearly cap, as the cooldown does."""
    ok = _d(r).get("ok")
    if p.rule not in LABOR_CAPS or _d(p.action).get("type") != "assign_labor" or ok is False:
        return
    names = _d(r).get("assigned") if ok is True else None
    n = len(names) if isinstance(names, list) else int(_d(p.action).get("count") or 0)
    if n <= 0:
        return
    if not isinstance(getattr(memory, "labor_given", None), dict):
        memory.labor_given = {}
    rows = [x for x in _l(memory.labor_given.get(p.rule)) if isinstance(x, list) and len(x) == 2
            and isinstance(x[0], int) and 0 <= now - x[0] < TICKS_PER_YEAR]
    memory.labor_given[p.rule] = rows + [[now, n]]


# (v35 fix) actions whose "id" names one entrance: one entrance's refusal (the
# cavern seal, an enemy near it) isn't another's
REFUSAL_ID_TYPES = ("open_entrance",)
# (v35 fix) rules whose proposals for different entrances each keep their own
# cooldown (and may act for several entrances in one cycle)
PER_ID_COOLDOWN = {"stranded"}


def _key_value(v):
    """(0.105.48, K6) A refusal key's value: a list of ids in a stable order."""
    if isinstance(v, (list, tuple)):
        try:
            return sorted(v)
        except TypeError:
            return [str(x) for x in v]
    return v


def refusal_key(p: Proposal) -> str:
    a = _d(p.action)
    # (0.105.48, K6) "id" is in REFUSAL_KEYS for every action now (was only REFUSAL_ID_TYPES')
    # (r11 n1 fixes) one office's swap refused isn't another's, nor the interim's swap-out a better holder's
    keys = REFUSAL_KEYS + (("office", "interim_out") if p.rule == "office_swap" else ())
    return p.rule + ":" + json.dumps({k: _key_value(a.get(k)) for k in keys if k in a},
                                     sort_keys=True, default=str)


def cooldown_key(p: Proposal) -> str:
    """(v35 fix) The key of p's cooldown in memory.last_fired: its rule, or for
    a PER_ID_COOLDOWN rule's action on one entrance, the rule and that id."""
    a = _d(getattr(p, "action", None))
    if p.rule in PER_ID_COOLDOWN and a.get("id") is not None:
        return f"{p.rule}:{a['id']}"
    if p.rule == "office_swap" and a.get("office"):      # (r11 n1) a season per office
        return f"office_swap:{a['office']}"
    return p.rule


# (0.105.36) actions whose rule paces its own tries after a refusal: no
# refusal back-off on top (the shelter's "tried again in 1 day(s)" stretched
# to weeks under a siege: SHELTER_RETRY_*_DAYS is its pace)
OWN_PACE = {"setup_shelter"}


def _refused_wait(memory: Memory, p: Proposal, now: int, bridge: str | None = None) -> int | None:
    """Days left before a refused action may be tried again, or None. A
    refusal booked under another bridge version is tried again at once: new
    code may do what the old couldn't (0.81: squads refused for want of a
    captain's post waited up to 84 days after the bridge learned to add one)."""
    if p.rule in EMERGENCY or p.action.get("type") in OWN_PACE:
        return None
    r = _d((memory.refusals or {}).get(refusal_key(p)))
    if bridge and r and r.get("v") != bridge:   # (refusals from before 0.81 carry no version: once more)
        return None
    until = r.get("until")
    if isinstance(until, int) and 0 <= now < until:
        return max(1, -(-(until - now) // TICKS_PER_DAY))
    return None


# (0.105.26) a search the bridge cut short (timed_out in its answer: no spot
# found in the time it had, not "there is none") is tried again in a day or
# two, with no back-off and no "could not be placed" in Needs you, this many
# times in a row; then it counts as a refusal (the cistern's always times out)
TIMEOUT_TRIES = 3


def timeout_streak(memory, key: str) -> int:
    """(0.105.26) How many searches in a row under this refusal key were cut
    short before this one."""
    return int(_d(_d(getattr(memory, "refusals", None)).get(key)).get("t") or 0)


def brief_timeout(memory, p: Proposal, r: dict) -> bool:
    """(0.105.26) A search cut short that is still to be tried again soon: not
    a lasting failure (see TIMEOUT_TRIES)."""
    return (r.get("ok") is False and bool(r.get("timed_out"))
            and timeout_streak(memory, refusal_key(p)) + 1 < TIMEOUT_TRIES)


# (item7) a zone with no free floor for a statue or other furniture: no
# place_in_zone there for ZONE_FULL_FIRST_DAYS, doubling each refusal in a
# row, at most ZONE_FULL_MAX_DAYS (B, 13 Nov: the tavern's zone 139 and the
# mayor's bedroom refused "no free floor in zone N" 33 times; the general
# back-off began again at a day with each new bridge version)
ZONE_FULL_FIRST_DAYS = 28
ZONE_FULL_MAX_DAYS = 336


def zone_full_days(memory, zone_id, now: int) -> int | None:
    """Days left before furniture is put into this zone again, or None."""
    rec = _d(_d(getattr(memory, "place_full", None)).get(str(zone_id)))
    until = rec.get("until")
    if isinstance(until, int) and 0 <= now < until and until - now <= ZONE_FULL_MAX_DAYS * TICKS_PER_DAY:
        return max(1, -(-(until - now) // TICKS_PER_DAY))
    return None


def note_zone_full(memory, p: Proposal, r: dict, now: int) -> None:
    """A place_in_zone answered: "no free floor" books the zone full (longer
    each time in a row); a placement there clears it."""
    a = _d(p.action)
    if a.get("type") != "place_in_zone" or a.get("zone_id") is None or a.get("dry_run"):
        return
    if not isinstance(getattr(memory, "place_full", None), dict):
        memory.place_full = {}
    k = str(a["zone_id"])
    if r.get("ok") is True:
        memory.place_full.pop(k, None)
        return
    if r.get("ok") is False and "no free floor" in str(r.get("error") or ""):
        n = int(_d(memory.place_full.get(k)).get("n") or 0) + 1
        days = min(ZONE_FULL_MAX_DAYS, ZONE_FULL_FIRST_DAYS * 2 ** (n - 1))
        memory.place_full[k] = {"n": n, "until": now + days * TICKS_PER_DAY, "at": now,
                                "what": str(a.get("what") or "")}
    for z in [z for z, v in memory.place_full.items()
              if not isinstance(v, dict) or not isinstance(v.get("until"), int)
              or not -ZONE_FULL_MAX_DAYS * TICKS_PER_DAY <= now - v["until"] < 2 * ZONE_FULL_MAX_DAYS * TICKS_PER_DAY]:
        memory.place_full.pop(z, None)


def note_refusal(memory: Memory, p: Proposal, r: dict, now: int, bridge: str | None = None) -> None:
    """Book a refusal (or clear the count after a success), with the bridge
    version that refused it."""
    if not isinstance(memory.refusals, dict):
        memory.refusals = {}
    key = refusal_key(p)
    if r.get("ok") is True and p.action.get("type") == "polish" and r.get("designated") == 0:
        r = {"ok": False, "error": r.get("note") or "nothing to smooth or engrave"}   # nothing done: back off
    if r.get("ok") is True:
        # (0.104.138) a success halves the count rather than wiping it: one
        # success among many refusals began the back-off again at a day
        old = _d(memory.refusals.get(key))
        if int(old.get("n") or 0) >= 3:
            memory.refusals[key] = {k: v for k, v in dict(old, n=int(old["n"]) // 2, until=now).items()
                                    if k not in ("why", "t")}
        else:
            memory.refusals.pop(key, None)
        return
    if r.get("ok") is not False or r.get("halted") or p.rule in EMERGENCY or p.action.get("type") in OWN_PACE:
        return                     # unknown, or stopped by the in-game halt: not the game saying no
    if r.get("waiting"):           # work under way (trees being felled): look again in 2 days, no back-off
        memory.refusals[key] = {"n": 0, "until": now + 2 * TICKS_PER_DAY, "at": now,
                                "why": str(r.get("error") or "")[:120]}
        if bridge:
            memory.refusals[key]["v"] = str(bridge)
        return
    old = _d(memory.refusals.get(key))
    if r.get("timed_out"):
        # (0.105.26) a search cut short: again in a day or two, no back-off,
        # TIMEOUT_TRIES times in a row (one timed-out well search began an
        # 84-day back-off and said "no well could be placed")
        t = int(old.get("t") or 0) + 1
        if t < TIMEOUT_TRIES:
            memory.refusals[key] = {"n": int(old.get("n") or 0), "t": t, "at": now,
                                    "until": now + min(2, t) * TICKS_PER_DAY,
                                    "why": ("search cut short: " + str(r.get("error") or ""))[:120]}
            if bridge:
                memory.refusals[key]["v"] = str(bridge)
            return
    n = int(old.get("n") or 0) + 1
    days = min(REFUSAL_MAX_DAYS, REFUSAL_FIRST_DAYS * 2 ** (n - 1))
    if r.get("nothing_to_do"):
        days = REFUSAL_IDLE_DAYS   # (0.104.138) the goal is met: a year, not a loop
    if p.action.get("type") == "squad_release" and "longs to fight or train" in str(r.get("error") or ""):
        days = max(days, 56)       # (0.104.34) a need that lasts: Enxah asked 368 times, 10 dwarves, all refused
    memory.refusals[key] = {"n": n, "until": now + days * TICKS_PER_DAY, "at": now,
                            "why": str(r.get("error") or "")[:120]}
    if r.get("timed_out"):
        memory.refusals[key]["t"] = int(old.get("t") or 0) + 1   # still cut short: the streak goes on
    if bridge:
        memory.refusals[key]["v"] = str(bridge)
    # forget refusals nothing has asked about for two months
    # (0.104.38) but not one still waiting out its back-off: a 56-84 day wait
    # was forgotten at 60 and began again at 1 day (feeder piles refused 120
    # times overnight, squad releases 78)
    for k in [k for k, v in memory.refusals.items()
              if not isinstance(v, dict) or not isinstance(v.get("at"), int)
              or (now - v["at"] > 60 * TICKS_PER_DAY
                  and not (isinstance(v.get("until"), int) and now < v["until"] + 30 * TICKS_PER_DAY))]:
        memory.refusals.pop(k, None)


# the same action (refusal_key) this many times in a game year looks like a
# loop (the soak run: 125 soap-maker levels, 184 meal orders): held a while.
# Rules that repeat by design aren't counted.
LOOP_LIMITS = {"start_project": 12, "place_surface": 12, "place_well": 12, "make_pasture": 20,
               "deep_depot": 12,                                # (0.105.23) the underground depot's road
               "dismiss_alerts": 400, "answer_petition": 400}   # (0.105.9) residency batches by the hundred
LOOP_LIMITS["break_fights"] = 400   # (0.105.47) now on every tantrum report too (harmless when nothing is wrong)
LOOP_LIMIT_DEFAULT = 80
LOOP_EXEMPT = {"entrances", "needs_trinkets", "trinket_orders", "excess_shops", "cistern", "call_trader", "open_trade",
               "trade_deal", "close_trade", "trade", "train", "water", "project"}


def _loop_count(memory: Memory, p: Proposal, now: int) -> int | None:
    """How often this action was done in the last game year, when that is
    over its limit and it was done again recently (else None)."""
    if p.rule in LOOP_EXEMPT or (p.rule in EMERGENCY and not getattr(p, "guard", False)):
        return None
    if is_release(p.action):          # (0.105.48, K3) letting go is never a loop to hold
        return None
    log = (getattr(memory, "action_log", None) or {}).get(refusal_key(p)) or []
    recent = [t for t in log if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR]
    limit = LOOP_LIMITS.get(str(p.action.get("type")), LOOP_LIMIT_DEFAULT)
    if len(recent) >= limit and recent and now - max(recent) < PLANNER_CONFIG["loop_hold_days"] * TICKS_PER_DAY:
        return len(recent)
    return None


# (0.105.24) Rules whose action can succeed without changing what asked for
# it: a crossbow made that never reaches the squad, a quiver handed out that
# the game takes back. Done no_effect_max times in a row for the very same
# reason (the same counts in its words), the rule waits no_effect_hold_days,
# then tries once more. C (2-5 Nov) ordered a crossbow every week for 35 game
# years, "4 crossbow soldiers and 3 with a crossbow" each time (962 orders);
# F gave the same one quiver 171 times ("1 without a quiver and 1 free").
NO_EFFECT_RULES = {"arms", "quivers"}
NO_EFFECT_WHY = {"arms": "the crossbows made don't reach the crossbow squad (a hunter may take them, or the "
                         "uniform asks for another kind): look in the game",
                 "quivers": "the quiver handed out doesn't stay with the soldier (the game takes it back): "
                            "look in the game"}


def note_no_effect(memory: Memory, p: Proposal, ok, now: int) -> None:
    """(0.105.24) Count a done action of a NO_EFFECT_RULES rule: again for the
    same reason, or a new count."""
    if p.rule not in NO_EFFECT_RULES or ok is not True:
        return
    if not isinstance(getattr(memory, "no_effect", None), dict):
        memory.no_effect = {}
    k = refusal_key(p)
    old = _d(memory.no_effect.get(k))
    n = int(old.get("n") or 0) + 1 if old.get("reason") == p.reason else 1
    memory.no_effect[k] = {"reason": p.reason, "n": n, "tick": now}
    if len(memory.no_effect) > 40:
        for kk in sorted(memory.no_effect, key=lambda x: int(_d(memory.no_effect[x]).get("tick") or 0))[:-40]:
            del memory.no_effect[kk]


def no_effect_wait(memory: Memory, p: Proposal, now: int, cfg: dict = PLANNER_CONFIG) -> int | None:
    """(0.105.24) Days left to wait when this action was done no_effect_max
    times in a row for this same reason (else None)."""
    if p.rule not in NO_EFFECT_RULES:
        return None
    r = _d(_d(getattr(memory, "no_effect", None)).get(refusal_key(p)))
    most = cfg.get("no_effect_max", PLANNER_CONFIG["no_effect_max"])
    if r.get("reason") != p.reason or int(r.get("n") or 0) < most or not isinstance(r.get("tick"), int):
        return None
    left = r["tick"] + cfg.get("no_effect_hold_days", PLANNER_CONFIG["no_effect_hold_days"]) * TICKS_PER_DAY - now
    return max(1, -(-left // TICKS_PER_DAY)) if 0 < left else None


def _stalled_days(memory: Memory, recipe: str, now: int) -> int | None:
    """Days the AI's longest-waiting order of this recipe has stood still (None: no
    unfinished AI order of it). More copies of an order that doesn't move only
    pile up (0.75 overnight prep: drink orders were placed and cancelled as stuck
    in turn, all evening)."""
    best = None
    for w in (getattr(memory, "order_watch", None) or {}).values():
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what")) == recipe
                and isinstance(w.get("since"), int) and (w.get("left") or 0) > 0):
            days = max(0, (now - watch_since(w)) // TICKS_PER_DAY)
            best = days if best is None else max(best, days)
    return best
