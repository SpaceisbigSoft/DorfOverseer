"""(0.105.40 M7) Alloys at the smelter: a fort without iron arms itself in
bronze, and precious metals piling up are alloyed where the alloy is worth
more.

The game's own smelter reactions from bars (vanilla reaction_smelter.txt, the
"(use bars)" ones; each takes one fuel, none at a magma smelter):

  bronze           1 copper + 1 tin                 -> 2 bars
  bismuth bronze   2 copper + 1 tin + 1 bismuth     -> 4 bars
  brass            1 copper + 1 zinc                -> 2 bars
  electrum         1 gold + 1 silver                -> 2 bars
  billon           1 copper + 1 silver              -> 2 bars
  black bronze     2 copper + 1 silver + 1 gold     -> 4 bars
  rose gold        3 gold + 1 copper                -> 4 bars
  sterling silver  3 silver + 1 copper              -> 4 bars

The bridge's recipes (lua/ai-bridge-orders.lua alloy_*) name these reaction
codes and fall back to the smelter reaction making a bar of that metal from
bars alone when a game lacks the code.

Gear (the Rules switch make_gear): only a fort with no iron route (fewer
than alloy_iron_route_bars iron, pig iron and steel bars, no iron ore in
stock and none uncovered) alloys copper and tin into bronze, bismuth bronze
when there is bismuth too (twice the bars from the same tin), while there are
fewer than alloy_bronze_want bars of them, with fuel at alloy_fuel_min at
least (or a magma smelter); short of fuel it waits and says so. With copper
and no tin bars, tin ore in stock is smelted (the AI's smelting stops at its
gear-metal line, which tin isn't in), and the vein mined is tin's
(tin_ore_first, used by planner_industry's ore rule). The gear rules already
take the best metal with enough bars: steel, iron, bronze, bismuth bronze,
copper (GEAR_METALS).

Value (low priority, a forge and plenty of fuel or a magma smelter): an
alloy whose bars are worth alloy_value_gain times its parts (the game's
metal values, from the gear report's bar_values; the vanilla values below
without them), from metals each over alloy_value_keep bars, while it has
fewer than alloy_value_want bars. Copper for it only past the bronze the
fort still wants.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, player_rules, queued

__all__ = ["ALLOYS", "ALLOY_RECIPES", "GEAR_ALLOYS", "VALUE_ALLOYS", "VANILLA_VALUES", "iron_route",
           "tin_ore_first", "_alloy_rule"]

# metal -> (recipe, parts by metal, bars made)
ALLOYS = {
    "BRONZE": ("alloy_bronze", {"COPPER": 1, "TIN": 1}, 2),
    "BISMUTH_BRONZE": ("alloy_bismuth_bronze", {"COPPER": 2, "TIN": 1, "BISMUTH": 1}, 4),
    "BRASS": ("alloy_brass", {"COPPER": 1, "ZINC": 1}, 2),
    "ELECTRUM": ("alloy_electrum", {"GOLD": 1, "SILVER": 1}, 2),
    "BILLON": ("alloy_billon", {"COPPER": 1, "SILVER": 1}, 2),
    "BLACK_BRONZE": ("alloy_black_bronze", {"COPPER": 2, "SILVER": 1, "GOLD": 1}, 4),
    "ROSE_GOLD": ("alloy_rose_gold", {"GOLD": 3, "COPPER": 1}, 4),
    "STERLING_SILVER": ("alloy_sterling_silver", {"SILVER": 3, "COPPER": 1}, 4),
}
ALLOY_RECIPES = {v[0] for v in ALLOYS.values()}
GEAR_ALLOYS = ("BISMUTH_BRONZE", "BRONZE")       # bismuth bronze first: twice the bars from a tin
VALUE_ALLOYS = ("ROSE_GOLD", "STERLING_SILVER", "ELECTRUM", "BLACK_BRONZE", "BILLON", "BRASS")
# the vanilla MATERIAL_VALUEs, for a bridge that doesn't report bar_values
VANILLA_VALUES = {"COPPER": 2, "TIN": 1, "BISMUTH": 1, "ZINC": 2, "SILVER": 10, "GOLD": 30,
                  "BRONZE": 5, "BISMUTH_BRONZE": 6, "BRASS": 7, "ELECTRUM": 20, "BILLON": 7,
                  "BLACK_BRONZE": 11, "ROSE_GOLD": 20, "STERLING_SILVER": 20}
IRON_METALS = ("IRON", "PIG_IRON", "STEEL")


def _bars(s: dict) -> dict:
    gear = _d(_d(s.get("military")).get("gear"))
    raw = gear.get("all_bars") if isinstance(gear.get("all_bars"), dict) else gear.get("bars")
    return {k: int(v) for k, v in _d(raw).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _ores_by_metal(s: dict, metal: str) -> list:
    """The dug ore stones (name, count) yielding this metal, most first."""
    by = _d(_d(s.get("industry")).get("ore_stock_by"))
    out = [(k, int(_d(v).get("n") or 0)) for k, v in by.items()
           if isinstance(v, dict) and metal in _l(v.get("metals")) and int(v.get("n") or 0) > 0]
    return sorted(out, key=lambda x: (-x[1], x[0]))


def iron_route(s: dict, cfg: dict, bars: dict | None = None) -> bool:
    """Iron in the fort's reach: bars enough, iron ore dug, or a vein uncovered."""
    bars = _bars(s) if bars is None else bars
    gear = _d(_d(s.get("military")).get("gear"))
    have = sum(bars.get(m, 0) for m in ("IRON", "STEEL")) + max(bars.get("PIG_IRON", 0),
                                                                 int(gear.get("pig_iron") or 0))
    if have >= cfg["alloy_iron_route_bars"]:
        return True
    return bool(_ores_by_metal(s, "IRON")) or "IRON" in _d(_d(s.get("industry")).get("ores"))


def tin_ore_first(s: dict, cfg: dict, ores: dict) -> str | None:
    """"TIN" when the vein worth mining is tin's: no iron route, a tin vein
    uncovered, copper bars enough, no tin bars and no tin ore dug."""
    bars = _bars(s)
    if ("TIN" not in ores or "IRON" in ores or iron_route(s, cfg, bars) or bars.get("COPPER", 0) < cfg["alloy_tin_copper_bars"]
            or bars.get("TIN", 0) > 0 or _ores_by_metal(s, "TIN") or not player_rules(s)["make_gear"]):
        return None
    return "TIN"


def _values(s: dict) -> dict:
    v = dict(VANILLA_VALUES)
    for k, n in _d(_d(_d(s.get("military")).get("gear")).get("bar_values")).items():
        if isinstance(n, (int, float)) and not isinstance(n, bool) and n >= 0:
            v[k] = n
    return v


def _reactions(bars: dict, parts: dict, keep: dict) -> int:
    return min((bars.get(m, 0) - keep.get(m, 0)) // k for m, k in parts.items())


def _alloy_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    furnaces = _d(_d(s.get("buildings")).get("furnaces"))
    magma = bool(furnaces.get("MagmaSmelter"))
    if not (furnaces.get("Smelter") or magma):
        return
    bars = _bars(s)
    if not any(bars.get(m, 0) for m in ("TIN", "ZINC", "GOLD", "SILVER")) and not _ores_by_metal(s, "TIN"):
        return                                    # nothing to alloy with (most forts: identical to before)
    if queued(s, ALLOY_RECIPES, ai_only=True):
        return
    fuel = int(_d(s.get("supplies")).get("fuel") or 0)
    gear_wants = 0
    # 1. gear: bronze for a fort with no iron
    if player_rules(s)["make_gear"] and not iron_route(s, cfg, bars):
        bronze = bars.get("BRONZE", 0) + bars.get("BISMUTH_BRONZE", 0)
        gear_wants = max(0, cfg["alloy_bronze_want"] - bronze)
        keep = {"COPPER": cfg["alloy_copper_keep"]}
        if gear_wants and bars.get("TIN", 0) <= 0 and bars.get("COPPER", 0) > cfg["alloy_copper_keep"]:
            ores = _ores_by_metal(s, "TIN")
            if ores and (fuel > 0 or magma) and player_rules(s)["import_smelting"] \
                    and not queued(s, {"smelt_ore"}, ai_only=True) \
                    and not any(p.action.get("recipe") == "smelt_ore" for p in proposals):
                ore, n = ores[0]
                amount = max(1, min(n, cfg["smelt_batch"], fuel if not magma else 99))
                proposals.append(Proposal("alloy", {"type": "work_order", "recipe": "smelt_ore", "amount": amount,
                                                    "material": f"INORGANIC:{ore}"},
                                          f"{bars.get('COPPER', 0)} copper bars, no tin and no iron: smelt {amount} "
                                          f"{ore.lower()} for tin (copper and tin make bronze)", 5, True))
                return
        for metal in GEAR_ALLOYS:
            recipe, parts, out = ALLOYS[metal]
            n = _reactions(bars, parts, keep)
            if n <= 0 or not gear_wants:
                continue
            if not magma and fuel < cfg["alloy_fuel_min"]:
                notes.append(f"copper and tin bars for {metal.lower().replace('_', ' ')} (no iron here), but only "
                             f"{fuel} charcoal or coke: the bronze waits for fuel (charcoal or coke is made as wood or coal allows)")
                return
            n = max(1, min(n, cfg["alloy_batch"], -(-gear_wants // out), fuel if not magma else 99))
            proposals.append(Proposal("alloy", {"type": "work_order", "recipe": recipe, "amount": n},
                                      f"no iron here, {bars.get('COPPER', 0)} copper and {bars.get('TIN', 0)} tin bars"
                                      + (f" and {bars.get('BISMUTH', 0)} bismuth" if "BISMUTH" in parts else "")
                                      + f": alloy {n * out} {metal.lower().replace('_', ' ')} bars for the "
                                        "soldiers' gear (better than copper)", 5, True))
            return
    # 2. value: precious metals piled up, alloyed where the alloy is worth more
    if not _d(_d(s.get("military")).get("gear")).get("forges"):
        return
    if not magma and fuel < cfg["alloy_value_fuel_min"]:
        return
    values = _values(s)
    keep_n = cfg["alloy_value_keep"]
    for metal in VALUE_ALLOYS:
        recipe, parts, out = ALLOYS[metal]
        if bars.get(metal, 0) >= cfg["alloy_value_want"]:
            continue
        worth_parts = sum(values.get(m, 0) * k for m, k in parts.items())
        if worth_parts <= 0 or values.get(metal, 0) * out < cfg["alloy_value_gain"] * worth_parts:
            continue
        keep = {m: keep_n for m in parts}
        if "COPPER" in parts and gear_wants:
            keep["COPPER"] = keep_n + gear_wants      # the bronze the fort still wants comes first
        n = _reactions(bars, parts, keep)
        if n <= 0:
            continue
        n = max(1, min(n, cfg["alloy_batch"], -(-(cfg["alloy_value_want"] - bars.get(metal, 0)) // out)))
        have = ", ".join(f"{bars.get(m, 0)} {m.lower()}" for m in parts)
        proposals.append(Proposal("alloy", {"type": "work_order", "recipe": recipe, "amount": n},
                                  f"{have} bars spare: alloy {n * out} {metal.lower().replace('_', ' ')} bars "
                                  f"(worth {values.get(metal, 0) * out} a reaction against {worth_parts} for "
                                  "the parts), for crafts and trade", 7, True))
        return
