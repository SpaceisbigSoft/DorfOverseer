"""planner_select: part of the planner (split out of planner.py in r7 d2; see planner.py).

select(): the safety limits on the proposals, and the one-order-per-squad
helpers it uses. planner.py re-exports every name."""

from __future__ import annotations

import crisis
import planner_refusal_streak as refusal_streak
import steer_guard
from planner_core import (COOLDOWN_KEYS, EMERGENCY, LABOR_CAPS, MULTI_PER_CYCLE, NO_COOLDOWN, NO_EFFECT_WHY,
                          ONE_A_CYCLE, ORDER_HOLD_EXEMPT, PLANNER_CONFIG, Proposal, STUCK_HOLD_EXEMPT,
                          TICKS_PER_DAY, _has_shop, _loop_count, _refused_wait, _stalled_days, abs_tick,
                          can_fight, cooldown_key, game_day, labor_given, limit_exempt, no_effect_wait,
                          queued, recipe_shop, refusal_key, shop_count, steer_of, stuck_hold_days,
                          supply_order_kept, zone_full_days)  # noqa: F401
from digest import (_d, _l, normalize)  # noqa: F401
from planner_threats import (alarm_held)  # noqa: F401
from order_check import (approve_on_place, hold_lifted)  # noqa: F401
from planner_alarm import (govern_alarm)  # noqa: F401
from planner_guards import (guard_fail, guard_ok)  # noqa: F401
from planner_building import (stuck_fallback)  # noqa: F401


# (r7 d2) Names the tests patch on `planner` (planner.<name> = fake): looked up there
# at call time, so a patch on planner still reaches the moved code.
def _late(name):
    def call(*a, **k):
        import planner
        return getattr(planner, name)(*a, **k)
    call.__name__ = call.__qualname__ = name
    return call


mood_blocked = _late('mood_blocked')
order_gate = _late('order_gate')
reserve_room = _late('reserve_room')


SHOPS_RETRY_DAYS = 56          # (0.105.35) a workshops level started twice and not seen built: once more after this
SHOPS_RETRY_MAX = 3            # (v35 fix) and so at most this many times


# (0.105.48 K1b, audit A6 #5) One order per squad per cycle. About ten rules
# each took "the first free squad" (berserk, thieves, interrupters, the
# vampire...) and select() let them all through: squad 185 got four kill
# orders in one cycle, each replacing the last (lua orders() drops the AI's
# earlier order), so it ended on the vampire and nobody on the berserk dwarf.
# The squads an action gives orders to, by the key that names them:
SQUAD_ORDER_KEYS = {"squad_orders": "squad_id", "squad_station": "squad_id", "hospital_guard": "squad_id",
                    "hunt_send": "squad_ids", "hunt_recall": "squad_ids", "shelter_squads": "squads",
                    "archer_post": "squads", "guard_gate": "squads"}
# a party sized as a whole: never trimmed, held whole when one of it is taken
SQUAD_WHOLE = {"hunt_send"}


def ordered_squads(a: dict) -> list:
    """The squad ids action `a` gives orders to (none for any other action).
    (F2c) read off the general actuator table (brain/actuator_claims.py)."""
    import actuator_claims
    return actuator_claims.ordered_squads(a)


def _is_kill(a: dict) -> bool:
    return a.get("type") == "squad_orders" and not a.get("clear") and isinstance(a.get("kill"), list)


def squad_claim(p: Proposal, claimed: dict) -> str | None:
    """(0.105.48 K1b) p against the squads already given an order this cycle
    (`claimed`: squad id -> the allowed proposal; the proposals come in
    priority order, so the first one wins). A kill order on a squad already
    sent to kill this cycle adds its targets to that one order; a squad
    list loses the squads taken; anything else on a taken squad waits for the
    next cycle. Returns why p is held, or None (p goes, maybe trimmed)."""
    ids = ordered_squads(p.action)
    taken = [i for i in ids if i in claimed]
    if not taken:
        return None
    win = claimed[taken[0]]
    if len(ids) == 1 and _is_kill(p.action) and _is_kill(win.action):
        old = [i for i in win.action["kill"]]
        add = [i for i in p.action["kill"] if i not in old]
        if add:
            win.action = dict(win.action, kill=(old + add)[:50])
            win.reason = f"{win.reason}; and {p.rule}'s target(s) too"
        return (f"{p.rule}: squad {taken[0]} already has an order this cycle ({win.rule}): "
                f"its target(s) were added to that order")
    key = SQUAD_ORDER_KEYS[p.action["type"]]
    if isinstance(p.action.get(key), list) and p.action["type"] not in SQUAD_WHOLE:
        rest = [i for i in p.action[key] if i not in claimed]
        if rest:
            p.action = dict(p.action, **{key: rest})
            return None
    return (f"{p.rule}: squad {taken[0]} already has an order this cycle ({win.rule}, higher priority); "
            "this one waits for the next cycle")


def free_squad_for(p: Proposal, claimed: dict, state: dict, cfg: dict, proposed: set, memory=None):
    """(0.105.48, K16) The rules each take the first able squad, so a second
    kill order at a squad another order took this cycle waited (or was
    folded into that order) while other squads sat free. A kill order on one
    squad already taken goes to the first squad that can fight and is free:
    no order of the AI's (or only its shelter), not on the player's orders,
    not taken this cycle, and named by no other proposal (a reserve the
    matchup kept home is free). None: none is."""
    a = p.action if isinstance(p.action, dict) else {}
    if not _is_kill(a) or a.get("squad_id") not in claimed:
        return None
    # (0.105.48 merge) the matchup sized a fight this cycle: the squads it kept
    # home stay home (the second order folds into the first instead)
    if memory is not None and getattr(memory, "matchup_judged", None) == abs_tick(state):
        return None
    for q in _l(_d(state.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("id") is None or q["id"] in claimed or q["id"] in proposed:
            continue
        if q.get("ai_orders") and not q.get("sheltering"):
            continue
        if int(q.get("orders") or 0) > int(q.get("ai_orders") or 0):
            continue
        if can_fight(q, cfg):
            return q
    return None


def select(proposals: list[Proposal], state: dict, memory: Memory,
           cfg: dict = PLANNER_CONFIG) -> tuple[list[Proposal], list[str]]:
    """Apply the limits. Returns (allowed, held back with reasons)."""
    now = abs_tick(state)
    orders_today = memory.orders_by_day.get(str(game_day(state)), 0)
    allowed, held = [], []
    fired_this_cycle: set[str] = set()
    squads_claimed: dict = {}            # (0.105.48 K1b) one order per squad per cycle
    proposed_sq = {i for q_ in proposals for i in ordered_squads(getattr(q_, "action", None))}
    failed_ = False
    # (F2c) the actuators' owners across cycles, and this cycle's users (brain/actuator_claims.py)
    import actuator_claims as ac_
    try:
        claims = ac_.claims_open(memory, cfg)
        outranked = ac_.claims_outranked(proposals, claims, cfg)
    except Exception as e:  # noqa: BLE001  no claims this cycle (the per-cycle squad rule still holds)
        claims, outranked = {"n": 0, "own": {}}, {}
        failed_ = True
        guard_fail(memory, "select", e, now)
    used_act: dict = {}
    # (0.104.89) the strategist's word: a raised rule goes first and skips its
    # cooldown; a held one waits (never a survival or safety rule)

    def _steer(p):
        try:
            st = steer_of(memory, p.rule, now)
            # (r4 k1, A7 B1/B2) judged by what the step is: a hold waits only
            # an expansion step (or build's ladder), a raise never speeds a
            # kill/squad order, gate, lever, trade, butcher, conviction, lure,
            # kill zone, hunt or an opened seal, whatever the rule's name
            if st and st.get("mode") == "hold" and not steer_guard.hold_applies(p):
                return None
            if st and st.get("mode") == "raise" and not steer_guard.raise_applies(p):
                return None
            return st
        except Exception:  # noqa: BLE001  (0.105.48, K6) an odd steer is no steer
            return None
    # (0.105.26) a waiting strange mood's materials: no other rule's work order
    # uses them up (bags, quivers, shoes, jewellery, crafts and cloth re-ordered
    # what a mood had just cancelled)
    try:
        mood_recipes, mood_mats = mood_blocked(state)
    except Exception as e:  # noqa: BLE001  (0.105.48, K6) nothing held for a mood this cycle
        mood_recipes, mood_mats = {}, {}
        failed_ = True
        guard_fail(memory, "select", e, now)
    # (0.105.31) and the mood reserves: no other rule's order takes the last few
    # (reserve fixes: held at or under the line, else capped at what lies over
    # it; the reserve rule tops a reserve up at the line, so nothing waits for
    # good while it can be made; a noble's mandate is never held by it)
    try:
        reserve_recipes = reserve_room(state, cfg)
    except Exception as e:  # noqa: BLE001  (0.105.48, K6) no reserve held this cycle
        reserve_recipes = {}
        failed_ = True
        guard_fail(memory, "select", e, now)
    for p in sorted(proposals, key=lambda p: p.priority - (2 if (_steer(p) or {}).get("mode") == "raise" else 0)):
        try:
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
            # (0.105.46, I3) what was missing at the stuck cancel has come (bars
            # arrived): the recipe's hold gives way (brain/order_check.py)
            if p.action.get("type") == "work_order" and isinstance(sc.get("tick"), int) and hold_lifted(p, state, memory, cfg):
                sc = {}
            # (r1g8) drink and meals are never held back by an old stuck cancel
            # while they are short or the alarm is up
            if p.action.get("type") == "work_order" and sc and supply_order_kept(state, p.action.get("recipe"), cfg):
                sc = {}
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
            # (0.105.46, I3) inputs, fuel, a free workshop and a worker before any
            # order; none again after a stuck cancel until what it lacked changes
            og = order_gate(p, state, memory, cfg, now, allowed)
            if og:
                held.append(og)
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
                rec_ = _d(memory.refusals.get(refusal_key(p)))
                n = rec_.get("n")
                if rec_.get("w"):         # (item4) the same answer to wait, again: a longer wait each time
                    held.append(f"{p.rule}: waiting on the game, the same answer {rec_['w']} time(s) in a row "
                                f"({str(rec_.get('why') or '')[:80]}); asks again in {wait} day(s)")
                    continue
                held.append(f"{p.rule}: the game refused it {n} time(s) in a row; tries again in {wait} day(s)" if n
                            else f"{p.rule}: waiting on the game (its last answer was to wait); asks again in "
                                 f"{wait} day(s)")      # (0.97: it said "refused 0 time(s)")
                continue
            # (r5 p3) the same no for the same reason N times in a row: a longer
            # wait, kept a year, ended by a change in what it depends on
            rs = refusal_streak.wait(memory, p, state, now, cfg)
            if rs is not None:
                held.append(refusal_streak.held_line(p, *rs))
                continue
            alt = free_squad_for(p, squads_claimed, state, cfg, proposed_sq, memory)
            if alt is not None:
                taken_ = p.action["squad_id"]
                p.action = dict(p.action, squad_id=alt["id"])
                p.reason = (f"{p.reason} ({alt.get('name') or 'squad ' + str(alt['id'])} goes: squad {taken_} "
                            f"has another order this cycle)")
            # (0.105.52) the AI's alarm let down for the thirsty: not raised again
            # for half a day (the shelter held no drink even over the whole fort)
            if (isinstance(p.action, dict) and p.action.get("type") == "civ_alert" and p.action.get("on") is True
                    and now < int(getattr(memory, "thirst_alarm_off_until", 0) or 0)):
                held.append(f"{p.rule}: the alarm was let down for the thirsty (the shelter has no drink): "
                            "not sounded again before they've drunk")
                continue
            why_cl = ac_.actuator_claim(p, claims, used_act, outranked, cfg)
            if why_cl:
                held.append(why_cl)
                continue
            why_sq = squad_claim(p, squads_claimed)
            if why_sq:
                held.append(why_sq)
                continue
            # (0.104.137) in a crisis, recovery gets extra action slots
            limit = cfg["max_actions_per_cycle"]
            if _d(getattr(memory, "crisis", None)).get("why") and crisis.is_recovery(p, cfg):   # (0.105.48, K5) cfg: the table switch
                limit += cfg["crisis_extra_actions"]
            if (not limit_exempt(p.rule)          # (0.105.48, K6) and every EMERGENCY rule, however late added
                    and len([a for a in allowed if not limit_exempt(a.rule)]) >= limit):
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
            if p.action.get("type") == "work_order" and approve_on_place(memory, cfg, now):
                # (0.105.46, I3) the manager doesn't get to the AI's orders: approved as placed
                p.action = dict(p.action, approve=True)
            allowed.append(p)
            for i_ in ordered_squads(p.action):
                squads_claimed.setdefault(i_, p)
            ac_.claims_commit(p, claims, used_act, now, cfg)
            fired_this_cycle.add(cooldown_key(p))
            if p.is_order:
                orders_today += 1
        except Exception as e:  # noqa: BLE001  (0.105.48, K6) one odd proposal never stops the limits
            failed_ = True
            guard_fail(memory, "select", e, now)
            if limit_exempt(p.rule) and p not in allowed:
                # a response to danger goes as it is; anything else waits a cycle
                allowed.append(p)
                fired_this_cycle.add(p.rule)
            elif p not in allowed:
                held.append(f"{p.rule}: the limits' check failed on it ({type(e).__name__}: {str(e)[:80]}); "
                            "it waits a cycle")
    try:
        refusal_streak.said(memory)      # (r5 p3) the waits begun were in this cycle's notes
    except Exception:  # noqa: BLE001
        pass
    if not failed_:
        guard_ok(memory, "select")
    return allowed, held
