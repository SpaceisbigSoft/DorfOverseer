"""planner_building: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
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

__all__ = ["STUCK_FALLBACKS", "stuck_fallback", "magma_access", "GROWTH", "GROWTH_EXTRA_SCORE", "GROWTH_MAX", "growth_want", "growth_candidates", "settled_times", "growth_wait", "GROWTH_SOLDIERS", "GROWTH_ZONES", "GROWTH_MAX_OF", "GROWTH_AT", "TRAIT_NAMES_SHORT", "FURNITURE_RECIPES", "METAL_FURNITURE", "spare_metal", "WOODEN_FURNITURE", "BASIC_WORKSHOPS", "BASIC_STOCKPILES", "memorial_due", "_well_rule", "_well_lid_rule", "cavern_danger", "_planned_note", "_planned_parts_rule", "planned_wants", "_water_zone_rule", "cavern_well_need", "cavern_points", "cavern_action", "cavern_well_safe", "WELL_PARTS_SHOPS", "chain_metal", "well_parts_plan", "_well_parts", "_room_repair_rule", "_water_traffic_rule", "_cleanup_rule", "STORE_GROW", "stone_tidiness", "jail_plan", "cistern_pop", "tavern_factor", "full_stores", "LEARNING_NEEDS", "_stairwell_rule", "WATER_WORDS", "water_summary", "_water_rules", "CISTERN_WORDS", "_cistern_parts", "_cistern_rule", "_deep_notes", "good_times", "ORDINALS", "garden_name", "_pop_cap_rule", "fort_strain", "hospital_shortfall", "dining_shortfall", "social_shortfall", "SOCIAL_KINDS", "_join_rule", "_dig_stall_rule", "_shrink_rule", "room_size", "_project_rules", "CHARACTER_KINDS", "is_character_level", "character_slot_reserved", "character_slot_filter", "temple_size", "more_temple", "has_grand_temple", "piety_slot", "LADDER_BASE", "LADDER_TRAITS", "_ladder_kind", "_ladder_word", "ladder_score", "tombs_short", "PLACEMENT_CUSTOMS", "apply_customs", "customs_pass"]


# Furniture waiting in a project -> the recipe that makes it.
# (a well's parts are ordered by the well rule: it needs four different things)
FURNITURE_RECIPES = {"Bed": "wooden_bed", "Door": "stone_door", "Table": "stone_table",
                     "Chair": "stone_chair", "Cabinet": "stone_cabinet", "Box": "stone_chest",
                     "Statue": "stone_statue", "Armorstand": "stone_armor_stand",
                     "Weaponrack": "stone_weapon_rack", "Coffin": "stone_coffin",
                     "Bookcase": "stone_bookcase"}

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
    ok = [(n, m) for m, n in bars.items()
          if m not in GEAR_METALS and m not in ("PIG_IRON",) and n - 3 * amount >= cfg["metal_furniture_bars"]]
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
                m = max(((int(v), k) for k, v in bars.items() if isinstance(v, (int, float)) and k not in GEAR_METALS
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


def _stairwell_rule(s: dict, memory, cfg: dict, traits: dict, proposals: list) -> None:
    """(0.104.82) Stairwells, as the fort's style asks (the Stairwells area:
    one great stair, a second one, or one a district; The Hundred Stairs two
    more): while the survey counts fewer, a new one for the next district of
    the plan without one, `dir` of the main stair, from the district's top
    down through its levels. A season apart (the survey counts again)."""
    if memory is None or young_fort(s, cfg):
        return
    if int(_d(s.get("dwarves")).get("total") or 0) < cfg["stairwell_min_citizens"]:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    site = _d(_d(_d(memory.atlas).get("survey")).get("site"))
    have = site.get("stairwells")
    if not isinstance(have, int):
        return                                  # an older bridge's survey: nothing counted
    try:
        want = int(profile_from(traits, memory.culture).get("stairwells") or 1)
    except (TypeError, ValueError):
        want = 1
    if has_rule(_d(memory.culture), "many_stairs"):
        want += 2
    if have >= want:
        return
    import masterplan
    d = masterplan.stairwell_district(memory)
    if not d:
        return
    plan = _d(_d(memory.atlas).get("plan"))
    spine = _d(plan.get("spine"))
    dirs = [x for x in d.get("dirs") or [] if x in masterplan.DIRS]
    action = {"type": "dig_stairwell", "dir": dirs[0], "elev_lo": int(d["lo"]), "elev_hi": int(d["hi"]),
              "district": d.get("id")}
    if isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
        action["spine"] = {"x": spine["x"], "y": spine["y"]}
    proposals.append(Proposal("stairwell", action,
                              f"the fort's style asks for {want} stairwell(s) and it has {have}: a new one "
                              f"{dirs[0]} of the main stair for {d.get('name') or d.get('id')} "
                              f"(elevations {d['lo']}-{d['hi']}), its levels to grow from it", 6))


def _deep_notes(s: dict, notes: list) -> None:
    """The deep (the bridge's `deep` report): caverns found and whether the
    fort's ground joins them, great dangers on the map and where, cursed
    citizens. Said, and Needs you where only the player can act."""
    d = s.get("deep")
    if not isinstance(d, dict) or "error" in d:
        return
    caverns = [c for c in _l(d.get("caverns")) if isinstance(c, dict)]
    open_ = [c for c in caverns if c.get("discovered") and c.get("open")]
    dangers = [x for x in _l(d.get("dangers")) if isinstance(x, dict) and not x.get("caged")]
    for c in open_:
        at = _d(c.get("open_at"))                   # (0.104.101) where the dwarves' ground meets it
        where_ = f" (the dwarves' ground meets it at x{at.get('x')} y{at.get('y')} z{at.get('z')})" if at else ""
        here = [x for x in dangers if x.get("layer") == c.get("name")]
        if here:
            ask_player(notes, f"{c['name']} is open to the fort{where_} and {here[0].get('name')} ({here[0].get('kind')}) "
                              f"is in it: seal the way down (the AI walls cavern openings it finds; check "
                              "the entrances line) and keep the dwarves inside")
        else:
            notes.append(f"{c['name']} is open to the fort's ground (z{c.get('z_bottom')}-{c.get('z_top')}){where_}: the AI "
                         "walls the openings it finds; cavern creatures can walk in until then")
    for x in dangers:
        if x.get("layer") in [c.get("name") for c in open_]:
            continue
        where = x.get("layer") or "the map"
        reach = " and can reach the dwarves" if x.get("can_reach_dwarves") else ""
        notes.append(f"{x.get('name')} ({x.get('kind')}) is in {where.replace('_', ' ')}{reach}")
    for c in [c for c in _l(d.get("cursed")) if isinstance(c, dict)]:
        if c.get("kind") == "vampire" and player_rules(s).get("expel_vampires", True):
            notes.append(f"{c.get('name')} is a vampire: the AI sends them away (Rules tab)")
        elif c.get("kind") == "vampire":
            ask_player(notes, f"{c.get('name')} is a vampire: they drink sleeping dwarves' blood (dwarves die "
                              "drained, and the sheriff may convict the wrong one). Lock them away or give them "
                              "work away from the others")
        else:
            ask_player(notes, f"{c.get('name')} carries a {c.get('kind')} curse: they change at the full moon "
                              "and attack: keep them in a locked room on those nights, or away from the fort")


ORDINALS = ("", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth")


def garden_name(s: dict, memory) -> str:
    """The fort's name (letters only), then "Second", "Third"... for later ones."""
    raw = str(_d(s.get("fort")).get("name") or "")
    base = " ".join("".join(ch for ch in w if (ch.isascii() and ch.isalpha()) or ch == "'")
                    for w in raw.split()).strip()
    base = " ".join(base.split()[:3]) or "Founders"
    n = len(memory.gardens_built or [])
    # (0.103.20) a name the season's character decision chose
    chosen = _d(getattr(memory, "culture", None)).get("set_piece_name")
    if isinstance(chosen, str) and chosen and chosen not in (memory.gardens_built or []):
        return chosen[:40]
    return (base + (" " + ORDINALS[n] if 0 < n < len(ORDINALS) else ""))[:40]


SOCIAL_KINDS = {"tavern": ("INN_TAVERN", ("BeWithFriends", "DrinkAlcohol", "Socialize"), "tavern_badly_per"),
                "temple": ("TEMPLE", ("PrayOrMeditate",), "temple_badly_per")}


def social_shortfall(s: dict, cfg: dict) -> list:
    """(0.104.137) [(kind, why)] for taverns and temples too few for the dwarves
    who badly miss what they give: one for every `*_badly_per` of them (the
    worst of the needs counted), up to `social_halls_max`, once one stands."""
    nd = _d(_d(s.get("needs")).get("needs"))
    locs = _d(_d(s.get("locations")).get("count"))
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    out = []
    for kind, (where, needs, per_key) in SOCIAL_KINDS.items():
        have = int(locs.get(where) or 0)
        if have < 1:
            continue                                  # the first is the ladder's (and the urgent rules')
        badly = max([int(_d(nd.get(n)).get("badly") or 0) for n in needs] or [0])
        # (0.104.146) or every distracted dwarf, at a wider spacing: Teacheroar's
        # 93 distracted for want of prayer (40 badly) held at 2 temples, one of
        # them for all gods; 128 wanting friends (68 badly) at 3 taverns
        dist = max([int(_d(nd.get(n)).get("distracted") or 0) for n in needs] or [0])
        want = min(cfg["social_halls_max"],
                   max(1 + badly // cfg[per_key], 1 + dist // cfg["social_distracted_per"]))
        if (badly >= cfg["social_badly_share"] * cit or dist >= cfg["social_distracted_share"] * cit) and have < want:
            words = ", ".join(f"{n} {int(_d(nd.get(n)).get('distracted') or 0)} distracted "
                              f"({int(_d(nd.get(n)).get('badly') or 0)} badly)" for n in needs)
            out.append((kind, f"{have} {kind}(s) for {cit} dwarves and many badly miss what one gives ({words}): "
                              f"another {kind} ({want} wanted)"))
    return out


def prayer_uncovered(s: dict) -> tuple[int, dict] | None:
    """(0.104.146) The dwarves distracted for want of prayer whose god no temple
    here serves (one to that god, to a religion that has it, or to all gods),
    and those by god: (n, {god: n}). None when the bridge doesn't say what the
    temples are dedicated to (older than 0.104.146), or there is no temple."""
    temples = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict) and e.get("type") == "TEMPLE"]
    if not temples or not any(("any_deity" in e or "deity_hf" in e or "religion_deities" in e) for e in temples):
        return None
    if any(e.get("any_deity") for e in temples):
        return 0, {}
    served = {e.get("deity_hf") for e in temples} | {h for e in temples for h in _l(e.get("religion_deities"))}
    nd = _d(s.get("needs"))
    ids = _d(nd.get("deity_ids"))
    by = {g: int(v or 0) for g, v in _d(nd.get("deities")).items() if ids.get(g) not in served}
    return sum(by.values()), by


def dining_shortfall(s: dict, cfg: dict) -> dict | None:
    """(0.104.135) The fort's tables against its diners, once it has a dining
    hall: {have, want, tables, citizens} when under `dining_short_share` of
    what it wants, or None."""
    zones = _d(_d(s.get("buildings")).get("zones"))
    if not zones.get("DiningHall"):
        return None                        # the first hall is the ladder's
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    have = int(_d(_d(s.get("buildings")).get("other")).get("Table") or 0)
    want = math.ceil(cit / cfg["dwarves_per_table"])
    if cit < cfg["min_dwarves_for_dining"] or have >= cfg["dining_short_share"] * want:
        return None
    return {"have": have, "want": want, "citizens": cit, "tables": max(8, min(40, want - have))}


def hospital_shortfall(s: dict, traits: dict, cfg: dict) -> dict | None:
    """(0.104.121) The hospitals' beds against the wounded resting (on the
    Rest job: in a bed, or on the hospital's floor when it has none free;
    Teacheroar's 5-bed hospital zone, a meeting hall, held 106 of 107):
    {unbedded, have, want, beds, citizens}, or None."""
    locs = _d(_d(s.get("locations")).get("count"))
    if not locs.get("HOSPITAL"):
        return None                      # the first hospital is the ladder's (and the urgent rule's)
    h = _d(s.get("health"))
    cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    have = sum(int(_d(z).get("beds") or 0) for hosp in _l(h.get("hospital")) for z in _l(_d(hosp).get("zones")))
    if isinstance(h.get("resting"), int):
        resting = h["resting"]
    else:                                # an older bridge: the listed patients waiting for a treatment
        resting = sum(1 for p in _l(h.get("patients")) if isinstance(p, dict) and _l(p.get("needs")))
    unbedded = resting - have
    base = math.ceil(cit / 20 * factor(traits, "welfare")) + 2
    want = max(4, min(cfg["hospital_beds_max"], max(base, resting)))
    if unbedded < cfg["hospital_outside_min"] or have >= want:
        return None
    return {"unbedded": unbedded, "resting": resting, "have": have, "want": want, "citizens": cit,
            "beds": max(4, min(20, want - have))}

DIG_FIRST_KINDS = {"hospital", "tombs"}      # (0.104.128) levels dug before the rest


def _dig_stall_rule(s: dict, memory, cfg: dict, open_: list, proposals: list) -> None:
    """(0.104.110, the 38-year soak) Teacheroar's tomb level sat at 235 of 240
    tiles for three game years ("5 being dug") and a bedroom level at 0 of 89
    for one, and with only two building slots nothing new was started from
    y76. A level with no tile dug for dig_stall_days: its dig jobs let go of
    their workers (a dwarf who took one and then lay in the hospital held it);
    still nothing after dig_stall_furnish_days and 90%+ dug: furnished
    without the last tiles."""
    now = abs_tick(s)
    seen = _d(memory.dig_seen)
    memory.dig_seen = seen
    live = set()
    for p in open_:
        if p.get("phase") != "dig" or not isinstance(p.get("id"), int):
            continue
        dig = _d(p.get("dig"))
        dug, total = int(dig.get("dug") or 0), int(dig.get("total") or 0)
        if total <= 0:
            continue
        k = str(p["id"])
        live.add(k)
        rec = seen.get(k)
        if not isinstance(rec, dict) or rec.get("dug") != dug:
            seen[k] = {"dug": dug, "tick": now}
            if isinstance(rec, dict) and rec.get("raised_ok"):
                seen[k]["raised_ok"] = rec["raised_ok"]    # (0.104.128) raised once is enough
            continue
        days = (now - int(rec.get("tick") or now)) // TICKS_PER_DAY
        what = f"the {p.get('kind')} level (project {p['id']})"
        # (0.104.128) dug first: an urgent level, or one with nothing dug for
        # weeks while other digging takes the miners (Teacheroar: the new
        # hospital 0 of 175, a bedrooms level 0 of 89 for years, at priority 4
        # with 260 tiles waiting elsewhere)
        raised = rec.get("raised_ok")
        # (0.104.134) asked again a week on while still nothing is dug (its
        # old jobs renewed at the new priority)
        again = isinstance(raised, int) and dug == 0 and now - raised >= cfg["dig_raise_again_days"] * TICKS_PER_DAY
        if (dug < total and (not raised or again)      # (0.104.129: 0.104.128's "raised" marked held ones too)
                and (p.get("urgent") or p.get("kind") in DIG_FIRST_KINDS
                     or (dug == 0 and days >= cfg["dig_raise_days"]))):
            proposals.append(Proposal("dig_first", {"type": "prioritize_dig", "project_id": p["id"], "priority": 2},
                                      f"{what}: {dug} of {total} tiles dug"
                                      + (f", none for {days} days" if days else "")
                                      + ": dig it before the rest (priority 2)", 3))
            # (marked raised in planner.record, once the game took it: a
            # proposal held by the cycle's limits is asked again)
        jobs = "; ".join(str(w) for w in _l(dig.get("waiting"))[:3])
        if days >= cfg["dig_stall_furnish_days"] and dug >= 0.9 * total and dug < total:
            proposals.append(Proposal("project", {"type": "furnish_project", "project_id": p["id"], "stalled": True},
                                      f"{what}: {dug} of {total} tiles dug and none for {days} days"
                                      + (f" ({jobs})" if jobs else "") + ": furnish it without the last ones", 3))
        elif days >= cfg["dig_stall_days"] and int(dig.get("digging") or 0) > 0 and not rec.get("freed"):
            proposals.append(Proposal("dig_jobs", {"type": "free_dig_jobs", "project_id": p["id"]},
                                      f"{what}: no tile dug for {days} days though {dig.get('digging')} are "
                                      "taken" + (f" ({jobs})" if jobs else "") + ": let other miners take them", 3))
            rec["freed"] = now
    for k in list(seen):
        if k not in live:
            del seen[k]


def room_size(traits: dict) -> int:
    """Fort size trait -> bedroom size: small 2x2, normal 3x3, large 4x4."""
    size = traits.get("size", 0)
    return 2 if size <= -50 else 4 if size >= 50 else 3


# (0.105.29) the customs that place a level of a kind (masterplan.hint applies
# them); the layout ones are customs.LAYOUT. wide_ways and winding_ways bend
# every level's ways: they ride along with these, never call the hint alone.
PLACEMENT_CUSTOMS = {"bedrooms": ("cells",), "dining": ("deep_hall", "field_hall"), "tavern": ("market_gate",),
                     "barracks": ("gate_barracks",), "archery": ("gate_barracks",), "workshops": ("field_kitchens",)}


def apply_customs(action: dict, memory, traits: dict, profile: dict, citizens: int,
                  urgent: bool = False) -> dict | None:
    """(0.105.29) The fort's customs on a start_project: the master plan's hint
    (placement customs; returned, and set as action["plan"]), style.customs
    (layout customs) and action["customs"] (the journal's). The ladder calls it
    as it is; customs_pass with urgent=True for every other rule's level.
    urgent: the level keeps its own placement and gets nothing at all unless a
    custom concerns its kind; the hint is kept only when it applied a placement
    custom of that kind (else the rule's own placement stands)."""
    kind = action["kind"]
    lc = customs.layout_customs(traits, kind)
    place = [c for c in PLACEMENT_CUSTOMS.get(kind, ()) if customs.has(traits, c)] if urgent else None
    where = None
    if memory is not None and (not urgent or place):
        where = masterplan.hint(memory, kind, slot=action.get("set_piece"), traits=traits,
                                profile=profile, action=action, citizens=citizens)
        if urgent and not set(_l((where or {}).get("customs"))) & set(place):
            where = None
    if lc:
        if not isinstance(action.get("style"), dict):
            action["style"] = {}           # (as no style: plain, the bridge's defaults)
        action["style"]["customs"] = lc
    cs = sorted(set(lc) | set(_l((where or {}).get("customs"))))
    if cs:
        action["customs"] = cs
    if where:
        # the door rule follows the fort as it is now (the plan's own was set when it was drawn)
        where["doors"] = ("fortified" if traits.get("fortification", 0) >= 70
                          else "doored" if profile.get("entry_doors") else "open")
        action["plan"] = where                 # the master plan's district for it, tried first
    return where


def customs_pass(proposals: list, memory, traits: dict, citizens: int) -> None:
    """(0.105.29 customs fixes) The fort's customs on every start_project the
    rules proposed without them: the urgent levels of _project_rules and the
    workshop levels of bags, cloth, gems, bottleneck, kiln, glass, industry,
    needs_shops, well_parts, the fishery, moods and bowyers (13 proposers
    that skipped them: no ore_piles on 132 Deep mine workshop levels, no
    field_kitchens). Run once by plan() after every rule has proposed, as
    apply_customs(urgent=True): the hint only when a placement custom of the
    kind is on, kept only when it applied (else the rule's own placement
    stands), the layout customs always. The ladder's level (it has "plan" or
    "customs" from apply_customs already) is left as it is. Nothing at all
    changes for a fort with no custom on. The strategist's levels
    (review.py) get the layout customs only."""
    if not customs.active(traits):
        return
    profile = None
    for p in proposals:
        a = p.action
        if not isinstance(a, dict) or a.get("type") != "start_project" or not isinstance(a.get("kind"), str) \
                or "customs" in a or "plan" in a:
            continue
        if profile is None:
            profile = profile_from(traits, (memory.culture if memory is not None else None) or new_history())
        b = dict(a)
        if isinstance(b.get("style"), dict):
            b["style"] = dict(b["style"])      # (a rule's style dict may be shared)
        apply_customs(b, memory, traits, profile, citizens, urgent=True)
        if b != a:
            p.action = b


def _project_rules(s, traits, cfg, proposals, notes, can_use, memory) -> None:
    s.pop("_character_slot", None)          # (0.105.10) this plan's own (normalize may hand back the same dict)
    pr = s["projects"]
    open_ = [p for p in pr.get("open") or [] if isinstance(p, dict)]
    decorating = [p for p in pr.get("decorating") or [] if isinstance(p, dict)]
    history = memory.culture or new_history()
    profile = profile_from(traits, history)
    stone = pick_stone(s.get("stone_types") if isinstance(s.get("stone_types"), list) else [],
                       profile["palette"])
    one_stone = has_rule(memory.culture, "one_stone")                  # (0.103.18) One Stone: its commonest rock
    if one_stone and isinstance(s.get("stone_types"), list) and s["stone_types"] and isinstance(s["stone_types"][0], dict):
        stone = s["stone_types"][0]

    # Move projects along. The game says what's next for each one; older
    # bridges don't, so the phases are also read directly.
    for p in open_ + decorating:
        dig, fur = p.get("dig") or {}, p.get("furnish") or {}
        step = p.get("next")
        if step is None and "next" not in p:
            if p.get("phase") == "dig" and dig.get("total") and dig.get("dug") == dig.get("total"):
                step = "furnish"
            elif p.get("phase") == "furnish" and fur and fur.get("done", 0) == fur.get("placed", 0):
                step = "finish"
        what = f"{p.get('kind')} level #{p.get('id')}"
        if step == "furnish":
            if s["tools"].get("buildingplan") is True:
                left = f" ({dig['stuck']} spots the game cancelled stay rock)" if dig.get("stuck") else ""
                proposals.append(Proposal("project", {"type": "furnish_project", "project_id": p["id"]},
                                          f"{what} is dug out: furnish it{left}", 3))
            else:
                notes.append(f"{what} is dug, waiting for buildingplan to be on")
        elif step == "finish":
            # Includes levels with nothing to build (storage: only stockpiles).
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"]},
                                      f"{what} is fully built", 3))
        elif step == "cancel":
            action = {"type": "cancel_project", "project_id": p["id"]}
            memorial = (p.get("summary") or {}).get("memorial")
            if memorial:
                action["memorial"] = memorial      # owed again; built elsewhere
            proposals.append(Proposal("project", action,
                                      f"{what}: {dig.get('stuck', 0)} of {dig.get('total', 0)} tiles were "
                                      "cancelled by the game (e.g. damp stone); give up on this spot", 3))
        elif step == "engrave":
            proposals.append(Proposal("project", {"type": "engrave_project", "project_id": p["id"]},
                                      f"{what} is smoothed: engrave its halls", 3))
        elif step != "furnish" and p.get("phase") == "dig" and (dig.get("stuck") or dig.get("marked")):
            if dig.get("marked"):
                ask_player(notes, f"{what}: {dig['marked']} tiles are designated in marker (blueprint) mode, "
                             "so dwarves won't dig them; check Quickfort's marker settings")
            if dig.get("stuck"):
                # (0.100.1, overnight run) nothing left being dug and the rest no
                # longer designated: it never finishes, and it held a building
                # slot (with a stuck well, both slots) for five game years while
                # it waited for the player. After STUCK_PROJECT_DAYS it's given up.
                started = stamp_tick(p.get("started"))
                age = (abs_tick(s) - started) // TICKS_PER_DAY if started is not None else None
                if not dig.get("digging") and not dig.get("marked") and age is not None \
                        and age >= cfg["stuck_project_days"]:
                    proposals.append(Proposal("project", {"type": "cancel_project", "project_id": p["id"]},
                                              f"{what}: {dig['stuck']} tiles are no longer designated and nothing "
                                              f"is being dug ({age} days since it started): give it up, so the "
                                              "slot goes to the next level", 3))
                else:
                    ask_player(notes, f"{what}: {dig['stuck']} tiles are no longer designated, so it won't "
                                 "finish (cancel it, or re-designate them)")

    # (0.105.30, construction 3.3) a finished hall's own step `floor`: block
    # floors over its soil (soil can't be smoothed), once per project
    try:
        _soil_floor_rule(s, traits, cfg, proposals, notes, memory)
    except Exception as e:  # noqa: BLE001  (an odd report value: the project steps go on)
        notes.append(f"rule _soil_floor_rule failed ({type(e).__name__}: {str(e)[:120]}); the others ran")
    _dig_stall_rule(s, memory, cfg, open_, proposals)

    # (0.104.12) projects that hold a building slot for good: a dig that has
    # crept (under half dug in slow_dig_days: Enxah's cavern well, 2 of 24
    # tiles in six game years) is given up; a level furnished but for statues
    # there's no stone for is finished without them (they stay planned)
    now_ = abs_tick(s)
    for p in open_:
        started = stamp_tick(p.get("started"))
        if started is None:
            continue
        age = (now_ - started) // TICKS_PER_DAY
        dig = _d(p.get("dig"))
        what = f"the {p.get('kind')} level (project {p.get('id')})"
        # (0.105.22) or nothing dug at all in unreached_dig_days: no dwarf gets
        # to it (B's tomb level, 11 times on one stair column, 336 days each,
        # while 41 ghosts rose); its spot is kept off-limits a while (`unreached`)
        none_dug = (int(dig.get("dug") or 0) == 0 and age >= cfg["unreached_dig_days"]
                    and int(dig.get("total") or 0) > 0)
        if (p.get("phase") == "dig" and int(dig.get("total") or 0) > 0
                and ((age >= cfg["slow_dig_days"] and int(dig.get("dug") or 0) * 2 < int(dig.get("total") or 0))
                     or none_dug)):
            # (0.105.26) `unreached` (its spot kept off-limits) only where nothing
            # was dug at all: a slow dig was reached, and a cavern well given up
            # as slow stays revivable (lua: revive_cavern_well skips unreached)
            action = {"type": "cancel_project", "project_id": p["id"]}
            if none_dug:
                action["unreached"] = True
            if p.get("kind") == "well" and _d(p.get("summary")).get("cavern"):
                action["cavern_well"] = True
            proposals.append(Proposal("project", action,
                                      f"{what}: {dig.get('dug') or 0} of {dig.get('total')} tiles dug in {age} days: "
                                      "give it up, so its building slot goes to what waits"
                                      + (" (and not that spot again for a while)" if none_dug else ""), 4))
        fw = _d(_d(p.get("furnish")).get("waiting"))
        # (0.104.33) or waits so long for them whatever the stone (Enxah's
        # storage level: 197 days for 1 statue, 199 usable boulders, the
        # mason's bench jammed) while another level is refused for its slot
        fdays = int(_d(p.get("furnish")).get("days") or 0)
        if (p.get("phase") == "furnish" and fw and set(fw) <= {"Statue"}
                and fdays >= cfg["statue_wait_days"]
                and (stone_short(s, cfg["stone_low"]) or fdays >= cfg["statue_wait_days_any"])):
            why = ("there's no stone to carve" if stone_short(s, cfg["stone_low"])
                   else f"they haven't come in {fdays} days")
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"], "decor_only": True},
                                      f"{what} waits only for {fw.get('Statue')} statue(s) and {why}: "
                                      "finish it (the statues stay planned) and free its slot", 4))
        # (0.104.141) furnished but for buildings placed and never finished
        # (Teacheroar's 20-bed hospital: 30 of 31 done, nothing missing, 134
        # days) while its slot holds a petition's guildhall back: finish it
        # (DF goes on building what is placed)
        fur = _d(p.get("furnish"))
        if (p.get("phase") == "furnish" and not fw and int(fur.get("placed") or 0) > 0
                and int(fur.get("done") or 0) < int(fur.get("placed") or 0)
                and fdays >= cfg["furnish_stalled_days"]):
            left_ = int(fur.get("placed") or 0) - int(fur.get("done") or 0)
            proposals.append(Proposal("project", {"type": "finish_project", "project_id": p["id"], "stalled": True},
                                      f"{what} has all its furniture and {left_} building(s) placed but not built "
                                      f"in {fdays} days: finish it (DF still builds them) and free its slot", 4))

    # Furniture the projects are waiting for: order what isn't already queued,
    # in the fort's materials: its signature stone, a stone per kind ("by
    # purpose"), or wood where wood will do (while the fort has wood to spare).
    if can_use("orders"):
        stones = s.get("stone_types") if isinstance(s.get("stone_types"), list) else []
        citizens = max(1, s["dwarves"].get("total", 0))
        wood_spare = (s["stocks"].get("wood", 0) or 0) - citizens * cfg["wood_per_dwarf"]
        waiting: dict[str, int] = {}
        for p in open_:
            for kind, n in ((p.get("furnish") or {}).get("waiting") or {}).items():
                waiting[kind] = waiting.get(kind, 0) + int(n or 0)
        for kind, n in sorted(waiting.items()):
            if kind == "Chain":
                _restraint_order(s, n, cfg, proposals, notes)
                continue
            recipe = FURNITURE_RECIPES.get(kind)
            wooden = WOODEN_FURNITURE.get(recipe)
            metal_r = METAL_FURNITURE.get(recipe)
            # (0.104.141) a stone order already made, but too slow for what waits
            # (Teacheroar in crisis: 51 tables and 41 chairs for the dining hall
            # and tavern, 88-93 days, one order each on 5 busy Masons' workshops,
            # 3 carpenters' and 659 logs idle): part of it in wood beside it
            if (recipe and wooden and n > 0 and queued(s, {wooden} | ({metal_r} if metal_r else set())) == 0
                    and _has_shop(s["buildings"], "Carpenters")):
                stone_left = queued(s, {recipe})
                masons = max(1, int(_d(s["buildings"].get("workshops")).get("Masons") or 0))
                part = min(stone_left // 2, n, int(wood_spare) - 2, cfg["max_order"])
                if (stone_left and stone_left / masons >= cfg["furniture_parallel_backlog"]
                        and part >= cfg["furniture_parallel_min"]):
                    proposals.append(Proposal("furniture", {"type": "work_order", "recipe": wooden, "amount": part},
                                              f"building projects are waiting for {n} {kind.lower()}(s) and "
                                              f"{stone_left} in stone wait on {masons} Masons' workshop(s): "
                                              f"{part} in wood beside them at the carpenters'", 3, True))
                    continue
            if recipe and n > 0 and queued(s, {recipe} | ({wooden} if wooden else set())
                                                | ({metal_r} if metal_r else set())) == 0:
                amount = min(n, cfg["max_order"])
                why = f"building projects are waiting for {n} {kind.lower()}(s)"
                metal = spare_metal(s, cfg, amount) if metal_r and (
                    stone_short(s, max(amount, cfg["stone_low"]))
                    or traits.get("craftsmanship", 0) >= 50 or traits.get("grandeur", 0) >= 50
                    # (0.103.11) Forge-born: metal first
                    or (memory is not None and has_rule(memory.culture, "metal_furnish"))) else None
                if metal:
                    action = {"type": "work_order", "recipe": metal_r, "amount": amount, "material": f"INORGANIC:{metal}"}
                    why += f", in {metal.lower().replace('_', ' ')} at the forge (bars the soldiers don't need)"
                elif profile["palette"] == "wood" and wooden and wood_spare >= amount:
                    action = {"type": "work_order", "recipe": wooden, "amount": amount}
                    why += ", in wood (the fort builds in wood where it will do)"
                elif stone_short(s, max(amount, cfg["stone_low"])) and wooden and wood_spare >= amount:
                    action = {"type": "work_order", "recipe": wooden, "amount": amount}
                    why += ", in wood (no stone the masons may use)"
                elif stone_short(s, max(amount, cfg["stone_low"])) and wooden and wood_spare >= 5:
                    # (0.104.138) as many as the wood covers: Teacheroar's 27 coffins
                    # waited with ~20 logs to spare and nothing was ordered at all
                    part = int(wood_spare) - 2
                    action = {"type": "work_order", "recipe": wooden, "amount": part}
                    why += f", {part} of them in wood for now (no stone the masons may use; wood for {part})"
                elif stone_short(s, max(amount, cfg["stone_low"])) and recipe.startswith("stone_"):
                    notes.append(f"{why}: no stone the masons may use" + ("" if wooden else " and no wooden kind"))
                    continue
                else:
                    action = {"type": "work_order", "recipe": recipe, "amount": amount}
                    kstone = (stone_for(stones, profile["palette"], kind)
                              if profile["palette"] == "purpose" and not one_stone else stone)
                    if kstone and recipe.startswith("stone_"):
                        action["material"] = kstone["token"]
                        why += (f", in {kstone.get('name')} (each kind of furniture in its own stone)"
                                if profile["palette"] == "purpose"
                                else f", in the fort's {kstone.get('name') or 'signature'} stone")
                proposals.append(Proposal("furniture", action, why, 3, True))

    # One new level at a time, most urgent need first.
    if traits.get("surface", 0) >= 50:
        notes.append("Surface ambition: the AI builds a walled, roofed keep round the way in (or on open "
                     "ground near the fields); new levels still go underground")
    # (0.100.1, overnight run) a still, a kitchen and a carpenter's workshop
    # before anything else, with a slot of their own (as a farm level has):
    # a fresh fort built a mason's, a mechanic's and the metal works first
    # (for a well and for ore), then both slots stuck, and it never brewed,
    # cooked or made a bed in five years.
    if can_use("stocks") and "buildings" not in s["_errors"]:
        have = {**_d(s["buildings"].get("workshops")), **_d(s["buildings"].get("furnaces"))}
        coming = set()
        for p in open_:
            if p.get("kind") == "workshops":
                coming |= set(_l((p.get("summary") or {}).get("workshops")))
                coming |= set(_d(p.get("furniture")).keys())
        need = [w for w in SURVIVAL_SHOPS if not have.get(w) and w not in coming]
        if need and len(open_) < (pr.get("max_open") or 2) + 1:
            extra = [w for w in BASIC_WORKSHOPS if w not in need and not have.get(w) and w not in coming]
            proposals.append(Proposal("build", {"type": "start_project", "kind": "workshops",
                                                "shops": need + extra, "urgent": True},
                                      f"no {', '.join(need)}: the fort can't brew, cook or make beds, doors and "
                                      "barrels without them; dig them first", 1))
    # (0.100.2, second overnight run) the manager works only in an office: with
    # none, the work orders are never taken up (a fresh fort's brewing, meals,
    # beds and barrels all waited, workshops standing). An office for the
    # manager is a need, not a luxury: one suite, with a slot of its own.
    if can_use("stocks") and "buildings" not in s["_errors"] and manager_needs_office(s) \
            and not any(p.get("kind") == "suites" for p in open_) \
            and len(open_) < (pr.get("max_open") or 2) + 1:
        n_suites = max(1, suites_short(s)) if "office" in noble_room_kinds(traits, memory) else 1
        # (urgent: the builder's extra slot, as for the survival workshops; it
        # holds the open-project limit itself and refused the suite at 2)
        proposals.append(Proposal("build", {"type": "start_project", "kind": "suites", "suites": n_suites,
                                            "urgent": True},
                                  "the manager has no office, and a manager takes up work orders only in one: "
                                  f"dig {'a suite' if n_suites == 1 else f'{n_suites} suites'} (a bedroom and an "
                                  "office each)", 1))
    # (0.104.135, 12k) dining by tables, not halls: Teacheroar had one dining
    # hall and 19 tables for 227 dwarves (a bad thought at every meal eaten
    # without one, in a fort 62% miserable or very unhappy); a second hall
    # came only as the great hall set piece, in good times
    if can_use("stocks") and "buildings" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "dining" for p in open_):
        dn = dining_shortfall(s, cfg)
        if dn and player_rules(s)["levels"].get("dining", True):
            proposals.append(Proposal("build", {"type": "start_project", "kind": "dining", "tables": dn["tables"],
                                                "urgent": True},
                                      f"{dn['have']} tables for {dn['citizens']} dwarves (the fort wants {dn['want']}; "
                                      f"a meal without one is a bad thought): another dining hall with {dn['tables']} tables", 2))
    # (0.104.137, 12k) taverns and temples by the dwarves who badly miss what
    # they give, not by whether one stands (Teacheroar: 2 taverns and 2
    # temples for 221 dwarves; 85 badly missing friends, 56 drink, 63 prayer)
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2:
        for kind, cap in social_shortfall(s, cfg):
            if any(p.get("kind") == kind for p in open_) or not player_rules(s)["levels"].get(kind, True):
                continue
            action = {"type": "start_project", "kind": kind, "urgent": True}
            if kind == "tavern":
                action["tables"] = 20
            else:
                # (0.105.23) the bridge knows "shrine" and "grand" only: this temple
                # went without a size and was refused 83 times (fort E, 5 Nov)
                action["size"] = temple_size(traits)
            proposals.append(Proposal("build", action, cap, 2))
            break                                   # one a cycle
    # (0.104.146) a temple to all gods while many pray to gods no temple here
    # serves (Teacheroar: 2 temples, 9 gods prayed to, 93 distracted for want
    # of prayer; more temples by count never came, the count of the badly
    # held at 40 for 2 temples)
    pu = prayer_uncovered(s)
    if (pu and pu[0] >= max(cfg["temple_uncovered_min"], round(cfg["temple_uncovered_share"] * int(_d(s.get("dwarves")).get("total") or 0)))
            and can_use("stocks") and "buildings" not in s["_errors"]
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "temple" for p in open_)
            and player_rules(s)["levels"].get("temple", True)):
        gods = ", ".join(f"{g} {n}" for g, n in sorted(pu[1].items(), key=lambda kv: -kv[1])[:4])
        proposals.append(Proposal("build", {"type": "start_project", "kind": "temple", "size": "shrine",
                                            "urgent": True},
                                  f"{pu[0]} dwarves are distracted for want of prayer to gods no temple here serves "
                                  f"({gods}): a temple to all gods", 2))
    # (0.104.121) a hospital too small for the fort: Teacheroar's stop-gap of
    # 5 beds (built at 54 dwarves) served 296, 107 on the Rest job, 124
    # patients and 112 infected wounds; "another hospital" was counted by halls (one per 150
    # dwarves) and only in good times. Counted by beds against the wounded
    # resting, in bad times too (a second hospital brings 4 more posts), with a slot of its own.
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and not any(p.get("kind") == "hospital" for p in open_):
        hp = hospital_shortfall(s, traits, cfg)
        if hp and player_rules(s)["levels"].get("hospital", True):
            proposals.append(Proposal("build", {"type": "start_project", "kind": "hospital", "beds": hp["beds"],
                                                "urgent": True},
                                      f"{hp['resting']} wounded dwarves resting and the hospitals have "
                                      f"{hp['have']} beds for {hp['citizens']} dwarves (the fort wants {hp['want']}): "
                                      f"another hospital with {hp['beds']} beds", 1))
    # (0.103.8) dwarves waiting for care with no hospital: a hospital with a
    # slot of its own (Enxah: the chief medical dwarf waited 252 days, 4
    # infected wounds, while a tomb level and a workshops level held both slots)
    if can_use("stocks") and "buildings" not in s["_errors"] and "locations" not in s["_errors"] \
            and len(open_) < (pr.get("max_open") or 2) + 2 and len(open_) >= (pr.get("max_open") or 2):
        waiting = care_waiting(s)
        cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
        locs = _d(_d(s.get("locations")).get("count"))
        if (waiting >= cfg["urgent_hospital_waiting"] and cit >= cfg["min_dwarves_for_small_hospital"]
                and player_rules(s)["levels"].get("hospital", True) and not locs.get("HOSPITAL")
                and not any(p.get("kind") == "hospital" for p in open_)):
            beds = max(4, min(20, math.ceil(cit / 20 * factor(traits, "welfare")) + 2))
            proposals.append(Proposal("build", {"type": "start_project", "kind": "hospital", "beds": beds,
                                                "urgent": True},
                                      f"{waiting} dwarves wait for care and there is no hospital: build one with "
                                      f"{beds} beds now, ahead of the levels under way", 1))
        # (0.103.12) most of the fort longing to pray with only the stop-gap
        # temple over the dining hall: a shrine with a slot of its own (Enxah,
        # 49 dwarves: 53 prayers unmet, 13 miserable, every slot on bedrooms,
        # a well and tombs)
        lc = _d(_d(s.get("locations")).get("count"))
        pray = unmet(s, "PrayOrMeditate")
        share = cfg["urgent_temple_share"] / (2 if memory is not None and has_rule(memory.culture, "omens") else 1)
        if (pray >= max(cfg["needs_build_at"], math.ceil(cit * share))      # (0.103.17) Superstitious: a quarter
                and player_rules(s)["levels"].get("temple", True) and player_rules(s)["fort_goal"] != "maintain"
                and not _real_locations(lc, "TEMPLE", memory, _l(_d(s.get("locations")).get("list")))
                and not any(p.get("kind") == "temple" for p in open_)
                and not any(x.action.get("kind") == "hospital" and x.action.get("urgent") for x in proposals)):
            proposals.append(Proposal("build", {"type": "start_project", "kind": "temple", "size": "shrine",
                                                "urgent": True},
                                      f"{min(pray, cit)} dwarves are distracted for want of somewhere to pray and the fort "
                                      "has only the dining hall for it: dig a shrine now, ahead of the levels under way", 1))
        # (0.104.12) the dead unburied (ghosts, or many bodies: seeing them
        # stresses the living) with both slots taken: a tomb level of its own
        # slot. It was looked at only after the "slots full" return below, so
        # it never came when it was needed (Enxah y60: 35 unburied, 4 ghosts,
        # 7 free tombs, the slots on a stuck well and suites)
        dead = _d(s.get("dead"))
        if (player_rules(s)["levels"].get("tombs", True)
                and ((dead.get("ghosts") or 0) > 0 or (dead.get("unburied") or 0) >= cfg["urgent_unburied"])
                and not any(p.get("kind") == "tombs" for p in open_)
                and tombs_short(s, cit, cfg, memory) > 0
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple") for x in proposals)):
            short = tombs_short(s, cit, cfg, memory) + (dead.get("ghosts") or 0)
            coffins = max(4, min(30, short * 2))
            proposals.append(Proposal("tombs_ghosts", {"type": "start_project", "kind": "tombs", "coffins": coffins,
                                                       "urgent": True, "style": layout_style(profile)},
                                      f"{dead.get('unburied') or 0} dead unburied, {dead.get('ghosts') or 0} ghost(s) and "
                                      f"{dead.get('free_tombs', 0)} free tombs: dig a tomb level with {coffins} coffins "
                                      "now, ahead of the levels under way", 2))
        # (0.104.31) tantrums are crimes: with a sheriff or captain and no jail
        # the punishment is a beating, and the beaten fill the hospital (Enxah:
        # one bone carver's tantrums 194 times in the log, 18 abed). A jail
        # with an urgent slot of its own while tantrums come thick
        tn = tantrums_recent(s, memory)
        jp = jail_plan(traits, cfg, cit)
        if (tn >= cfg["urgent_jail_tantrums"] and jp and justice_held(s)
                and player_rules(s)["levels"].get("jail", True)
                and _d(_d(s.get("buildings")).get("zones")).get("Dungeon", 0) == 0
                and not any(p.get("kind") == "jail" for p in open_)
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple", "tombs")
                            for x in proposals)):
            proposals.append(Proposal("jail_urgent", {"type": "start_project", "kind": "jail", "cells": jp["cells"],
                                                      "urgent": True},
                                      f"{tn} tantrums in 28 days and no jail: the guard beats the offenders and the beaten "
                                      f"fill the hospital: dig a jail with {jp['cells']} cells now", 2))
        # (0.104.35) a third of the fort badly wanting company with only the
        # stop-gap tavern over the dining hall: a proper tavern with a slot of
        # its own (Enxah, spring y64: 38 of 71 badly, 56 distracted, tantrums
        # and their beatings putting 27 to bed; the ladder's tavern never got
        # a slot behind tombs, storage and the jail)
        friends = int(_d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends")).get("badly") or 0)
        if (friends >= max(cfg["needs_build_at"], math.ceil(cit * cfg["urgent_tavern_share"]))
                and player_rules(s)["levels"].get("tavern", True) and player_rules(s)["fort_goal"] != "maintain"
                and not _real_locations(lc, "INN_TAVERN", memory, _l(_d(s.get("locations")).get("list")))
                and not any(p.get("kind") == "tavern" for p in open_)
                and not any(x.action.get("urgent") and x.action.get("kind") in ("hospital", "temple", "tombs", "jail")
                            for x in proposals)):
            tables = max(4, min(20, math.ceil(cit / 10 * tavern_factor(traits))))
            proposals.append(Proposal("tavern_urgent", {"type": "start_project", "kind": "tavern", "tables": tables,
                                                        "urgent": True},
                                      f"{friends} dwarves badly want time with friends and the fort has only the dining "
                                      f"hall for a tavern: dig a tavern with {tables} tables now, ahead of the levels "
                                      "under way", 2))
    if len(open_) >= (pr.get("max_open") or 2) or not can_use("stocks") or "buildings" in s["_errors"]:
        return
    kinds_open = {p.get("kind") for p in open_}
    lb = _d(s.get("labor"))
    if "dig" in lb and lb.get("dig", 0) > max(1, lb.get("miners") or 0) * cfg["dig_backlog_per_miner"]:
        notes.append(f"no new level yet: {lb['dig']} tile(s) wait to be dug by {lb.get('miners') or 0} miner(s)")
        return
    b = s["buildings"]
    other, zones, shops = b.get("other") or {}, b.get("zones") or {}, b.get("workshops") or {}
    loc = s.get("locations") if isinstance(s.get("locations"), dict) else {}
    locations = loc.get("count") if isinstance(loc.get("count"), dict) else {}
    citizens = max(1, s["dwarves"].get("total", 0))
    action, reason = None, ""
    allow = dict(player_rules(s)["levels"])
    if mining_plan(traits, cfg)["need_only"]:
        # (0.96) Mining -100: only the levels the fort needs (was: none at all)
        for kind in MINING_NEED_ONLY:
            if allow.get(kind, True):
                allow[kind] = False
        notes.append("Mining -100: only the levels the fort needs (no library, archery, garden, barracks, "
                     "temple or jail level)")
    # kinds you've turned down wait (or are left to you); the next kind gets its turn
    held = held_levels(memory, abs_tick(s)) if memory is not None else {}
    if memory is not None:
        for kind, why in phases.held_kinds(memory, abs_tick(s)).items():   # the fort's phase of life
            held.setdefault(kind, why)
    for kind, why in held.items():
        if allow.get(kind, True):        # (a kind already switched off in the Rules tab says nothing)
            allow[kind] = False
            notes.append(why)

    young = young_fort(s, cfg)
    beds = other.get("Bed", 0)
    # Beds of levels still being dug; once furnishing starts, the (planned) beds
    # are buildings and already in the bed count.
    planned_beds = sum((p.get("summary") or {}).get("beds", 0) for p in open_
                       if p.get("kind") == "bedrooms" and p.get("phase") == "dig")
    goal = player_rules(s)["fort_goal"]
    if goal == "maintain":
        want_beds = citizens + cfg["maintain_spare_beds"]
    else:
        want_beds = citizens + max(cfg["min_spare_beds"], math.ceil(citizens * cfg["spare_beds_share"]))
        target = growth_target(s, cfg)
        if target > citizens and not young:   # room for the migrants the fort is growing toward
            want_beds = max(want_beds, min(target, citizens + cfg["beds_ahead"]))
        if memory is not None and has_rule(memory.culture, "rooms_ahead"):
            # (0.103.6) Cradle-hold: a room ready for every child, and some
            want_beds += int(_d(s.get("dwarves")).get("children") or 0) + cfg["min_spare_beds"]
    fresh_shops = not any(shops.get(w) for w in BASIC_WORKSHOPS) and beds == 0   # (a new fort: nothing built yet)
    if fresh_shops and "workshops" not in kinds_open:
        # a new fort: workshops first (beds, tables and doors all come from them)
        action = {"type": "start_project", "kind": "workshops", "shops": list(BASIC_WORKSHOPS)}
        reason = "a new fort with no workshops: dig the basic ones first (the furniture comes from them)"
    elif fresh_shops and b.get("stockpiles", 0) == 0 and "storage" not in kinds_open:
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": BASIC_STOCKPILES, "room_size": 5 if small else 7}
        reason = "a new fort with no stockpiles: dig a storage level for the wagon's goods"
    elif (young and _d(s.get("labor")).get("fish_water") and not shops.get("Fishery")
          and "workshops" not in kinds_open):
        # fish are caught raw: a fishery cleans them for the kitchen
        action = {"type": "start_project", "kind": "workshops", "shops": ["Fishery", "Butchers"]}
        reason = "water to fish in and no fishery: dig one (with a butcher's shop) so the catch can be eaten"
    elif beds + planned_beds < want_beds and "bedrooms" not in kinds_open:
        rooms = min(32, want_beds - beds - planned_beds)
        size = room_size(traits)
        if memory is not None and has_rule(memory.culture, "small_rooms"):
            size = max(2, size - 1)                  # Warren: small rooms
        if young:
            size = 2                                 # a young fort: a bed and a door, quick to dig
        action = {"type": "start_project", "kind": "bedrooms", "rooms": rooms, "room_size": size}
        reason = f"{beds} beds for {citizens} dwarves: dig {rooms} bedrooms"
        if memory is not None and has_rule(memory.culture, "dormitories"):
            # (0.103.11) Communal: one hall of beds, a chest by each
            rooms = max(4, min(20, rooms))
            action = {"type": "start_project", "kind": "bedrooms", "rooms": rooms, "room_size": 2,
                      "dormitory": True}
            reason = f"{beds} beds for {citizens} dwarves: dig a dormitory of {rooms} beds (a communal fort)"
    elif (zones.get("DiningHall", 0) == 0 and citizens >= cfg["min_dwarves_for_dining"]
          and "dining" not in kinds_open):
        tables = max(4, min(90, math.ceil(citizens / cfg["dwarves_per_table"])))
        action = {"type": "start_project", "kind": "dining", "tables": tables}
        reason = f"no dining hall for {citizens} dwarves: dig one with {tables} tables"
    elif "workshops" not in kinds_open and [w for w in BASIC_WORKSHOPS if not shops.get(w)]:
        missing = [w for w in BASIC_WORKSHOPS if not shops.get(w)]
        action = {"type": "start_project", "kind": "workshops", "shops": missing}
        reason = "missing basic workshops: " + ", ".join(missing)
    elif (allow["tombs"] and tombs_short(s, citizens, cfg, memory) > 0 and "tombs" not in kinds_open
          # (0.104.37) not beside the urgent tomb level of this same cycle
          # (Enxah, 02:13: both went through, two tomb levels at once)
          and not any(x.action.get("kind") == "tombs" and x.action.get("urgent") for x in proposals)):
        short = tombs_short(s, citizens, cfg, memory)
        coffins = max(4, min(30, short * 2))
        action = {"type": "start_project", "kind": "tombs", "coffins": coffins}
        reason = (f"{_d(s.get('dead')).get('free_tombs', 0)} free tombs"
                  + (f" and {_d(s.get('dead')).get('unburied')} bodies to bury" if _d(s.get('dead')).get('unburied') else "")
                  + f": dig a tomb level with {coffins} coffins (unburied dead come back as ghosts)")
    elif b.get("stockpiles", 0) == 0 and "storage" not in kinds_open:
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": BASIC_STOCKPILES, "room_size": 5 if small else 7}
        reason = "no stockpiles: dig a storage level"
    elif ("storage" not in kinds_open and full_stores(s, cfg)
          # (0.104.38) one storage level for full piles a season and a half
          # at most: Enxah's overnight run dug 35 in six game years, the
          # crafts and quarried stone filling each as it was finished
          and not (memory is not None and isinstance(memory.storage_started, int)
                   and 0 <= abs_tick(s) - memory.storage_started < cfg["storage_gap_days"] * TICKS_PER_DAY)):
        kinds = full_stores(s, cfg)
        small = memory is not None and (has_rule(memory.culture, "small_rooms") or has_rule(memory.culture, "small_storage"))
        action = {"type": "start_project", "kind": "storage", "piles": kinds[:4], "room_size": 5 if small else 7}
        st = _d(_d(s.get("logistics")).get("storage"))
        reason = ("stockpiles full, things lying about: " + "; ".join(
            f"{k.replace('_', ' ')} {_d(st.get(k)).get('used')}/{_d(st.get(k)).get('tiles')} tiles used, "
            f"{_d(st.get(k)).get('loose')} loose" for k in kinds[:4]) + ": dig more storage for them")
    elif (allow["hospital"] and "hospital" not in kinds_open
          and (citizens >= cfg["min_dwarves_for_hospital"]
               or (not young and citizens >= cfg["min_dwarves_for_small_hospital"] and _office_held(s, "CHIEF_MEDICAL_DWARF"))
               # (0.102.3) dwarves waiting for care, young fort or not (Enxah:
               # 4 infected wounds, no hospital, the doctor himself a patient)
               or (citizens >= cfg["min_dwarves_for_small_hospital"] and care_waiting(s) >= 2))
          and "locations" not in s["_errors"] and not locations.get("HOSPITAL")):
        beds = max(4, min(20, math.ceil(citizens / 20 * factor(traits, "welfare")) + 2))
        action = {"type": "start_project", "kind": "hospital", "beds": beds}
        reason = f"no hospital for {citizens} dwarves: build one with {beds} beds"
    # (0.98) The weighted ladder: once the levels the fort needs to live are
    # dealt with (above: workshops, storage, bedrooms, dining, tombs,
    # hospital), every optional level whose time has come is a candidate,
    # scored by its old place in the ladder, the temperament and the need
    # (ladder_score); the best goes first. Neutral sliders keep the old order.
    cands: list = []
    # (0.105.10, 14.1 step 3) the fort's own levels are weighed every cycle,
    # not only once every need is met: one building slot is theirs
    need_action, need_reason = action, reason
    action, reason = None, ""
    if True:
        if (allow["jail"] and not young and jail_plan(traits, cfg, citizens)
              and citizens >= jail_plan(traits, cfg, citizens)["min_dwarves"] and justice_held(s)
              and zones.get("Dungeon", 0) == 0 and "jail" not in kinds_open):
            cells = jail_plan(traits, cfg, citizens)["cells"]
            action = {"type": "start_project", "kind": "jail", "cells": cells}
            reason = (f"the fort has a sheriff and no jail: dig {cells} cells with restraints (convicts are "
                      "chained there; without a jail, justice is beatings or nothing)"
                      + (f"; Justice {int(traits.get('justice', 0)):+d}" if traits.get("justice") else ""))
            cands.append((action, reason))
            action, reason = None, ""
        if ("suites" not in kinds_open and suites_short(s) > 0 and not manager_needs_office(s)
              and (not young or traits.get("deference", 0) >= 50
                   or (memory is not None and has_rule(memory.culture, "noble_pride")))
              and "office" in noble_room_kinds(traits, memory)):
            n = suites_short(s)
            action = {"type": "start_project", "kind": "suites", "suites": n}
            reason = (f"{n} noble{'s' if n > 1 else ''} without the rooms their office asks for and none free: "
                      f"dig {n} suite{'s' if n > 1 else ''} (a bedroom and an office each)")
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["tavern"] and (citizens >= cfg["min_dwarves_for_tavern"]
                                   or (citizens >= 8 and unmet(s, *SOCIAL_NEEDS) >= cfg["needs_build_at"]))
              and "tavern" not in kinds_open
              and "locations" not in s["_errors"] and not _real_locations(locations, "INN_TAVERN", memory, _l(loc.get("list")))):
            tables = max(4, min(20, math.ceil(citizens / 10 * tavern_factor(traits))))
            action = {"type": "start_project", "kind": "tavern", "tables": tables}
            reason = f"no tavern for {citizens} dwarves (they need to socialise and drink together): build one" + (
                f"; {unmet(s, *SOCIAL_NEEDS)} are distracted for want of company or a drink"
                if unmet(s, *SOCIAL_NEEDS) else "")
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["library"] and goal != "maintain"
              and (citizens >= cfg["min_dwarves_for_library"]
                   or (citizens >= 8 and unmet(s, *LEARNING_NEEDS) >= cfg["needs_build_at"]))
              and "library" not in kinds_open
              and "locations" not in s["_errors"]
              and (not locations.get("LIBRARY")
                   # (0.103.2) a Scholars' Hold of 40+ raises a second
                   or (memory is not None and has_rule(memory.culture, "library_first")
                       and citizens >= 40 and int(locations.get("LIBRARY") or 0) < 2))):
            action = {"type": "start_project", "kind": "library", "bookcases": 6}
            reason = f"no library for {citizens} dwarves (scholars and curious dwarves need one): build one"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["barracks"] and (traits.get("militarism", 0) >= 50 or _d(s.get("military")).get("soldiers"))
              and not zones.get("Barracks")
              and "barracks" not in kinds_open):
            beds = max(4, min(20, math.ceil(citizens / 10 * factor(traits, "militarism") / 2)))
            action = {"type": "start_project", "kind": "barracks", "beds": beds}
            reason = f"a militant fort without barracks: build one for {beds} soldiers"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow.get("archery", True) and any(is_ranged(q) and (q.get("members") or 0) > 0
                                                  for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict))
              and not zones.get("ArcheryRange") and "archery" not in kinds_open):
            n = sum(int(q.get("members") or 0) for q in _l(_d(s.get("military")).get("squads"))
                    if isinstance(q, dict) and is_ranged(q))
            lanes = max(1, min(3, -(-n // 4)))
            action = {"type": "start_project", "kind": "archery", "lanes": lanes, "length": 12}
            reason = f"a crossbow squad of {n} and no archery range: dig one with {lanes} target(s)"
        # Culture: memorials for slain beasts, then a temple for a devout fort.
            cands.append((action, reason))
            action, reason = None, ""
        if (profile["memorials"] and "memorial" not in kinds_open and goal != "maintain"
              and "memorial" not in held and memorial_due(s, memory, player_rules(s))):
            name = profile["memorials"][0]
            action = {"type": "start_project", "kind": "memorial", "name": name}
            reason = f"{name} was slain: build a memorial hall"
            cands.append((action, reason))
            action, reason = None, ""
        if (allow["temple"] and goal != "maintain"
              and (profile["temple"] != "none" or unmet(s, "PrayOrMeditate") >= cfg["needs_build_at"])
              and "temple" not in kinds_open
              and "locations" not in s["_errors"] and not _real_locations(locations, "TEMPLE", memory, _l(loc.get("list")))):
            size = profile["temple"] if profile["temple"] != "none" else "shrine"
            action = {"type": "start_project", "kind": "temple", "size": size}
            reason = (f"the fort is devout and has no temple: build a {size}" if profile["temple"] != "none" else
                      f"{unmet(s, 'PrayOrMeditate')} dwarves are distracted for want of somewhere to pray: build a shrine")
        # Set pieces: in good times, a statue garden named for the fort
            cands.append((action, reason))
            action, reason = None, ""
        # (0.102.1) a devout fort that has its temple raises one to each god
        # many of its dwarves long to pray to (Piety 150 built nothing in the
        # Monastery run: a mature fort saw nothing missing)
        more = more_temple(s, traits, cfg) if (allow["temple"] and goal != "maintain" and "temple" not in kinds_open
                                               and locations.get("TEMPLE")) else None
        if more:
            god, hf, n = more
            # (0.103.12) the bridge knows "shrine" and "grand" only: "temple" was refused
            size = temple_size(traits)
            cands.append(({"type": "start_project", "kind": "temple", "size": size, "deity_hf": hf},
                          f"a devout fort (Piety {int(traits.get('piety', 0)):+d}): {n} dwarves "
                          + ("long to pray to" if n <= int(_d(_d(s.get("needs")).get("deities")).get(god) or 0)
                             else "pray to")
                          + f" {god}, who has no temple here: raise one"))
        # (0.105.23, 14.1 step 4b) a fort this devout has a grand temple: when
        # no god asks for one of its own, a grand temple to all gods (B's
        # first was a shrine dug urgently; the ladder's grand one never came)
        elif (allow["temple"] and goal != "maintain" and "temple" not in kinds_open
              and (traits.get("piety", 0) or 0) >= cfg["temple_grand_piety"]
              and "locations" not in s["_errors"]
              and _real_locations(locations, "TEMPLE", memory, _l(loc.get("list")))
              and int(locations.get("TEMPLE") or 0) < 1 + int((traits.get("piety", 0) or 0) // 50)
              and not has_grand_temple(s, memory)):
            cands.append(({"type": "start_project", "kind": "temple", "size": "grand"},
                          f"a devout fort (Piety {int(traits.get('piety', 0)):+d}) with no grand temple: "
                          "raise a grand temple to all gods"))
        if (allow.get("garden", True) and goal != "maintain" and "garden" not in kinds_open
              and memory is not None and good_times(s, memory, traits, cfg)):
            name = garden_name(s, memory)
            action = {"type": "start_project", "kind": "garden", "name": name}
            reason = (f"good times (fed, safe, {round(100 * _idle_share(s))}% idle): dig a statue garden, "
                      f"The {name} Garden, for the fort to be proud of")
            cands.append((action, reason))
            action, reason = None, ""
        # the plan's great hall, a set piece (0.98): a grand dining hall in
        # the halls district, in good times, once the fort has outgrown its first
        if (memory is not None and goal != "maintain" and zones.get("DiningHall", 0) >= 1
                and "dining" not in kinds_open and citizens >= cfg["great_hall_min_citizens"]
                and masterplan.open_slot(memory, "great hall") and good_times(s, memory, traits, cfg)):
            tables = max(20, min(90, citizens // 2))
            cands.append(({"type": "start_project", "kind": "dining", "tables": tables, "set_piece": "great hall"},
                          f"good times and {citizens} dwarves: raise the plan's great hall, a dining hall of "
                          f"{tables} tables among the halls"))
        # (0.104.85) a mature fort keeps growing its character: a second (and
        # further) tavern, library, hospital or barracks as the fort grows,
        # sooner as the sliders care (the 14.1 exit test: two forts of opposite
        # sliders built the same 20 levels; Enxah: 20 finished, none open)
        if memory is not None and goal != "maintain" and not young:
            cands.extend(growth_candidates(s, traits, cfg, memory, allow, kinds_open, locations, zones, citizens))
            # (0.105.23) a grand temple grown with the fort is the grand temple: not two
            if any(c[0].get("growth") and c[0].get("kind") == "temple" and c[0].get("size") == "grand" for c in cands):
                cands = [c for c in cands if not (c[0].get("kind") == "temple" and c[0].get("size") == "grand"
                                                  and not c[0].get("growth") and "deity_hf" not in c[0])]
        action, reason = need_action, need_reason
        if cands:
            scored = sorted(cands, key=lambda c: -ladder_score(c[0], s, traits, cfg, memory))
            reserved = character_slot_reserved(s, traits, cfg, memory, open_)
            if reserved and memory is not None:
                # (0.105.10 review) a level the game keeps refusing never holds the slot
                now_r = abs_tick(s)
                scored = [c for c in scored if _refused_wait(memory, Proposal("build", c[0], c[1], 6), now_r,
                                                             s.get("bridge_version")) is None] or scored
                if all(_refused_wait(memory, Proposal("build", c[0], c[1], 6), now_r, s.get("bridge_version"))
                       is not None for c in scored):
                    reserved = None
            # (0.105.23, 14.1 step 4b) the Monastery's bend: before the basics
            # are met, a devout fort's last slot may go to a shrine (only a
            # temple, shrine-sized: quick to dig, the food and drink still short)
            if not reserved:
                bend = piety_slot(s, traits, cfg, memory, open_)
                temples = [c for c in scored if c[0].get("kind") == "temple"] if bend else []
                if memory is not None:
                    now_r = abs_tick(s)
                    temples = [c for c in temples if _refused_wait(
                        memory, Proposal("build", dict(c[0], size="shrine"), c[1], 6), now_r,
                        s.get("bridge_version")) is None]
                if temples:
                    scored = [(dict(c[0], size="shrine"),
                               c[1].replace("grand temple", "shrine").replace("build a grand", "build a shrine")
                               + " (a shrine for now: the food and drink aren't all there yet)")
                              for c in temples]
                    reserved = bend
            # (review) care comes first: tombs and a hospital aren't put off
            if reserved and action is not None and action.get("kind") in ("tombs", "hospital"):
                reserved = None
            if len(scored) > 1 and (action is None or reserved):
                notes.append("next level by the fort's temperament: " + ", ".join(
                    f"{_ladder_word(c[0])} {ladder_score(c[0], s, traits, cfg, memory):.1f}" for c in scored[:4]))
            if action is None:
                action, reason = scored[0]
            elif reserved:
                notes.append(f"the last building slot is the fort's own ({reserved}): the "
                             f"{_ladder_word(scored[0][0])} level goes ahead of the {action.get('kind')} level")
                action, reason = scored[0]
                reason += " (the fort's own building slot)"
            if reserved:
                s["_character_slot"] = {"why": reserved, "kind": _ladder_word(scored[0][0])}
    rules_ = player_rules(s)
    if profile["memorials"] and "memorial" not in kinds_open and not memorial_due(s, memory, rules_):
        notes.append(f"memorial for {profile['memorials'][0]} waits: "
                     + ("memorials are switched off in the Rules tab" if rules_["memorial_pace"] == "never"
                        else f"at most one per {rules_['memorial_pace']} (Rules tab)"))
    if action and young and action["kind"] not in ("workshops", "storage", "farms", "tombs"):
        fpd = food_per_dwarf(s)
        if not has_farms(s) and fpd < cfg["found_food_per_dwarf"]:
            notes.append(f"food first: {fpd:g} food a dwarf and no farm yet, so the {action['kind']} level waits "
                         "(the dwarves gather, fish and farm instead)")
            action = None
    # (0.105.26) the ghosts' own tomb level is proposed once, with the urgent
    # levels above (tombs_ghosts); a second copy here proposed it again
    if action:
        action["style"] = layout_style(profile)
        if memory is not None and has_rule(memory.culture, "doored_levels"):
            action["style"]["entry_door"] = True    # (0.103.1, Sealed Halls: the rule had no effect)
        if memory is not None:
            action["style"].update(masterplan.variety(memory, action["kind"]))   # seeded details
        if young:
            action["style"].update(smooth=0, statues=0)    # a young fort builds plain: smoothing and statues later
        where = apply_customs(action, memory, traits, profile, citizens)   # the plan's hint, the customs
        if where:
            reason += f" (in {where['district']})"
        proposals.append(Proposal("build", action, reason, 6))


def temple_size(traits: dict) -> str:
    """(0.105.23) The size of a temple the bridge takes ("shrine" or "grand"):
    grand at Piety +100 and up."""
    return "grand" if (traits.get("piety", 0) or 0) >= 100 else "shrine"


def more_temple(s: dict, traits: dict, cfg: dict):
    """(0.102.1) The god most of the fort's distracted dwarves pray to with
    no temple of their own, for a devout fort that has its first temple:
    (name, deity hf id, dwarves), or None. At most one temple per 50 Piety
    beyond the first. (0.105.23, 14.1 step 4b) At Piety `temple_god_piety`
    and up, the god most citizens pray to (met or not: the bridge's
    `worship`) with no temple of their own, once no distracted dwarves ask:
    the Monastery's temple per god (Piety 150 built one temple to all gods,
    and nobody was distracted enough to ask for more)."""
    piety = traits.get("piety", 0) or 0
    if piety < cfg["temple_more_piety"]:
        return None
    nd = _d(s.get("needs"))
    ids = _d(nd.get("deity_ids"))
    temples = [e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict) and e.get("type") == "TEMPLE"]
    if len(temples) >= 1 + int(piety // 50):
        return None
    # (0.105.23) a god served by a religion's temple has one too
    have = {e.get("deity_hf") for e in temples} | {h for e in temples for h in _l(e.get("religion_deities"))}
    for n, god in sorted(((int(v or 0), g) for g, v in _d(nd.get("deities")).items()), reverse=True):
        hf = ids.get(god)
        if n >= cfg["temple_more_worshippers"] and isinstance(hf, int) and hf not in have:
            return god, hf, n
    if piety >= cfg["temple_god_piety"]:
        for n, god in sorted(((int(v or 0), g) for g, v in _d(nd.get("worship")).items()), reverse=True):
            hf = ids.get(god)
            if n >= cfg["temple_god_worshippers"] and isinstance(hf, int) and hf not in have:
                return god, hf, n
    return None


def has_grand_temple(s: dict, memory) -> bool:
    """(0.105.23, 14.1 step 4b) The fort has a grand temple, or one under
    way: a temple complex (DF's tier 2), an open temple level dug grand, or
    a grand temple the AI started (remembered: the report keeps no size)."""
    if any(isinstance(e, dict) and e.get("type") == "TEMPLE" and int(e.get("tier") or 0) >= 2
           for e in _l(_d(s.get("locations")).get("list"))):
        return True
    if any(isinstance(p, dict) and p.get("kind") == "temple" and _d(p.get("summary")).get("temple") == "grand"
           for p in _l(_d(s.get("projects")).get("open"))):
        return True
    return bool(memory is not None and _d(getattr(memory, "culture", None)).get("grand_temple"))


def tombs_short(s: dict, citizens: int, cfg: dict, memory=None) -> int:
    """How many more free tombs the fort should have (0 if enough, or unknown)."""
    if "dead" in s.get("_errors", {}):
        return 0
    d = _d(s.get("dead"))
    unburied = int(d.get("unburied") or 0)
    why = _d(d.get("why"))
    if why and isinstance(why.get("free"), int):
        # (0.104.101) the bodies a hauler can take now, as the bridge counts them:
        # a body both outside and unreachable was subtracted twice (Teacheroar:
        # 27 unburied, 9 free, 14 outside, 18 out of reach -> 0, a 4-coffin level)
        unburied = int(why["free"]) + sum(int(why.get(k) or 0) for k in ("forbidden", "in_job", "carried"))
    elif why:
        # (0.104.38) only the bodies a tomb can take: Enxah's overnight run dug
        # 23 tomb levels for 35 bodies outside or out of reach, 71 tombs free
        unburied = max(0, unburied - sum(int(why.get(k) or 0) for k in ("outside", "unreachable", "not_ours", "dump")))
    want = max(cfg["min_free_tombs"], math.ceil(citizens * cfg["free_tombs_per_dwarf"])) + unburied
    if memory is not None and has_rule(memory.culture, "lay_the_dead"):
        want *= 2                                   # (0.103.1, Haunted)
    return max(0, want - (d.get("free_tombs") or 0))


# --- (0.104.85) the fort keeps growing its character ----------------------------------


