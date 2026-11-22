"""planner_building_stores: furniture and shop pieces waiting in projects,
the planned parts, room repair and cleanup, the stores that grow and the
fallbacks for a stuck recipe (split out of planner_building in r7 d4,
moved unchanged). planner_building re-exports every name here."""

from __future__ import annotations

import math
import re
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
import design  # (D0) the design language's naming
from learning import held_levels
import customs
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_construct import _soil_floor_rule  # (0.105.30) block floors over a finished hall's soil
from planner_growth import *  # noqa: F401,F403  (13c: split out by theme)
from planner_wells import *  # noqa: F401,F403  (13c: split out by theme)
from planner_garden import garden_pace  # (0.105.47) the statue gardens sooner by Agriculture
from planner_alloys import gear_metals  # (fix41) tin and bismuth kept for bronze while there is no iron

__all__ = ["FURNITURE_RECIPES", "SHOP_PIECE_RECIPES", "SHOP_PIECE_WORDS", "SHOP_KINDS", "waiting_shops", "METAL_FURNITURE", "spare_metal", "WOODEN_FURNITURE", "BASIC_STOCKPILES", "memorial_due", "PLANNED_SAID", "_planned_note", "PLANNED_RECIPES", "planned_wants", "_planned_parts_rule", "_room_repair_rule", "_cleanup_rule", "STORE_GROW", "stone_tidiness", "STUCK_FALLBACKS", "BAG_KIND", "WEAVE_KIND", "RECIPES_WITH_METAL", "stuck_fallback", "full_stores"]


# Furniture waiting in a project -> the recipe that makes it.
# (a well's parts are ordered by the well rule: it needs four different things)
FURNITURE_RECIPES = {"Bed": "wooden_bed", "Door": "stone_door", "Table": "stone_table",
                     "Chair": "stone_chair", "Cabinet": "stone_cabinet", "Box": "stone_chest",
                     "Statue": "stone_statue", "Armorstand": "stone_armor_stand",
                     "Weaponrack": "stone_weapon_rack", "Coffin": "stone_coffin",
                     "Bookcase": "stone_bookcase"}
# (0.105.51) A planned workshop waiting for the piece it is built from (the
# report's furnish.waiting_shops, by the workshop's kind) -> the recipe making
# that piece. Only these: the others are built from any block or boulder.
SHOP_PIECE_RECIPES = {"Quern": "stone_quern", "Millstone": "stone_millstone"}
SHOP_PIECE_WORDS = {"Quern": "a quern", "Millstone": "a millstone"}
SHOP_KINDS = {"Workshop", "Furnace"}


def waiting_shops(p: dict) -> dict:
    """{workshop kind: how many} a project's planned workshops wait for their
    pieces. An older bridge says only "Workshop": the kinds then come from what
    the level planned (its furniture) that has a piece to make."""
    fur = _d(p.get("furnish"))
    named = {k: int(v or 0) for k, v in _d(fur.get("waiting_shops")).items() if isinstance(v, (int, float))}
    if named:
        return named
    n = int(_d(fur.get("waiting")).get("Workshop") or 0)
    planned = [k for k in _d(p.get("furniture")) if k in SHOP_PIECE_RECIPES]
    return {planned[0]: n} if n and len(planned) == 1 else {}


# The metal version of a stone furniture recipe (made at the forge).
METAL_FURNITURE = {"stone_table": "metal_table", "stone_chair": "metal_chair", "stone_door": "metal_door",
                   "stone_cabinet": "metal_cabinet", "stone_chest": "metal_chest", "stone_coffin": "metal_coffin",
                   "stone_armor_stand": "metal_armor_stand", "stone_weapon_rack": "metal_weapon_rack"}


def spare_metal(s: dict, cfg: dict, amount: int) -> str | None:
    """A metal for furniture: one the soldiers' gear doesn't use (silver,
    gold, tin...), with `metal_furniture_bars` bars to spare after `amount`
    pieces (3 bars each), a forge, and fuel for it. The most plentiful."""
    gear = _d(_d(s.get("military")).get("gear"))
    if not gear.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < amount + 5:
        return None
    bars = {k: int(v) for k, v in _d(gear.get("all_bars")).items() if isinstance(v, (int, float))}
    keep = gear_metals(s, cfg)      # (fix41) tin and bismuth too while the fort alloys bronze for gear
    ok = [(n, m) for m, n in bars.items()
          if m not in keep and m not in ("PIG_IRON",) and n - 3 * amount >= cfg["metal_furniture_bars"]]
    return max(ok)[1] if ok else None


# The wooden version of a stone furniture recipe (Materials: "wood where it will do").
WOODEN_FURNITURE = {"stone_table": "wooden_table", "stone_chair": "wooden_chair", "stone_door": "wooden_door",
                    "stone_cabinet": "wooden_cabinet", "stone_chest": "wooden_chest",
                    "stone_coffin": "wooden_coffin", "stone_armor_stand": "wooden_armor_stand",
                    "stone_weapon_rack": "wooden_weapon_rack", "stone_bookcase": "wooden_bookcase"}
BASIC_STOCKPILES = ["food", "stone", "wood", "furniture", "bars_blocks", "finished_goods"]


def memorial_due(s: dict, memory, rules: dict) -> bool:
    pace = rules["memorial_pace"]
    if pace == "never":
        return False
    last = memory.last_memorial_tick
    return last is None or not 0 <= abs_tick(s) - last < MEMORIAL_SPAN[pace]


PLANNED_SAID = {"Well", "Hatch", "Trap", "Floodgate", "Bridge", "Door"}   # (0.104.154) the ones that guard or water the fort


def _planned_note(s: dict, notes: list) -> None:
    """(0.104.154) What buildingplan's waiting buildings lack: the well, gate
    hatches, levers and doors by name and place, with buildingplan's own
    words and suspendmanager's reason (Teacheroar: a cavern well 85 days and a
    gate hatch 129 days with every part in store)."""
    pl = _d(s.get("planned"))
    lst = [x for x in _l(pl.get("list")) if isinstance(x, dict) and x.get("kind") in PLANNED_SAID]
    if not lst:
        return
    bits = []
    for x in lst[:4]:
        wants = "; ".join(f"{i.get('want')}" + (f" (queue {i.get('queue')})" if i.get("queue") else "")
                          for i in _l(x.get("items")) if isinstance(i, dict) and i.get("want"))
        bits.append(f"{x.get('kind')} at x{x.get('x')} y{x.get('y')} elevation {x.get('elevation')}"
                    + (f": wants {wants}" if wants else "") + (f"; {x.get('why')}" if x.get("why") else ""))
    notes.append(f"{pl.get('n')} planned building(s) wait for parts; " + " | ".join(bits))


# (0.104.154) what buildingplan waits for -> the work order that makes it,
# and the recipes that count as already on order for it
PLANNED_RECIPES = {
    "mechanism": ("mechanisms", {"mechanisms"}),
    "block": ("stone_blocks", {"stone_blocks", "glass_blocks"}),
    "bucket": ("wooden_bucket", {"wooden_bucket"}),
    "hatch cover": ("stone_hatch_cover", {"stone_hatch_cover"}),
    "door": ("stone_door", {"stone_door", "wooden_door", "metal_door", "glass_door"}),
    "chair": ("stone_chair", {"stone_chair", "wooden_chair", "metal_chair", "glass_chair"}),
    "table": ("stone_table", {"stone_table", "wooden_table", "metal_table", "glass_table"}),
    "coffin": ("stone_coffin", {"stone_coffin", "wooden_coffin", "metal_coffin"}),
    "cabinet": ("stone_cabinet", {"stone_cabinet", "wooden_cabinet", "metal_cabinet", "glass_cabinet"}),
    "chest": ("stone_chest", {"stone_chest", "wooden_chest", "metal_chest", "glass_chest"}),
    "bed": ("wooden_bed", {"wooden_bed"}),
}


def planned_wants(s: dict) -> dict:
    """(0.104.154) {thing: how many} buildingplan's waiting buildings still lack
    ("1 Mechanism", "2 Block"; a 0 is already attached)."""
    out: dict = {}
    for b in _l(_d(s.get("planned")).get("list")):
        for it in _l(_d(b).get("items")) if isinstance(b, dict) else []:
            m = re.match(r"^\s*(\d+)\s+(.+?)\s*$", str(_d(it).get("want") or ""))
            if not m or int(m.group(1)) <= 0:
                continue
            thing = re.sub(r"\s*\(.*\)$", "", m.group(2)).lower().rstrip("s")
            out[thing] = out.get(thing, 0) + int(m.group(1))
    return out


def _planned_parts_rule(s: dict, proposals: list, notes: list) -> None:
    """(0.104.154) Parts the waiting buildings lack, ordered from buildingplan's
    own list, not the stock count (Teacheroar, 1 Nov: 3 mechanisms "in store"
    that buildingplan never used, so no rule ordered more, while the cavern
    well, its gate lever and three traps waited for one each)."""
    wants = planned_wants(s)
    for thing, n in sorted(wants.items(), key=lambda kv: (-kv[1], kv[0])):    # the most wanted first
        rec = PLANNED_RECIPES.get(thing)
        if not rec:
            continue
        recipe, same = rec
        if queued(s, same):
            continue
        amount = min(10, n)
        proposals.append(Proposal("planned_parts", {"type": "work_order", "recipe": recipe, "amount": amount},
                                  f"{n} planned building part(s) wait for a {thing} buildingplan can't find "
                                  f"(whatever the stock count says): make {amount}", 3, True))


def _room_repair_rule(s: dict, proposals: list) -> None:
    """(0.104.20) Rooms whose walls were dug open (Enxah's quarry ate the
    walls between the old bedrooms: the player's screenshot): the walls built
    back, a batch every few days (the bridge finds the gaps from the rooms
    themselves: a bedroom or office zone with a door in its wall ring)."""
    rg = _d(s.get("room_gaps"))
    if (rg.get("gaps") or 0) > 0:
        proposals.append(Proposal("rooms", {"type": "repair_rooms"},
                                  f"{rg.get('rooms')} room(s) have {rg.get('gaps')} gap(s) in their walls (dug "
                                  "through): build the walls back", 4))
    elif (rg.get("stalled") or 0) > 0:
        # (0.104.25) walls planned on floors marked for smoothing: suspendmanager
        # holds them for the mark (Enxah: 40 walls suspended a season)
        proposals.append(Proposal("rooms", {"type": "repair_rooms"},
                                  f"{rg['stalled']} planned wall(s) wait on floors marked for smoothing (DFHack's "
                                  "suspendmanager keeps them suspended): clear the marks so they're built", 3))


def _cleanup_rule(s: dict, memory, proposals: list) -> None:
    """Gates the AI built at "entrances" a full scan no longer finds, on the
    surface (0.39 took the shade of trees for the fort): taken down, one a
    cycle. The game checks again that the spot is on the surface and isn't
    an entrance before anything is removed."""
    a = _d(memory.atlas)
    ents, reg = _d(a.get("entrances")), _d(a.get("registry"))
    for rid, rec in reg.items():
        prefix, _, spot = rid.partition(":")
        if prefix not in ("gate", "doors") or not isinstance(rec, dict) or rec.get("status") not in ("built", "open again"):
            continue
        e = _d(ents.get(spot))
        if not e.get("gone") or e.get("kind") not in (None, "surface"):
            continue
        try:
            x, y, z = (int(v) for v in spot.split(","))
        except ValueError:
            continue
        action = {"type": "clear_gate", "x": x, "y": y, "z": z, "spot": spot}
        if rec.get("pieces"):
            action["pieces"] = list(rec["pieces"])[:80]
        proposals.append(Proposal("cleanup", action,
                                  f"the AI built a gate at x{x} y{y} for an entrance that no longer exists (the "
                                  "shade of a tree, in 0.39): take it down", 6))
        return


# kinds of stockpile the planner adds storage for. Stone and ore (0.93) only
# past a pile of loose stone set by Industriousness: hauling every stone is
# work, leaving it is clutter (region2 had 557 loose with its piles full).
STORE_GROW = ("food", "wood", "bars_blocks", "furniture", "finished_goods", "cloth", "leather", "gems",
              "weapons", "armor",   # (0.99.12) the forge's products
              "ammo")               # (0.100) bolts for the crossbow squad


def stone_tidiness(traits: dict, cfg: dict) -> tuple[int, int] | None:
    """(0.93) How tidy the fort keeps its stone: (loose stones before more
    stone storage, the most stone storage tiles), or None when it leaves
    stone where it's dug (Industriousness -100 or lower). A busy fort (+100)
    clears it at 100 loose and stores up to 1200 tiles; an idle one (-50)
    lets 280 lie and stores at most about 420."""
    if traits.get("industriousness", 0) <= -100:
        return None
    f = factor(traits, "industriousness")
    return int(cfg["store_stone_loose"] / f), int(cfg["store_stone_max_tiles"] * f)


# (0.104.138, 12l) What a stuck order is made of instead: an order cancelled
# as stuck was held up to 112 days and then placed again unchanged
# (Teacheroar: stone coffins, slabs and jewellery with no stone the masons
# may use; cloth rope with only the hospital's cloth). The first alternative
# with its material at hand is ordered in its place.
STUCK_FALLBACKS = {
    **{k: (v,) + ((k.replace("stone_", "metal_"),) if k.replace("stone_", "metal_") in METAL_FURNITURE.values() else ())
       for k, v in WOODEN_FURNITURE.items()},
    "stone_mugs": ("wooden_cups",),
    "stone_crafts": ("bone_crafts", "wood_crafts", "metal_crafts"),       # (0.104.141) bone first
    "stone_amulet": ("metal_amulet", "bone_crafts", "wood_crafts"), "stone_bracelet": ("metal_bracelet", "bone_crafts", "wood_crafts"),
    "stone_ring": ("metal_ring", "bone_crafts", "wood_crafts"), "stone_earring": ("metal_earring", "bone_crafts", "wood_crafts"),
    "wood_crafts": ("bone_crafts",), "bone_crafts": ("wood_crafts",),
    "cloth_rope": ("metal_chain",),
    "weave_plant_cloth": ("weave_silk_cloth", "weave_yarn_cloth"),     # (0.104.140)
    "cloth_bag": ("silk_bag", "yarn_bag"), "silk_bag": ("cloth_bag", "yarn_bag"), "yarn_bag": ("cloth_bag", "silk_bag"),
}
BAG_KIND = {"cloth_bag": "plant", "silk_bag": "silk", "yarn_bag": "yarn"}
WEAVE_KIND = {"weave_silk_cloth": "silk", "weave_yarn_cloth": "yarn"}
RECIPES_WITH_METAL = {"metal_table", "metal_chair", "metal_door", "metal_cabinet", "metal_chest", "metal_coffin",
                      "metal_armor_stand", "metal_weapon_rack", "metal_chain", "metal_crafts", "metal_amulet",
                      "metal_bracelet", "metal_ring", "metal_earring"}


def stuck_fallback(p, s: dict, memory, cfg: dict, now: int) -> dict | None:
    """(0.104.138) The action to order instead of a work order held as stuck:
    the first alternative not itself stuck lately, with its material at hand
    and its workshop built. None when there is none."""
    a = p.action
    recipe = str(a.get("recipe") or "")
    amount = int(a.get("amount") or 1)
    b = _d(s.get("buildings"))
    wood = int(_d(s.get("stocks")).get("wood") or 0) - int(_d(s.get("dwarves")).get("total") or 0) * cfg["wood_per_dwarf"]
    kinds = _d(_d(s.get("supplies")).get("cloth_kinds"))
    stuck = _d(getattr(memory, "stuck_cancelled", None))
    for alt in STUCK_FALLBACKS.get(recipe, ()):
        sc = _d(stuck.get(alt))
        if isinstance(sc.get("tick"), int) and 0 <= now - sc["tick"] < stuck_hold_days(sc, cfg) * TICKS_PER_DAY:
            continue
        shop = recipe_shop(alt)
        if shop and (b.get("workshops") is not None or b.get("furnaces") is not None) and not _has_shop(b, shop):
            continue
        act = {k: v for k, v in a.items() if k != "material"}
        act["recipe"] = alt
        if alt in RECIPES_WITH_METAL:
            if alt in ("metal_chain", "metal_crafts") or alt.startswith(("metal_amulet", "metal_bracelet",
                                                                            "metal_ring", "metal_earring")):
                gear_ = _d(_d(s.get("military")).get("gear"))
                if not gear_.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < amount + 5:
                    continue                            # (a forge and fuel, as spare_metal asks)
                bars = _d(_d(_d(s.get("military")).get("gear")).get("all_bars"))
                keep = gear_metals(s, cfg)      # (fix41) tin and bismuth too while bronze is the gear
                m = max(((int(v), k) for k, v in bars.items() if isinstance(v, (int, float)) and k not in keep
                         and k != "PIG_IRON" and int(v) >= 2 * amount + 5), default=None)
                metal = m[1] if m else None
            else:
                metal = spare_metal(s, cfg, amount)
            if not metal:
                continue
            act["material"] = f"INORGANIC:{metal}"
        elif alt.startswith(("wooden_", "wood_")):
            if wood < amount + 5:
                continue
        elif alt == "bone_crafts":
            if int(_d(s.get("needs")).get("bones") or 0) < amount:
                continue
        elif alt in BAG_KIND:
            if kinds and int(kinds.get(BAG_KIND[alt]) or 0) < amount:
                continue
        elif alt in WEAVE_KIND:
            th = _d(_d(s.get("supplies")).get("thread_kinds"))
            if int(th.get(WEAVE_KIND[alt]) or 0) < amount:
                continue                                # (no thread of that kind, or an older bridge)
        return act
    return None


def full_stores(s: dict, cfg: dict) -> list:
    """Kinds whose stockpiles are nearly full (or missing) while things of
    that kind lie loose: fullest first."""
    st = _d(_d(s.get("logistics")).get("storage"))
    if "error" in st:
        return []
    out = []
    for k in STORE_GROW:
        r = _d(st.get(k))
        tiles, used, lz = int(r.get("tiles") or 0), int(r.get("used") or 0), int(r.get("loose") or 0)
        # (0.104.157) products left in their workshops are in `loose` already (the
        # survey's STORE_FROM_WORKSHOPS kinds); used cups lying in halls are not
        if k == "finished_goods":
            lz += unstored_cups(s)
        # (0.105.0) bolts come 25 to a stack (one item): with no ammo pile at
        # all, any lying in the bowyer's or forge want one (the squads take
        # bolts only from a stockpile; Teacheroar's 524 never reached them)
        lmin = cfg.get("store_loose_min_ammo", 1) if (k == "ammo" and tiles == 0) else cfg["store_loose_min"]
        if lz >= lmin and (tiles == 0 or used / tiles >= cfg["store_full_share"]):
            out.append((-(used / tiles if tiles else 1.0), -lz, k))
    kinds = [k for *_, k in sorted(out)]
    tidy = stone_tidiness(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)
    r = _d(st.get("stone"))
    tiles, used, lz = int(r.get("tiles") or 0), int(r.get("used") or 0), int(r.get("loose") or 0)
    if tidy and lz >= tidy[0] and tiles < tidy[1] and (tiles == 0 or used / tiles >= cfg["store_full_share"]):
        kinds.append("stone")                    # after the goods: stone waits its turn
    return kinds
