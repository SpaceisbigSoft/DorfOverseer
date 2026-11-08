"""planner_orders: the work orders kept moving (split out of planner_industry
in 0.105.25, 13c): order slots and the workshop an order goes to, jobs
left without an order, suspended jobs resumed, the AI's orders approved,
stuck orders cancelled (select() then holds the recipe: stuck_hold_days),
coffins on the bench. planner_industry re-exports every name here."""

from __future__ import annotations

from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_bench_coffins_rule", "STONE_CRAFTS", "order_shop", "_order_slots_rule", "_orphan_jobs_rule", "_unsuspend_rule", "_approve_rule", "_stuck_orders_rule"]


def _bench_coffins_rule(s: dict, memory, proposals: list) -> None:
    """(0.104.21) A tomb level waits for coffins and the AI's coffin order has
    made no job at a workshop for 3 days (Enxah: 29 coffins ordered, none
    started in two game months, 106 dead unburied): coffin jobs put straight
    on a mason's bench (a carpenter's while stone is short), 5 at a time."""
    if memory is None or not jobs_reported(s):
        return
    waiting = sum(int(_d(_d(p.get("furnish")).get("waiting")).get("Coffin") or 0)
                  for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict))
    if waiting <= 0:
        return
    now = abs_tick(s)
    idle = []
    for o in _l(s.get("orders")):
        if (isinstance(o, dict) and o.get("by_ai") and str(o.get("recipe") or "").endswith("_coffin")
                and not (_d(o.get("jobs")).get("n") or 0)):
            w = _d(memory.order_watch.get(str(o.get("id"))))
            if isinstance(w.get("since"), int) and now - w["since"] >= 3 * TICKS_PER_DAY:
                idle.append(o)
    if not idle:
        return
    material = "wood" if stone_short(s, 5) else "stone"
    action = {"type": "bench_jobs", "kind": "coffin", "count": min(5, waiting), "material": material}
    if material == "stone" and masons_jammed(s):
        action["make_room"] = True             # (0.104.32) lift autoslab's stuck engrave jobs
    proposals.append(Proposal("coffins", action,
                              f"a tomb level waits for {waiting} coffin(s) and the AI's coffin order has made no job "
                              f"in {(now - _d(memory.order_watch.get(str(idle[0].get('id')))).get('since', now)) // TICKS_PER_DAY} "
                              f"days: put {min(5, waiting)} straight on a {'carpenter' if material == 'wood' else 'mason'}'s bench", 3))


STONE_CRAFTS = ("crafts", "ring", "bracelet", "earring", "amulet", "figurine", "mug", "scepter", "crown", "goblet")


def order_shop(recipe) -> str | None:
    """(0.104.23) The workshop an AI order is made at, where it's sure: the
    table above, then stone furniture and blocks at the mason's."""
    r = str(recipe or "")
    shop = recipe_shop(r)
    if shop:
        return shop
    if r.startswith("stone_"):
        return "Craftsdwarfs" if any(r.endswith(k) or k in r for k in STONE_CRAFTS) else "Masons"
    return None


def _order_slots_rule(s: dict, proposals: list) -> None:
    """(0.104.23) A workshop whose order slots ("max general orders") are all
    held by jobs nobody is on, while the AI's orders for it get no job:
    five more slots (to 15 at most). Enxah's masons: autoslab's 5 engrave
    jobs waited 250 days for blank slabs and held every slot, so the AI's
    slab, coffin and block orders never reached the bench."""
    if not jobs_reported(s):
        return
    waiting = {}
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and o.get("active") and not (_d(o.get("jobs")).get("n") or 0):
            shop = order_shop(o.get("recipe"))
            if shop:
                waiting.setdefault(shop, []).append(str(o.get("recipe")))
    for w in _l(_d(s.get("order_desk")).get("workshops")):
        if not isinstance(w, dict) or not isinstance(w.get("job_list"), list):
            continue
        mx = int(w.get("max_orders") or 0)
        from_orders = [j for j in w["job_list"] if isinstance(j, dict) and j.get("order")]
        if (mx and mx < 15 and len(from_orders) >= mx and not any(j.get("worker") for j in from_orders)
                and waiting.get(str(w.get("type")))):
            proposals.append(Proposal("order_slots", {"type": "order_slots", "workshop_id": w.get("id"),
                                                      "max": min(15, mx + 5)},
                                      f"the {w.get('type')} workshop's {mx} order slots are all held by jobs nobody is "
                                      f"on ({', '.join(sorted({str(j.get('type')) for j in from_orders}))}) while the "
                                      f"AI's {', '.join(sorted(set(waiting[str(w.get('type'))]))[:3])} get none: "
                                      f"{min(15, mx + 5)} slots", 2))
            return


def _orphan_jobs_rule(s: dict, proposals: list) -> None:
    """(0.104.34) Jobs left on the benches by work orders that are gone (the
    AI cancels a stuck order, DF keeps its jobs, unworked for good: Enxah's
    three craftsdwarf's held 14 such jewellery and craft jobs while 21 dwarves
    badly wanted to craft): taken off."""
    n = int(_d(s.get("order_desk")).get("orphan_jobs") or 0)
    if n > 0:
        proposals.append(Proposal("orphan_jobs", {"type": "clear_orphan_jobs"},
                                  f"{n} job(s) wait on the workshops' benches for work orders that are gone: take "
                                  "them off, so the benches take new work", 3))


def _unsuspend_rule(s: dict, proposals: list) -> None:
    """(0.104.13) The AI's own orders whose jobs a workshop suspended: taken
    up again (the player's "resume"). An order's suspended job never moves by
    itself, so it was cancelled as stuck after 28 days and placed again, round
    and round (Enxah: the wooden bucket 31 times while patients waited for
    water). Never a construction or a player's job (the bridge checks)."""
    held = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
            and (_d(o.get("jobs")).get("suspended") or 0) > 0]
    if not held:
        return
    what = sorted({str(o.get("recipe") or o.get("job")) for o in held})
    proposals.append(Proposal("unsuspend", {"type": "unsuspend_orders"},
                              f"{len(held)} of the AI's work order(s) have a suspended job ({', '.join(what[:4])}): "
                              "resume them", 3))


def _approve_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.101.2) The AI's own orders the manager hasn't approved in
    `approve_after_days` (no working office yet: an office needs a chair, a
    chair needs an approved order) are approved by the AI itself."""
    if memory is None:
        return
    now = abs_tick(s)
    waiting = []
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and o.get("validated") is False:
            w = _d(memory.order_watch.get(str(o.get("id"))))
            if isinstance(w.get("since"), int) and now - w["since"] >= cfg["approve_after_days"] * TICKS_PER_DAY:
                waiting.append(o)
    # (0.101.4) no order in the fort has started at all (none active) after
    # `approve_after_days`+2 days: the manager has no office chair to hand them
    # out from. One chair is made straight at a workshop.
    mine = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")]
    if mine and not any(isinstance(o, dict) and o.get("active") for o in _l(s.get("orders"))):
        old = [o for o in mine if isinstance(_d(memory.order_watch.get(str(o.get("id")))).get("since"), int)
               and now - memory.order_watch[str(o.get("id"))]["since"] >= (cfg["approve_after_days"] + 2) * TICKS_PER_DAY]
        if old:
            proposals.append(Proposal("bootstrap_chair", {"type": "bootstrap_chair"},
                                      f"none of the fort's {len(mine)} AI work orders has started: the manager hands "
                                      "orders out only from an office with a chair, and the chair waits on an order. "
                                      "Make one chair straight at a workshop", 1))
    if waiting:
        # (0.104.71) say why as it is: Enxah's manager has an office with a chair
        # and is busy hauling, so "no working office" was wrong
        offices = [x for x in _l(_d(s.get("order_desk")).get("offices")) if isinstance(x, dict)]
        has_office = any(x.get("manager_owns") and _d(x.get("built")).get("Chair") for x in offices)
        job = _d(_d(s.get("order_desk")).get("manager")).get("job")
        why = (f"the manager is busy ({job})" if has_office and job else
               "the manager has an office but hasn't come to it" if has_office else
               "no working office yet: it needs a chair, which needs an approved order")
        proposals.append(Proposal("approve_orders", {"type": "approve_orders"},
                                  f"{len(waiting)} of the AI's work orders have waited "
                                  f"{cfg['approve_after_days']}+ days for the manager's approval ({why}): approve them", 2))


def _stuck_orders_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """The AI's own work orders that have stood still: copies of one order
    (0.54 piled up two dozen coke orders on one smelter) after 2 weeks, all
    but the one that moved last; a single one after 4 weeks. Cancelled, a few
    a cycle, and not placed again for 4 weeks (select holds it); one that gets
    stuck again after that is Needs you (_watchdog_notes)."""
    if memory is None:
        return
    if "orders" in _d(s.get("_errors")):
        return          # (0.104.81, 13c) no fresh order list: the watch is stale, cancel nothing
    now = abs_tick(s)
    groups: dict[str, list] = {}
    # (0.101.2) an order still waiting for the manager's approval isn't stuck
    unapproved = {str(o.get("id")) for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("validated") is False}
    # (0.101.4) nor is any order while none at all has started (no manager's
    # office: cancelling and placing them again only churns)
    orders = [o for o in _l(s.get("orders")) if isinstance(o, dict)]
    if any("validated" in o for o in orders) and not any(o.get("active") for o in orders):
        return
    for k, w in memory.order_watch.items():
        if k in unapproved:
            continue
        if (isinstance(w, dict) and w.get("by_ai") and isinstance(w.get("since"), int)
                and (w.get("left") or 0) > 0):
            groups.setdefault(str(w.get("what")), []).append((watch_since(w), k, w))
    out = []
    for what, lst in sorted(groups.items()):
        lst.sort()
        if len(lst) > 1:
            for since, k, w in lst[:-1]:
                days = (now - since) // TICKS_PER_DAY
                if days >= cfg["order_stuck_days"]:
                    out.append((0, k, what, f"{len(lst)} of the AI's {what} orders and this one hasn't moved in "
                                            f"{days} days: cancel it (one is kept)", False))
            lst = lst[-1:]
        since, k, w = lst[0]
        days = (now - since) // TICKS_PER_DAY
        # (0.105.22) the last slab or coffin for the waiting dead stays (B: 19
        # cancelled, each "not placed again for 28 days" while ghosts killed)
        if what in ("stone_slab", "stone_coffin") and (int(_d(s.get("dead")).get("ghosts") or 0) > 0
                                                       or int(_d(s.get("dead")).get("unburied") or 0) > 0):
            continue
        if days >= cfg["order_stuck_you_days"] and not _stuck_before(memory, what, now, cfg):
            out.append((1, k, what, f"the AI's {what} order ({w.get('left')} left) hasn't moved in {days} days: "
                                    f"cancel it (not placed again for {cfg['stuck_retry_days']} days)", True))
    taken = {p.action.get("order_id") for p in proposals if p.action.get("type") == "cancel_work_order"}
    for _, k, what, why, single in sorted(out)[:cfg["stuck_cancel_max"]]:
        try:
            oid = int(k)
        except ValueError:
            continue
        if oid in taken:                    # (another rule cancels it this cycle)
            continue
        action = {"type": "cancel_work_order", "order_id": oid}
        if single:
            action["stuck"] = what
        proposals.append(Proposal("stuck_order", action, why, 6))
