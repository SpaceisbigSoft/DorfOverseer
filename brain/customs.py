"""Fort customs: small fixed habits the sliders give a fort (14.1). Not the
earned quirks (quirks.py): a custom holds while its sliders do, nothing more.

    customs.active(traits)                -> ids, in precedence order
    customs.has(traits, cid)              -> bool
    customs.layout_customs(traits, kind)  -> ids the builder's layout reads (style.customs)
    customs.set_adopted(ids)              -> (D0) the design language's adopted customs, added to active()
"""
from __future__ import annotations

# id: (conditions, owner preset (scorecard only), words)
CUSTOMS = {
    "cloister":       ((("piety", ">=", 100), ("welfare", ">=", 40)), "Monastery", "temples ringed by a pillared walk"),
    "cells":          ((("piety", ">=", 100), ("welfare", ">=", 40)), "Monastery", "bedrooms beside the temple"),
    "wide_ways":      ((("trade", ">=", 80), ("outsiders", ">=", 50)), "Merchant city", "3-wide ways to every level"),
    "market_gate":    ((("trade", ">=", 80), ("outsiders", ">=", 50)), "Merchant city", "the tavern by the way in"),
    "winding_ways":   ((("outsiders", "<=", -120), ("caution", ">=", 30)), "Hermit hold", "narrow winding ways"),
    "hidden_hold":    ((("outsiders", "<=", -120), ("caution", ">=", 30)), "Hermit hold", "nothing built above ground"),
    "gate_barracks":  ((("militarism", ">=", 100),), "War-hold", "barracks and ranges by the gate"),
    "armoury":        ((("militarism", ">=", 100),), "War-hold", "an armoury in every barracks"),
    "deep_hall":      ((("mining", ">=", 100), ("verticality", ">=", 60)), "Deep mine", "the dining hall in the deeps"),
    "ore_piles":      ((("mining", ">=", 100), ("verticality", ">=", 60)), "Deep mine", "stone and ore by every workshop"),
    "field_hall":     ((("agriculture", ">=", 80),), "Garden fort", "the dining hall by the fields"),
    "field_kitchens": ((("agriculture", ">=", 80),), "Garden fort", "food workshops by the fields"),
}
LAYOUT = {"cloister": "temple", "armoury": "barracks", "ore_piles": "workshops"}
FOOD_SHOPS = {"Still", "Kitchen", "Farmers", "Quern", "Millstone", "Butchers", "Fishery"}
WINDING_MAX_CITIZENS = 80     # (0.104.107: 1-wide ways jammed a fort of 300)
GATE_BAND = 3                 # the gate band: the 3 levels under the way in


def _v(traits, k) -> float:
    try:
        return float((traits or {}).get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


# (D0) The customs the fort's design language adopted (design.adopted_customs),
# set by the planner at the start of each plan(); () at Scripts.
ADOPTED: tuple = ()
SLIDERS_ONLY = ("hidden_hold", "winding_ways")      # defence and the surface stay the sliders'


def set_adopted(ids) -> None:
    global ADOPTED
    ids = [c for c in (ids or ()) if isinstance(c, str)]
    ADOPTED = tuple(c for c in CUSTOMS if c in ids and c not in SLIDERS_ONLY)


def adopted() -> list[str]:
    return list(ADOPTED)


def active(traits: dict | None) -> list[str]:
    """The sliders' customs, then the adopted ones (each in CUSTOMS order, no
    duplicates)."""
    out = []
    for cid, (conds, _owner, _words) in CUSTOMS.items():
        if all((_v(traits, k) >= n) if op == ">=" else (_v(traits, k) <= n) for k, op, n in conds):
            out.append(cid)
    out.extend(c for c in ADOPTED if c not in out)
    return out


def has(traits: dict | None, cid: str) -> bool:
    return cid in active(traits)


def layout_customs(traits: dict | None, kind: str) -> list[str]:
    return [c for c in active(traits) if LAYOUT.get(c) == kind]
