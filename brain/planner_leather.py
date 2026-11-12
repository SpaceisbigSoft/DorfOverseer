"""(item10) Leather armour for the soldiers while metal is short.

The AI gives a squad the fort's leather uniform until there is metal for
armour (planner_military: "leather until the forge has made metal armour and
helms for every soldier, then metal"), but its gear orders were all metal:
the leather uniform's entries stayed empty while tanned hides lay about.

The `leather_gear` report (lua/ai-leather-gear.lua): `wanted` (uniform slot
-> item kind -> entries asking for leather and holding nothing), `spare` (item
kind -> free leather pieces DF can still hand out) and `classes` (every
material class the uniforms ask for).

leather_gear: while metal is short (fewer weapon-grade bars than
`metal_kit_bars` a soldier: the squads stay in leather), the kinds the empty
entries ask for are made at the leatherworks from the tanned hides (stocks
`leather`, one a piece): body armour, caps, leggings, gloves, high boots (an
entry asking for any kind gets the slot's usual one), less the free pieces
(a pair for gloves and boots) and the orders already queued, at most
`max_gear_order` an order, one slot a cycle (the body first). Under the
Rules switch make_gear, as the metal gear.
"""

from __future__ import annotations

from digest import _d
from planner_core import AGENDA_THEMES, RECIPE_SHOPS, Proposal, _has_shop, player_rules, queued

__all__ = ["_leather_gear_rule", "LEATHER_RECIPES", "LEATHER_SLOT_DEFAULT"]

AGENDA_THEMES.update({"leather_gear": "leather armour for the soldiers"})

# the item kind an entry asks for -> the recipe (lua/ai-bridge-orders.lua)
LEATHER_RECIPES = {"ITEM_ARMOR_LEATHER": "leather_armor", "ITEM_HELM_CAP": "leather_cap",
                   "ITEM_PANTS_LEGGINGS": "leather_leggings", "ITEM_GLOVES_GLOVES": "leather_gloves",
                   "ITEM_SHOES_BOOTS": "leather_high_boots", "ITEM_SHOES_BOOTS_LOW": "leather_low_boots",
                   "ITEM_SHOES_SHOES": "leather_shoes"}
# an entry asking for any kind of the slot, in leather
LEATHER_SLOT_DEFAULT = {"body": "ITEM_ARMOR_LEATHER", "head": "ITEM_HELM_CAP", "pants": "ITEM_PANTS_LEGGINGS",
                        "gloves": "ITEM_GLOVES_GLOVES", "shoes": "ITEM_SHOES_BOOTS"}
SLOT_ORDER = ("body", "head", "shoes", "gloves", "pants")
PAIRS = {"gloves", "shoes"}
SLOT_WORDS = {"body": "body armour", "head": "caps", "pants": "leggings", "gloves": "gloves", "shoes": "boots"}

# the leather recipes are made at the leatherworks (MakeArmor and the rest
# are the forge's in JOB_SHOPS)
for _r in set(LEATHER_RECIPES.values()):
    RECIPE_SHOPS.setdefault(_r, "Leatherworks")


def _leather_gear_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    lg = _d(s.get("leather_gear"))
    if not lg or "error" in lg or not player_rules(s)["make_gear"]:
        return
    wanted = _d(lg.get("wanted"))
    if not any(_d(v) for v in wanted.values()):
        return
    gear = _d(_d(s.get("military")).get("gear"))
    soldiers = int(gear.get("soldiers") or lg.get("soldiers") or 0)
    bars = sum(v for v in _d(gear.get("bars")).values() if isinstance(v, (int, float)))
    if soldiers and bars >= cfg["metal_kit_bars"] * soldiers:
        return                      # metal enough: the squads go to the metal uniform
    leather = int(_d(s.get("stocks")).get("leather") or 0)
    spare = {k: int(v) for k, v in _d(lg.get("spare")).items() if isinstance(v, (int, float))}
    empty_total = sum(int(n or 0) for v in wanted.values() for n in _d(v).values())
    if not _has_shop(_d(s.get("buildings")), "Leatherworks"):
        notes.append(f"{empty_total} leather uniform entr(ies) empty and the fort has no leatherworks to make them")
        return
    if leather <= 0:
        notes.append(f"{empty_total} leather uniform entr(ies) empty and no tanned hides: the leather comes from "
                     "the butchers' and tanners' work, or a caravan")
        return
    for slot in SLOT_ORDER:
        for kind, n in sorted(_d(wanted.get(slot)).items()):
            n = int(n or 0)
            item = LEATHER_SLOT_DEFAULT.get(slot) if kind == "any" else kind
            recipe = LEATHER_RECIPES.get(item)
            if not recipe or n <= 0:
                if n > 0:
                    notes.append(f"{n} {slot} entr(ies) ask for leather {kind}, which the AI has no recipe for")
                continue
            per = 2 if slot in PAIRS else 1
            short = n - spare.get(item, 0) // per - queued(s, {recipe})
            if short <= 0:
                continue
            amount = min(short, leather, cfg["max_gear_order"])
            proposals.append(Proposal("leather_gear", {"type": "work_order", "recipe": recipe, "amount": amount},
                                      f"{n} soldier place(s) wait for leather {SLOT_WORDS[slot]} and metal is short "
                                      f"({round(bars)} bars for {soldiers} soldiers): make {amount} from the "
                                      f"{leather} tanned hides at the leatherworks", 4, True))
            return
