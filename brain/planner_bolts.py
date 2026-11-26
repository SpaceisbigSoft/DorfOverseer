"""(item2) Bolts for the crossbow squad: one open order at a time, sized to
the gap, and another material when one stalls or is held.

Why (fort A, the War-hold, 25 Nov 21:35-23:00, at war with the goblins): 10
crossbow soldiers with 0 of the 500 bolts wanted. The `arms` rule ordered 5
lots of wooden bolts each cycle (21:37, 22:20, 22:21, 22:22, 22:23): the gap
was 500 wanted less 25 a queued lot, and each order was capped at 5 lots, so
one order never closed it. `stuck_order` cancelled the orders that stood at
"2 left" (21:35, 21:54, 22:38), each recipe hold 28 then 56 days, and nothing
was ordered in another material meanwhile; the range shot the stock away
(125 -> 61 -> 19 -> 0 in an hour). Called from
planner_military_squads._ranged_squad_rule.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (GEAR_METALS, TICKS_PER_DAY, Proposal, _has_shop, abs_tick, order_job_state, stuck_days,
                          stuck_hold_days)

__all__ = ["BOLT_RECIPES", "bolt_orders", "bolts_held", "bolts_order"]

BOLT_RECIPES = ("metal_bolts", "wooden_bolts", "bone_bolts")


def bolt_orders(s: dict, memory, cfg: dict) -> tuple[int, dict]:
    """(item2) The open bolts orders: (lots left on those that move, {recipe:
    (days still, lots left, why)} of the AI's that have stood still
    `bolts_stall_days` or more). The player's orders always count as moving."""
    now = abs_tick(s)
    watch = _d(getattr(memory, "order_watch", None))
    moving, stalled = 0, {}
    for o in _l(s.get("orders")):
        if not isinstance(o, dict) or o.get("recipe") not in BOLT_RECIPES:
            continue
        left = max(0, int(o.get("amount_left") or 0))
        if o.get("repeats"):
            left = max(left, int(o.get("amount_total") or 0))
        if left <= 0:
            continue
        w = watch.get(str(o.get("id")))
        days = stuck_days(w, now) if isinstance(w, dict) and isinstance(w.get("since"), int) else 0
        if o.get("by_ai") and days >= int(cfg.get("bolts_stall_days", 7)):
            j = _d(o.get("jobs"))
            why = j.get("why") or order_job_state(o) or "nothing the report shows"
            prev = stalled.get(o["recipe"])
            stalled[o["recipe"]] = (max(days, prev[0]) if prev else days, left + (prev[1] if prev else 0), why)
        else:
            moving += left
    return moving, stalled


def bolts_held(recipe: str, action: dict, s: dict, memory, cfg: dict) -> str:
    """(item2) Why select() would hold a bolts order of this recipe now ("" if
    it wouldn't): cancelled as stuck lately (stuck_retry_days, unless what it
    lacked has come), or the order loop's check (inputs, workshop, labour)."""
    if memory is None:
        return ""
    now = abs_tick(s)
    p = Proposal("arms", action, "", 4, True)
    sc = _d(_d(getattr(memory, "stuck_cancelled", None)).get(recipe))
    if isinstance(sc.get("tick"), int) and 0 <= now - sc["tick"] < stuck_hold_days(sc, cfg) * TICKS_PER_DAY:
        try:
            from order_check import hold_lifted
            lifted = hold_lifted(p, s, memory, cfg)
        except Exception:  # noqa: BLE001
            lifted = False
        if not lifted:
            return f"cancelled as stuck {(now - sc['tick']) // TICKS_PER_DAY} day(s) ago"
    try:
        from order_check import order_gate
        return order_gate(p, s, memory, cfg, now) or ""
    except Exception:  # noqa: BLE001  (never stops the rule)
        return ""


def bolts_order(s: dict, g: dict, cfg: dict, proposals: list, memory, members: int, want: int, shop: bool,
                 wood: int) -> None:
    """Bolts for the crossbow squad. (item2) A, the War-hold (25 Nov): orders of
    5 lots each placed one a cycle until the queued lots covered the whole
    gap (22:20-22:23, four orders in four minutes: `bshort` took the 500
    wanted less 5 lots queued, so a 5-lot order never closed it); each stood
    at "2 left", was cancelled as stuck and its recipe held 28-56 days while
    the range shot the stock away. Now one open order at a time, sized to the
    gap (`bolts_order_max` lots); while it stands still `bolts_stall_days` the
    next material that may go (metal at the forge, wood at the bowyer's, bone
    at the craftsdwarf's) is ordered beside it, and a recipe select would hold
    (stuck lately, no input, no workshop or worker) gives way to the next."""
    moving, stalled = bolt_orders(s, memory, cfg)
    if moving > 0:
        return                                          # one order at a time: it is being worked
    gap = want - int(g.get("bolts") or 0)
    if gap <= 0:
        return
    jobs = min(int(cfg.get("bolts_order_max", 10)), max(1, -(-gap // 25)))
    bars = _d(g.get("bars"))
    metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= 1 + cfg["bolt_bars_keep"]), None)
    # (0.105.113 item11) the forge's bars go to the soldiers' arms first:
    # while a place waits for a weapon and the bowyer has wood, the bolts
    # (shot away at the range) are wooden. C: ~110 orders of iron bolts in
    # 12 hours, 19 melee places without a weapon and 3 squads unarmoured
    wood_first = shop and wood >= jobs + cfg.get("bolt_wood_keep", 10) and (
        int(g.get("weapon_gaps") or 0) > 0 or int(g.get("armed") or 0) < int(g.get("soldiers") or 0))
    bones = int(_d(s.get("needs")).get("bones") or 0)
    bone_keep = cfg.get("h4_bone_bolts_keep", 10)
    cands = []
    if metal and g.get("forges"):
        n = min(jobs, int(bars.get(metal) or 0) - cfg["bolt_bars_keep"])
        cands.append(("metal_bolts", n, {"material": f"INORGANIC:{metal}"}, f"in {metal.lower()}"))
    if shop and wood >= 1:
        cands.append(("wooden_bolts", min(jobs, wood), {}, "of wooden bolts"))
    if wood_first and len(cands) == 2:
        cands.reverse()
    if _has_shop(s["buildings"], "Craftsdwarfs") and bones >= 1 + bone_keep:
        # (r2h4) bone bolts at the craftsdwarf's: no forge bars, no bowyer's
        cands.append(("bone_bolts", min(jobs, bones - bone_keep), {}, "of bone bolts"))
    skipped = []
    for recipe, n, extra, words in cands:
        if n < 1:
            continue
        if recipe in stalled:
            days, left, why = stalled[recipe]
            skipped.append(f"the {recipe.replace('_', ' ')} order ({left} left) has stood {days} days ({why})")
            continue
        action = {"type": "work_order", "recipe": recipe, "amount": n, **extra}
        held = bolts_held(recipe, action, s, memory, cfg)
        if held:
            skipped.append(f"{recipe.replace('_', ' ')}: {held}")
            continue
        proposals.append(Proposal("arms", action,
                                  f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                  f"make {n} lot(s) {words}"
                                  + (f" ({'; '.join(skipped)})" if skipped else ""), 4, True))
        return
