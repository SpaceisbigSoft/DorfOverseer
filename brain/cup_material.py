"""(0.105.94) Cups of wood when the stone for mugs is spoken for.

Live 23 Nov, B (the Monastery, 53% unhappy): 16 citizens upset at drinking
without a cup, the comfort rule's stone mugs held every cycle ("no
stone_mugs order: 11 stone the masons may use, 15 of them claimed by the AI's
open orders") while 325 logs lay in store. stone_short counted 11 usable
boulders against stone_low 10 (not short), but the open orders already held
them all. The cup rules (comfort, tavern) now take wooden cups whenever the
mugs couldn't be ordered for want of stone and there's wood.
"""

from __future__ import annotations

from digest import _d

CUP_WOOD_MIN = 20          # logs to spare for cups (as the rules' own "wood >= 20")


def cup_recipe(s: dict, cfg: dict, amount: int = 1) -> str:
    """'wooden_cups' when stone is short or the stone mugs would be held for
    stone (the order checker's free stone, open orders' claims counted) and
    there's wood; else 'stone_mugs'."""
    from planner_core_fort import stone_short
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    if wood < CUP_WOOD_MIN:
        return "stone_mugs"
    if stone_short(s, cfg["stone_low"]):
        return "wooden_cups"
    try:
        from order_check import order_feasible
        r = order_feasible("stone_mugs", s, {"type": "work_order", "recipe": "stone_mugs", "amount": amount}, cfg)
    except Exception:
        return "stone_mugs"
    if not r.get("ok", True) and r.get("missing") == "inputs":
        return "wooden_cups"
    return "stone_mugs"
