"""(0.105.40b, M6) The food store: food and drink kept in a stockpile with
barrels, near the kitchen and still, under a roof, sized to the fort; what
rots watched.

The coverage audit (12 Nov): the AI never made sure food was stored
properly. Food lying outside a stockpile rots; food in a pile but out of a
barrel or pot is what vermin eat (DF wiki, Food; Vermin). A pile takes
barrels up to its own max barrels setting.

The `food_store` report (lua/ai-food-store.lua) lists every stockpile that
takes food (its box, tiles and tiles used, max barrels, tiles open to the
sky, whether it is the AI's own), the kitchens and stills (each one's
nearest food pile, and whether a pile would fit near it), and the food
items: lying outside a pile (`loose`), in a pile out of any container
(`exposed`), in barrels and pots, and rotten.

  * food_store: a kitchen or still with no roofed food pile within
    food_store_reach tiles gets one (food_pile: free roofed floor on its
    level, about food_store_tiles_per_citizen tiles a citizen, its max
    barrels a barrel a tile); with no room near it, a storage level of food
    piles (food_store_level) -- (fix41) not while the AI has a roofed food
    pile anywhere or a storage level is open, and at most one level for each
    kitchen or still ever (memory.food_store_seen["levels"], booked by
    note_food_level when the start was not refused). A kitchen or still with
    a feeder_pile proposal this cycle is left to it (fix41). The near piles
    full with food lying about:
    another one beside them (food_pile `more`), up to
    food_store_tiles_cap_factor times the size wanted.
  * food_barrels: an AI food pile near a kitchen or still that takes fewer
    barrels than a barrel a tile is set to take them. The player's own piles
    are never changed (the bridge refuses them too).
  * barrels to put the food in: food_containers_want, read by the container
    rule (planner_industry _supply_rules), which orders barrels (or rock
    pots) as it always has.
  * spoilage: note_food (note_cycle) follows the rotten food; a rise of
    food_store_rot_rise_min within food_store_rot_window_days is said once,
    and for that window the fort's cats are kept from the butcher (the
    vermin rule's keep_mousers).

Without a `food_store` section (an older bridge, a failed one) nothing here
proposes or says anything, and the container rule wants what it did.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, abs_tick

__all__ = ["FOOD_SHOP_ORDER", "food_store", "food_tiles_want", "food_barrels_for", "food_containers_want",
           "food_dist", "_food_store_rule", "note_food", "note_food_level", "food_levels", "food_line"]

FOOD_SHOP_ORDER = ("Kitchen", "Still")


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def food_store(s: dict) -> dict | None:
    """The bridge's food_store section, or None (an older bridge, a failed one)."""
    fs = s.get("food_store")
    if not isinstance(fs, dict) or not fs or "error" in fs:
        return None
    if not isinstance(fs.get("piles"), list) or not isinstance(fs.get("shops"), list):
        return None
    return fs


def food_tiles_want(citizens: int, cfg: dict) -> int:
    """The tiles of food pile wanted near the kitchen and still for the fort."""
    n = math.ceil(max(0, citizens) * cfg["food_store_tiles_per_citizen"])
    return max(cfg["food_store_tiles_min"], min(cfg["food_store_tiles_max"], n))


def food_barrels_for(tiles: int, cfg: dict) -> int:
    """The max barrels a food pile of `tiles` tiles is set to take."""
    return max(1, min(cfg["food_store_barrels_max"], math.ceil(max(1, tiles) * cfg["food_store_barrel_share"])))


def food_containers_want(s: dict, cfg: dict) -> int:
    """Empty barrels or pots wanted for the food lying out of them (in a pile
    or outside one): read by the container rule. 0 without a food_store
    section, or with little food out."""
    fs = food_store(s)
    if fs is None:
        return 0
    it = _d(fs.get("items"))
    n = _int(it.get("exposed")) + _int(it.get("loose"))
    if n < cfg["food_store_exposed_min"]:
        return 0
    return min(cfg["food_store_containers_max"], math.ceil(n / cfg["food_store_per_container"]))


def _box(r: dict) -> tuple | None:
    try:
        return tuple(int(r[k]) for k in ("x1", "y1", "x2", "y2", "z"))
    except (KeyError, TypeError, ValueError):
        return None


def food_dist(a: tuple, b: tuple, cfg: dict) -> int:
    """The walk from one box to another, roughly (as the bridge's box_dist):
    the gap across, and each z-level between as food_store_dz_cost tiles."""
    gx = max(a[0] - b[2], b[0] - a[2], 0)
    gy = max(a[1] - b[3], b[1] - a[3], 0)
    return max(gx, gy) + cfg["food_store_dz_cost"] * abs(a[4] - b[4])


def _roofed(p: dict) -> bool:
    return _int(p.get("outside")) * 2 <= _int(p.get("tiles"))


def _where(r: dict) -> str:
    return f"x{r.get('x', r.get('x1'))} y{r.get('y', r.get('y1'))} elevation {r.get('elevation')}"


def food_levels(memory) -> set:
    """(fix41) The kitchens and stills (ids) a storage level was dug for."""
    seen = _d(getattr(memory, "food_store_seen", None)) if memory is not None else {}
    return {i for i in _l(seen.get("levels")) if isinstance(i, int)}


def note_food_level(p, r: dict, memory) -> None:
    """(fix41, record) A food storage level started (or its outcome unknown):
    the kitchens and stills it was for never get another."""
    if memory is None or getattr(p, "rule", None) != "food_store_level" or _d(r).get("ok") is False:
        return
    ids = [i for i in _l(p.action.get("for_shops")) if isinstance(i, int)]
    if not ids:
        return
    seen = dict(_d(memory.food_store_seen))
    seen["levels"] = sorted(food_levels(memory) | set(ids))[-50:]
    memory.food_store_seen = seen


def _food_store_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    fs = food_store(s)
    if fs is None:
        return
    citizens = _int(_d(s.get("dwarves")).get("total"))
    if citizens < cfg["food_store_min_citizens"]:
        return
    shops = [r for r in _l(fs.get("shops")) if isinstance(r, dict) and isinstance(r.get("id"), int) and _box(r)]
    if not shops:
        return                       # no kitchen or still yet: the workshop rules build them
    shops.sort(key=lambda r: (FOOD_SHOP_ORDER.index(r.get("kind")) if r.get("kind") in FOOD_SHOP_ORDER else 9,
                              r["id"]))
    piles = [p for p in _l(fs.get("piles")) if isinstance(p, dict) and isinstance(p.get("id"), int) and _box(p)]
    reach = cfg["food_store_reach"]
    want = food_tiles_want(citizens, cfg)
    items = _d(fs.get("items"))

    def near(shop, pool):
        sb = _box(shop)
        return [p for p in pool if food_dist(_box(p), sb, cfg) <= reach]

    good = [p for p in piles if _roofed(p) and _int(p.get("tiles")) > 0]
    placed = False
    # (fix41) a kitchen or still the feeder rule gives a pile this cycle: left to it
    feeding = {x.action.get("building_id") for x in proposals if x.action.get("type") == "feeder_pile"}
    # 1. a kitchen or still with no roofed food pile near it
    bare = [r for r in shops if not near(r, good) and r["id"] not in feeding]
    if bare:
        roomy = [r for r in bare if r.get("room") is not False]
        if roomy:
            r = roomy[0]
            open_sky = [p for p in near(r, piles) if not _roofed(p)]
            act = {"type": "food_pile", "building_id": r["id"], "tiles": want,
                   "barrels": food_barrels_for(want, cfg), "reach": reach}
            if open_sky or near(r, piles):
                act["more"] = True          # the near one is under the sky (or empty): one beside it
            proposals.append(Proposal(
                "food_store", act,
                f"no food stockpile under a roof within {reach} tiles of the {r.get('kind')} at {_where(r)}"
                + (" (the one there is open to the sky: food rots in the sun and the rain)" if open_sky else "")
                + f": put one of about {want} tiles for {citizens} dwarves beside it, taking barrels "
                "(food out of barrels rots or is eaten by vermin)", 5))
            placed = True
        else:
            pr = _d(s.get("projects"))
            open_kinds = {p.get("kind") for p in _l(pr.get("open")) if isinstance(p, dict)}
            # (fix41) not while the AI has a roofed food pile anywhere (a level
            # dug before), a storage level is open, or one was dug for each of them
            ai_roofed = any(p.get("ai") for p in good)
            due = [r for r in bare if r["id"] not in food_levels(memory)]
            if (due and not ai_roofed and "storage" not in open_kinds
                    and not any(x.action.get("kind") == "storage" for x in proposals)):
                proposals.append(Proposal(
                    "food_store_level", {"type": "start_project", "kind": "storage", "piles": ["food"],
                                         "room_size": 7, "for_shops": [r["id"] for r in due]},
                    f"no room for a food stockpile within {reach} tiles of the {due[0].get('kind')} at "
                    f"{_where(due[0])}: dig a storage level for the food", 6))
                placed = True
    # 2. the AI's own food piles near a kitchen or still taking barrels
    shop_boxes = [_box(r) for r in shops]
    for p in piles:
        if not p.get("ai") or not isinstance(p.get("barrels"), int):
            continue
        if not any(food_dist(_box(p), b, cfg) <= reach for b in shop_boxes):
            continue
        b_want = food_barrels_for(_int(p.get("tiles")), cfg)
        if p["barrels"] < b_want:
            proposals.append(Proposal(
                "food_barrels", {"type": "food_barrels", "pile_id": p["id"], "barrels": b_want},
                f"the AI's food stockpile at {_where(p)} takes {p['barrels']} barrels for its "
                f"{_int(p.get('tiles'))} tiles: let it take {b_want} (food out of barrels rots or is eaten by vermin)",
                5))
            break
    # 3. the near piles full, food lying about: one more beside them
    if not placed:
        near_all = {p["id"]: p for r in shops for p in near(r, good)}
        tiles = sum(_int(p.get("tiles")) for p in near_all.values())
        used = sum(_int(p.get("used")) for p in near_all.values())
        ai_tiles = sum(_int(p.get("tiles")) for p in near_all.values() if p.get("ai"))
        loose = _int(items.get("loose"))
        if (tiles and used / tiles >= cfg["food_store_full_share"] and loose >= cfg["food_store_loose_min"]
                and ai_tiles < want * cfg["food_store_tiles_cap_factor"]):
            fullest = max(near_all.values(), key=lambda p: (_int(p.get("used")) / max(1, _int(p.get("tiles"))), -p["id"]))
            shop = next((r for r in shops if r["id"] == fullest.get("shop_id")), None) or next(
                r for r in shops if fullest in near(r, good))
            if shop["id"] in feeding:
                shop = None                                 # (fix41) its feeder pile comes first
        else:
            shop = None
        if shop is not None:
            proposals.append(Proposal(
                "food_store", {"type": "food_pile", "building_id": shop["id"], "tiles": want,
                               "barrels": food_barrels_for(want, cfg), "reach": reach, "more": True},
                f"the food stockpiles near the {shop.get('kind')} are full ({used} of {tiles} tiles used) and "
                f"{loose} food items lie outside a pile (they rot): put another of about {want} tiles beside it", 5))
    # 4. spoilage risen lately: the cats kept to hunt the vermin
    seen = _d(getattr(memory, "food_store_seen", None)) if memory is not None else {}
    rise_tick = seen.get("rise_tick")
    if (isinstance(rise_tick, int) and 0 <= abs_tick(s) - rise_tick < cfg["food_store_rot_window_days"] * TICKS_PER_DAY
            and not any(x.action.get("type") == "keep_mousers" for x in proposals)):
        vh = _d(_d(s.get("needs")).get("vermin_hunters"))
        mw = max(cfg["mousers_min"], min(cfg["mousers_max"], citizens // max(1, cfg["citizens_per_mouser"])))
        loose_cats, kept = _int(vh.get("loose")), _int(vh.get("kept"))
        if vh and kept < mw and loose_cats > kept:
            k = min(mw, loose_cats)
            proposals.append(Proposal("vermin", {"type": "keep_mousers", "count": k},
                                      f"food has been rotting or eaten lately ({_int(seen.get('rise'))} more rotten): "
                                      f"{kept} of the {loose_cats} loose cat(s) are safe from the butcher; keep {k} "
                                      "(nicknamed Mouser, which autobutcher spares) to hunt the vermin", 5))


def note_food(s: dict, memory, cfg: dict) -> list[str]:
    """(note_cycle) The rotten food followed: the lowest count seen in the
    window; a rise of food_store_rot_rise_min over it is said once (and
    remembered, for the cats), and the window starts again."""
    fs = food_store(s)
    if fs is None or memory is None:
        return []
    it = _d(fs.get("items"))
    if not isinstance(it.get("rotten"), int) or it.get("partial"):
        return []                   # (fix41) a walk cut short counts too few: not a low to rise from
    rotten, now = it["rotten"], abs_tick(s)
    seen = dict(_d(memory.food_store_seen))
    since, low = seen.get("since"), seen.get("low")
    window = cfg["food_store_rot_window_days"] * TICKS_PER_DAY
    if not isinstance(since, int) or not isinstance(low, int) or not 0 <= now - since < window:
        since, low = now, rotten
    low = min(low, rotten)
    out = []
    rise = rotten - low
    if rise >= cfg["food_store_rot_rise_min"]:
        loose, exposed = _int(it.get("loose")), _int(it.get("exposed"))
        out.append(f"{rise} more food items rotted lately ({rotten} rotten now; {loose} food items lie outside a "
                   f"stockpile, {exposed} in piles out of barrels, where vermin eat them): the AI keeps a roofed food "
                   "pile taking barrels beside the kitchen and still, orders barrels for the food and keeps cats "
                   "from the butcher to hunt the vermin")
        seen.update(rise=rise, rise_tick=now)
        since, low = now, rotten
    seen.update(since=since, low=low, rotten=rotten)
    memory.food_store_seen = seen
    return out


def food_line(s: dict) -> str:
    """The digest's FOOD_STORE line, or "" without a food_store section."""
    fs = food_store(s)
    if fs is None:
        return ""
    piles = [p for p in _l(fs.get("piles")) if isinstance(p, dict)]
    shops = [r for r in _l(fs.get("shops")) if isinstance(r, dict)]
    it = _d(fs.get("items"))
    near = [p for p in piles if isinstance(p.get("dist"), int) and p["dist"] <= _int(fs.get("reach") or 20)]
    tiles = sum(_int(p.get("tiles")) for p in near)
    used = sum(_int(p.get("used")) for p in near)
    no_barrels = sum(1 for p in piles if p.get("barrels") == 0)
    bare = [str(r.get("kind")) for r in shops if not isinstance(r.get("dist"), int) or r["dist"] > _int(fs.get("reach") or 20)]
    return (f"FOOD_STORE piles {len(piles)} (near the kitchen/still: {len(near)}, {used}/{tiles} tiles used; "
            f"taking no barrels: {no_barrels}; AI's own: {sum(1 for p in piles if p.get('ai'))})"
            + (f" | no pile near: {', '.join(bare)}" if bare else "")
            + f" | food out of piles {_int(it.get('loose'))}, in piles out of barrels {_int(it.get('exposed'))},"
            f" in barrels/pots {_int(it.get('in_containers'))}, rotten {_int(it.get('rotten'))}")
