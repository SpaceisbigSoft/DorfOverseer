"""planner_flour (item7): flour for the good meals.

A meal's worth a serving is its ingredients' worth a unit times its quality
(probe i7mealval, 26 Nov 00:09): E's 2,930 servings by quality 0-4 were worth
4.0, 7.6, 11.1, 15.1 and 22.8 a serving, F's 3.8 ... 22.7, A's 3.9 ... 21.1
(and 39.4 at quality 5, A's legendary cook). The ingredients were plants at
2-4 a unit (E: 1,089 plants at 3.9, no meat, 2 cheese, 1 flour), so only a
quality-4 meal passed the 20 a good meal needs (DF: "a meal worth over 20",
or a preferred food): 45 of E's servings, 44 of F's, while 308 and 301 were
quality 3. The 0.105.123 chain (the best free cook alone at the kitchen, the
cheap kinds and drink kept from the cooks) worked; what it cooked from was the
limit. A quern turns a millable plant into an edible powder (flour, sugar)
worth 20 a unit (raws: MILL material_value 20): a lavish meal with flour in it
is a good meal from quality 2 up. No rule ever ordered milling (mill_plants
was in the bridge's recipes, unused); E, A, B and F each had a quern idle.

While the dwarves want good meals (good_meals_short), the fort has a Kitchen,
a Quern or Millstone, an empty bag (the powder's), drink at its target (the
millable crops brew too) and under FLOUR_KEEP_PD flour a citizen: mill_plants
for up to FLOUR_ORDER_MAX. The game picks any millable plant, dye plants too
(dimple cups, hide roots: E 24 units beside 28 of millet, cave wheat and sweet
pods), so only while the edible ones are FLOUR_EDIBLE_SHARE of the millable
units at least. Milling gives the plant's seed back.
"""

from __future__ import annotations

from digest import _d
from planner_core import AGENDA_THEMES, COOLDOWN_KEYS, Proposal, _has_shop, queued

__all__ = ["flour_due", "flour_rule", "FLOUR_KEEP_PD", "FLOUR_ORDER_MAX", "FLOUR_EDIBLE_SHARE", "FLOUR_MIN"]

AGENDA_THEMES["mill_flour"] = "flour for good meals"
COOLDOWN_KEYS["mill_flour"] = "needs_meal_cooldown_ticks"

FLOUR_KEEP_PD = 0.5        # flour a citizen kept in store (20 at least) before more is milled
FLOUR_ORDER_MAX = 10       # plants milled an order
FLOUR_EDIBLE_SHARE = 0.5   # the edible share of the millable plants the order needs
FLOUR_MIN = 4              # edible millable plants, the least worth an order


from util import int_or_zero as _int  # noqa: E402  (util's, test_r6_c2)


def flour_due(s: dict, cfg: dict, memory=None) -> tuple[int, str]:
    """(amount, why): how many plants to mill now, 0 with the reason why not
    ("" when good meals aren't wanted or the report is older)."""
    sup = _d(s.get("supplies"))
    mill = _d(sup.get("millable"))
    if "edible" not in mill or not isinstance(sup.get("flour"), int):
        return 0, ""                                       # an older bridge
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    from planner_farms import drink_below_target, good_meals_short
    if not good_meals_short(s, cfg, citizens, held=_int(sup.get("flour")) > 0):
        return 0, ""
    b = _d(s.get("buildings"))
    if not _has_shop(b, "Kitchen"):
        return 0, ""
    if not (_has_shop(b, "Quern") or _has_shop(b, "Millstone")):
        return 0, "no quern or millstone to mill flour at"
    if queued(s, {"mill_plants"}):
        return 0, ""
    keep = max(20, int(citizens * FLOUR_KEEP_PD))
    if _int(sup.get("flour")) >= keep:
        return 0, ""
    edible, other = _int(mill.get("edible")), _int(mill.get("other"))
    if edible < FLOUR_MIN:
        return 0, f"only {edible} plants that mill to flour or sugar"
    if edible < FLOUR_EDIBLE_SHARE * (edible + other):
        return 0, (f"{edible} plants mill to flour or sugar and {other} to dye: the quern would take the dye "
                   "plants as often")
    if drink_below_target(s, citizens, cfg, memory):
        return 0, "drink is under its target (the millable crops brew too)"
    bags = _int(sup.get("empty_bags"))
    if bags <= 0:
        return 0, "no empty bag for the flour"
    return min(FLOUR_ORDER_MAX, edible // 2 or 1, bags, keep - _int(sup.get("flour"))), ""


def flour_rule(s: dict, memory, cfg: dict, proposals: list, notes: list | None = None) -> None:
    """mill_plants while the good meals are short and the fort cooks from plants alone."""
    n, why = flour_due(s, cfg, memory)
    sup = _d(s.get("supplies"))
    if n <= 0:
        if why and notes is not None:
            notes.append(f"good meals are few and the kitchen cooks from plants worth 2-4 a unit: no flour milled ({why})")
        return
    good = _int(sup.get("good_meals"))
    proposals.append(Proposal("mill_flour", {"type": "work_order", "recipe": "mill_plants", "amount": n},
                              f"{good} meals are worth over 20 and the cooks have plants worth 2-4 a unit and "
                              f"{_int(sup.get('flour'))} flour: mill {n} plants to flour or sugar at the quern "
                              "(worth 20 a unit; a lavish meal with it is good from quality 2)", 6, True))
