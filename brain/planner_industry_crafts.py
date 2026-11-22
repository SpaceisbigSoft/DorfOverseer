"""planner_industry_crafts: cloth, gems, mechanisms, hauling, the surface
basics, the keep, the feeder shops, the excess shops, footwear and the
pasture (split out of planner_industry in r7 d4, moved unchanged).
planner_industry re-exports every name here."""

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
from planner_food import food_containers_want  # (0.105.40b, M6)
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403
from planner_orders import *  # noqa: F401,F403  (13c: split out by theme)
from planner_trade import *  # noqa: F401,F403  (13c: split out by theme)
from planner_labor import *  # noqa: F401,F403  (13c: split out by theme)
from planner_farms import *  # noqa: F401,F403  (13c: split out by theme)

__all__ = ["PASTURE_TILES_GUESS", "_pasture_rule", "_cloth_rule", "GEMS_GENEROUS_GREED", "_gems_rule", "_spare_mechanisms_rule", "_hauling_rule", "_surface_basics", "_keep_rule", "FEEDER_ORDER", "_feeder_rule", "spare_mechanisms", "EXCESS_SHOPS", "_excess_shops_rule", "_shoes_recipe"]


PASTURE_TILES_GUESS = 20       # (0.105.35) grass tiles an animal needs, when the bridge doesn't say


def _pasture_rule(s: dict, memory, traits: dict, cfg: dict, proposals: list, notes: list) -> None:
    """Grazers without a pasture: into a pasture with room for them, else a
    new pasture on grass near the fort, sized for the herd."""
    so = _d(s.get("society"))
    waiting = so.get("grazers_unpastured") or 0
    if not waiting or not player_rules(s)["pasture_animals"]:
        return
    need = so.get("grazer_tiles")
    spare, smallest = so.get("pasture_spare"), so.get("grazer_tiles_smallest") or 1
    # an older bridge says nothing about room: the old way, into the largest pasture
    room = so.get("pastures") and (spare is None or spare >= smallest)
    if room:
        n = min(20, waiting)
        proposals.append(Proposal("pasture", {"type": "pasture", "count": n},
                                  f"{waiting} grazing animal(s) without a pasture: put up to {n} where "
                                  "there's grass for them", 3))
        return
    guessed = need is None
    if guessed:
        # (0.105.35) nothing waits for the player: an older bridge says nothing
        # of the grass the herd needs, so a pasture sized by a guess per animal
        need = waiting * PASTURE_TILES_GUESS
    if memory.pasture_failure:
        notes.append(f"{waiting} grazing animals have no pasture and will starve, and the AI couldn't "
                     f"make one: {memory.pasture_failure}. It tries again every few days (the grass may "
                     "grow back, or another spot may do) and puts the animals in any pasture there is")
    # room for the herd to grow with Husbandry ("large herds")
    tiles = math.ceil(need * cfg["pasture_margin"] * max(1.0, factor(traits, "husbandry")))
    tiles = max(9, min(600, tiles))
    proposals.append(Proposal("new_pasture", {"type": "make_pasture", "tiles": tiles},
                              f"{waiting} grazing animal(s) need about {need} tiles of grass"
                              + (" (a guess: this bridge doesn't say)" if guessed else "") + " and "
                              + ("no pasture has room" if so.get("pastures") else "there is no pasture")
                              + f": make a {tiles}-tile pasture on grass near the fort", 3))


def _cloth_rule(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """Cloth: dressings for the hospital, bags, rope, and clothes when the
    dwarves' wear out (DFHack's tailor sews them from cloth). Plants with
    thread in them (pig tails, rope reeds) are processed into thread at a
    farmer's workshop, thread woven into cloth at a loom; the two workshops
    are built when missing. Not in a young fort."""
    if young_fort(s, cfg):
        return
    st = _d(s.get("stocks"))
    cloth, thread = int(st.get("cloth") or 0), int(st.get("thread") or 0)
    want = max(cfg["cloth_min"], math.ceil(citizens * cfg["cloth_per_dwarf"]))
    if cloth >= want:
        return
    b = _d(s.get("buildings"))
    missing = [w for w in ("Farmers", "Loom") if not _has_shop(b, w)]
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    # (0.104.132) bigger batches while wounds wait for a dressing (Teacheroar:
    # 79 waiting, 10 cloth, thread and cloth made 5 at a time)
    dressing = int(_d(_d(s.get("health")).get("needs_counts")).get("dressing") or 0)
    batch = min(cfg["cloth_batch_max"], cfg["cloth_batch"] + dressing // cfg["dressings_per_extra_bolt"])
    if missing:
        if not _workshops_busy(open_):
            proposals.append(Proposal("cloth", {"type": "start_project", "kind": "workshops", "shops": missing},
                                      f"only {cloth} cloth for {citizens} dwarves (dressings, bags, rope, clothes): "
                                      f"dig and build {', '.join(missing)} to make thread and weave it", 6))
        return
    # (0.104.28) yarn thread (shorn wool) is woven as yarn cloth: a plant-cloth
    # order can't use it
    weave = "weave_yarn_cloth" if (not thread_plants_here(s) and wool_route(s)) else "weave_plant_cloth"
    # (0.104.54) the thread the hospital keeps isn't free to weave (Enxah: 6
    # thread counted, all the hospital's: weave_yarn_cloth ordered and stuck
    # 23 times while 14 patients waited for dressings and no cloth was made)
    hosp = _location(s, "HOSPITAL")
    if hosp is not None:
        thread = max(0, thread - int(_d(hosp.get("have")).get("thread") or 0) // LOCATION_UNITS["thread"])
    if thread < 3 and not thread_plants_here(s) and wool_route(s):
        sup = _d(s.get("supplies"))
        for recipe, n, what in (("shear_creature", min(5, int(sup.get("shearable") or 0)), "shear"),
                                ("spin_thread", 5, "spin the wool into thread")):
            if not queued(s, {recipe}):
                proposals.append(Proposal("cloth", {"type": "work_order", "recipe": recipe, "amount": max(1, n)},
                                          f"only {cloth} cloth (the fort wants {want}) and no free thread; "
                                          f"{sup.get('shearable')} animals can be shorn: {what}", 4, True))
                return
    # (0.104.123) a weave order DF made no job from (Teacheroar: 12 thread
    # counted, the order 32 days without a job, cancelled and stuck again):
    # that thread isn't fit for the loom, so plants are processed for more
    stalled = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("recipe") == weave
               and o.get("by_ai") and not int(_d(o.get("jobs")).get("n") or 0)]
    if (stalled and (st.get("plants") or 0) > 0 and thread_plants_here(s) and _has_shop(b, "Farmers")
            and not queued(s, {"process_plants"})):
        proposals.append(Proposal("cloth", {"type": "work_order", "recipe": "process_plants",
                                            "amount": batch},
                                  f"only {cloth} cloth and the weave order has made no job (the {thread} thread "
                                  "isn't fit for the loom): process plants for fresh thread", 5, True))
        return
    if thread >= 3 and not queued(s, {weave}):
        n = min(thread, batch, want - cloth)
        proposals.append(Proposal("cloth", {"type": "work_order", "recipe": weave, "amount": max(1, n)},
                                  f"only {cloth} cloth (the fort wants {want}) and {thread} thread: weave {max(1, n)}",
                                  5, True))
    elif thread < 3 and (st.get("plants") or 0) > 0 and thread_plants_here(s) and not queued(s, {"process_plants"}):
        proposals.append(Proposal("cloth", {"type": "work_order", "recipe": "process_plants",
                                            "amount": batch},
                                  f"only {cloth} cloth and {thread} thread: process plants for thread "
                                  "(the ones with fibre in them)", 5, True))


GEMS_GENEROUS_GREED = -30     # (0.105.33) at or under this, twice the gems set into goods to give away


def _gems_rule(s: dict, cfg: dict, proposals: list, traits: dict | None = None, memory=None,
               notes: list | None = None) -> None:
    """Gems: rough gems are cut at a jeweller's (DFHack's autogems, the tools
    rule) and sold; the workshop first. Cut gems in stock are set into the
    crafts waiting to be sold (several times their value), a few at a time.
    (0.105.33, Greed) A grasping fort (keeps_treasures: Greed +30, or
    Gem-mad) never sets them: its cut gems are the hoard. A generous one
    (Greed -30 or less) sets up to 10 at a time, not 5. `traits` defaults to
    the report's; without `memory` Gem-mad isn't seen (Greed alone is)."""
    tr = _d(s.get("trade"))
    cg = _d(tr.get("cut_gem"))
    t = traits if traits is not None else _traits(s)
    greed = _d(t).get("greed", 0) or 0
    hoard = keeps_treasures(t, memory)
    # (0.105.24) a strange mood waiting for a rough or a cut gem it can't find:
    # the jewellers leave the last ones alone (E, 3 Nov: moods failed on "a
    # rough gem" while the AI cut 4-7 at a time down to under 5)
    waits = mood_waits(s)
    if (_has_shop(s["buildings"], "Jewelers") and int(cg.get("n") or 0) >= cfg["gems_cut_at"]
            and "cut_gem" not in waits
            and int(tr.get("goods") or 0) >= cfg["gems_cut_at"] and str(cg.get("token", "")).startswith("INORGANIC:")
            and not queued(s, {"encrust_goods"})):
        if hoard:
            if notes is not None:
                notes.append(f"{cg.get('total')} cut gems kept in store, not set into crafts: "
                             + (f"Greed {int(greed):+d}" if greed >= KEEP_TREASURES_GREED else "Gem-mad")
                             + ", the fort hoards its gems")
            n = 0
        else:
            n = min(10 if greed <= GEMS_GENEROUS_GREED else 5, int(cg["n"]) // 2)
    else:
        n = 0
    if n > 0:
        proposals.append(Proposal("encrust", {"type": "work_order", "recipe": "encrust_goods", "amount": n,
                                              "material": cg["token"]},
                                  f"{cg.get('total')} cut gems and {tr.get('goods')} crafts to sell: set {n} "
                                  f"{str(cg['token']).split(':')[-1].lower().replace('_', ' ')} into crafts "
                                  "(worth far more to the caravans)", 6, True))
    rough = int(_d(s.get("stocks")).get("rough_gems") or 0)
    # (0.104.84) no autogems in this DFHack (the tools report doesn't know it):
    # the gems are cut by work order, the commonest rough gem a few at a time
    rg = _d(tr.get("rough_gem"))
    if (_has_shop(s["buildings"], "Jewelers") and _d(s.get("tools")).get("autogems") is None
            and int(rg.get("n") or 0) >= 1 and rough >= cfg["gems_cut_at"] and "rough" not in waits
            and str(rg.get("token", "")).startswith("INORGANIC:") and not queued(s, {"cut_gems"})):
        n = min(10, int(rg["n"]))
        proposals.append(Proposal("gem_cutting", {"type": "work_order", "recipe": "cut_gems", "amount": n,
                                                  "material": rg["token"]},
                                  f"{rough} rough gems and no autogems to cut them: cut {n} "
                                  f"{str(rg['token']).split(':')[-1].lower().replace('_', ' ')} "
                                  "(cut gems sell for far more, and are set into crafts)", 6, True))
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if (rough >= cfg["gems_cut_at"] and not _has_shop(s["buildings"], "Jewelers") and not young_fort(s, cfg)
            and not _workshops_busy(open_)):
        proposals.append(Proposal("gems", {"type": "start_project", "kind": "workshops", "shops": ["Jewelers"]},
                                  f"{rough} rough gems and no jeweller's workshop: build one (cut gems sell well)", 8))


def _spare_mechanisms_rule(s: dict, cfg: dict, traits: dict, proposals: list) -> None:
    """(0.96) Engineering +50 or more: a few mechanisms kept spare for levers,
    traps and links (spare_mechanisms), made at a mechanic's workshop."""
    want = spare_mechanisms(traits)
    have = free_stock(s, "mechanisms")
    if (want and have < want and not young_fort(s, cfg) and _has_shop(s["buildings"], "Mechanics")
            and not queued(s, {"mechanisms"})):
        proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                 "amount": want - have},
                                  f"Engineering {int(traits.get('engineering', 0)):+d}: keep {want} mechanisms spare "
                                  f"for levers and traps ({have} now): a mechanic makes {want - have}", 7, True))


def _hauling_rule(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """Stone is the heaviest thing dwarves carry: wheelbarrows (one per 15
    dwarves, at least 2) once the fort digs a lot."""
    su, st = _d(s.get("supplies")), _d(s.get("stocks"))
    if "wheelbarrows" not in su or young_fort(s, cfg) or not _has_shop(s["buildings"], "Carpenters"):
        return
    want = max(2, citizens // 15)
    have = (su.get("wheelbarrows") or 0) + queued(s, {"wheelbarrow"})
    if have < want and (st.get("wood") or 0) >= 10:
        proposals.append(Proposal("hauling", {"type": "work_order", "recipe": "wheelbarrow", "amount": want - have},
                                  f"{su.get('wheelbarrows') or 0} wheelbarrows for {citizens} dwarves and "
                                  f"{st.get('boulders') or 0} loose stones: make {want - have}", 6, True))


def _surface_basics(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """A refuse pile and a trade depot outside. Where trees stand in the way
    the woodcutters fell them first (the bridge keeps the spot); the thing is
    placed once the last tree is down."""
    b = _d(s.get("buildings"))
    clearing = _d(b.get("clearing"))

    def why(kind: str, text: str) -> str:
        n = clearing.get(kind)
        if n == 0:
            return text + ": the trees in the way are down, place it"
        return text

    if ("refuse_piles" in b and not b.get("refuse_piles") and citizens >= 5
            and not clearing.get("refuse")):
        proposals.append(Proposal("refuse", {"type": "place_surface", "kind": "refuse"},
                                  why("refuse", "no refuse pile: put one outside, near the way in (rot left "
                                      "indoors makes miasma)"), 5))
    fed = not young_fort(s, cfg) or has_farms(s) or food_per_dwarf(s) >= cfg["found_food_per_dwarf"]
    if (not _d(b.get("other")).get("TradeDepot") and not _d(b.get("being_built")).get("TradeDepot")
            and citizens >= 10 and fed and not clearing.get("depot")):
        proposals.append(Proposal("depot", {"type": "place_surface", "kind": "depot"},
                                  why("depot", "no trade depot: build one outside, so caravans can trade "
                                      "(cloth, rope, metal, seeds the fort can't make)"), 6))


def _keep_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list, memory=None) -> None:
    """Building above ground (Surface ambition 50+): a keep round the fort's way
    in from the surface, walls with a door first, then a roof over the inside.
    One step at a time (the bridge keeps where it's got to); not in a young or
    small fort, not while enemies can reach the dwarves, and only with stone,
    blocks or logs to build with."""
    if traits.get("surface", 0) < cfg["keep_surface_min"] and not (
            memory is not None and has_rule(memory.culture, "keep_above")):     # (0.103.18) Sky-reachers
        return
    if masterplan.underground_only(traits):
        return          # (0.105.23) the Deep mine raises nothing above ground, whatever its quirks
    b = _d(s.get("buildings"))
    k = b.get("keep")
    if isinstance(k, dict):
        stage = k.get("stage")
        if stage == "done":
            return
        if stage == "clearing" and k.get("trees_left"):
            notes.append(f"the keep: the woodcutters fell {k['trees_left']} tree(s) in the way of its walls")
            return
        if stage == "walls" and k.get("walls_planned"):
            notes.append(f"the keep: {k['walls_planned']} wall tile(s) still to build")
            return
        if stage == "stair" and (k.get("stair_planned") or k.get("roof_planned")):
            # (0.105.30, construction seams) the stair up to the roof, waiting
            # to be built (keep_status stair_planned; roof_planned counts it too)
            notes.append("the keep: its stair up to the roof is still to build")
            return
        if stage == "roof" and k.get("roof_planned"):
            notes.append(f"the keep: {k['roof_planned']} roof tile(s) still to build")
            return
    if young_fort(s, cfg) or citizens < cfg["keep_min_citizens"]:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    # (0.105.30, construction) one building above ground at a time: the keep
    # waits while a surface hall builds (clearing to roof)
    hs = _d(b.get("halls"))
    hs = next((x for x in _l(hs.get("list")) if isinstance(x, dict)), hs)
    if hs.get("stage") in ("clearing", "walls", "floor", "roof"):
        notes.append(f"the keep waits for the hall ({hs['stage']}): one building above ground at a time")
        return
    # (0.105.30) blocks first (free ones: faster to build, lighter to haul),
    # then boulders and logs
    st = _d(s.get("stocks"))
    blocks = free_stock(s, "blocks")
    if blocks < cfg["keep_min_material"] and (
            blocks + st.get("boulders", 0) + st.get("wood", 0) < cfg["keep_min_material"]):
        notes.append(f"the keep waits for blocks, building stone or logs (needs {cfg['keep_min_material']}, "
                     f"{blocks} free blocks)")
        return
    if not isinstance(k, dict):
        # (0.105.23) the bridge looks round every way in first, then for open
        # flat ground near the surface farms (F: 39 refusals on a slope)
        why = ("Surface ambition: a walled keep with one door, the first building above ground: "
               "round the way in from the surface, else on open ground near the fields")
    elif k.get("stage") == "clearing":
        why = "the keep: the trees are down, raise its walls and door"
    elif k.get("stage") == "walls":
        why = "the keep: its walls stand, put a roof over the inside"
    elif k.get("stage") == "stair":
        why = "the keep: a stair up to its roof is built, put the roof over the inside"
    else:
        why = "the keep: its roof is built, call it finished"
    proposals.append(Proposal("keep", {"type": "place_keep"}, why, 7))


# workshops given a feeder stockpile first (the busiest hauling first)
FEEDER_ORDER = ("Masons", "Carpenters", "Smelter", "MetalsmithsForge", "Craftsdwarfs", "Depot", "Kitchen", "Still",
                "WoodFurnace", "Bowyers", "Loom", "Clothiers", "Leatherworks")


def _feeder_rule(s: dict, cfg: dict, proposals: list) -> None:
    """Hauling: a small stockpile beside each workshop for what it uses, and
    one for goods beside the depot (lua/ai-builder.lua place_feeder), one a
    cycle, busiest first. Not in a young fort (it has few piles to spare)."""
    if young_fort(s, cfg):
        return
    # (0.104.138) never one with no room for a pile (the bridge's own check)
    rows = [r for r in _l(_d(s.get("logistics")).get("feeders")) if isinstance(r, dict) and not r.get("has")
            and r.get("room") is not False]
    rows.sort(key=lambda r: FEEDER_ORDER.index(r.get("kind")) if r.get("kind") in FEEDER_ORDER else 99)
    # (0.102.2) the stills' piles first while drink is short (Monastery's 5
    # stills on three levels had none: plants were hauled across the fort)
    if drink_below_target(s, int(_d(s.get("dwarves")).get("total") or 0), cfg):
        rows.sort(key=lambda r: 0 if r.get("kind") == "Still" else 1)
    if rows:
        r = rows[0]
        where = "the trade depot" if r.get("kind") == "Depot" else f"the {r.get('kind')}"
        proposals.append(Proposal("feeder", {"type": "feeder_pile", "building_id": r["id"]},
                                  f"no {r.get('what')} pile near {where} (x{r.get('x')} y{r.get('y')}): put a small "
                                  "one beside it, so the hauling is short", 6))


def spare_mechanisms(traits: dict) -> int:
    """Engineering +50 or more: mechanisms kept spare for levers and traps,
    one per 25 (2 at +50, 4 at +100, 8 at +200)."""
    e = traits.get("engineering", 0) or 0
    return int(e // 25) if e >= 50 else 0


# workshops the fort can have far too many of (0.75.0 built 116 soap maker's): name -> most kept
EXCESS_SHOPS = {"SoapMaker": 2, "ScrewPress": 2}   # (item9) the AI builds screw presses for paper


def _excess_shops_rule(s: dict, cfg: dict, proposals: list) -> None:
    places = {**_d(_d(s.get("buildings")).get("workshops"))}
    for name, most in EXCESS_SHOPS.items():
        n = sum(places.get(k, 0) for k in SHOP_ALIASES.get(name, (name,)))
        if n > most:
            proposals.append(Proposal("excess_shops", {"type": "remove_workshops", "kind": name, "keep": 1,
                                                       "max": 20},
                                      f"{n} {name} workshops (one is enough): take down the idle extras", 6))


def _shoes_recipe(m: dict, stocks: dict, notes: list) -> str | None:
    """Footwear for a mandate: shoes in leather (else cloth), socks in cloth,
    low boots in leather, high boots in metal at a forge. (0.105.35) Short
    of leather or cloth, or a kind the AI has no recipe for: a note of what
    the AI does (it buys leather and cloth from the caravans and orders the
    footwear once there is enough), never a Needs you."""
    sub = m.get("subtype")
    need = m.get("remaining") or 1
    if sub == "ITEM_SHOES_SOCKS":
        if stocks.get("cloth", 0) >= need:
            return "cloth_socks"
        notes.append("mandate for socks: not enough cloth: the AI buys cloth from the caravans and makes "
                     "them once there is")
        return None
    if sub == "ITEM_SHOES_BOOTS_LOW":
        if stocks.get("leather", 0) >= need:
            return "leather_low_boots"
        notes.append("mandate for low boots: not enough leather: the AI buys leather from the caravans and "
                     "makes them once there is")
        return None
    if sub == "ITEM_SHOES_BOOTS":
        return "metal_high_boots"
    if sub not in (None, "ITEM_SHOES_SHOES"):
        notes.append(f"mandate for {str(sub).replace('ITEM_SHOES_', '').lower()}: the AI has no recipe for "
                     "these (dwarves don't make them), so this mandate goes unmet; the AI meets the others")
        return None
    if stocks.get("leather", 0) >= need:
        return "leather_shoes"
    if stocks.get("cloth", 0) >= need:
        return "cloth_shoes"
    notes.append("mandate for shoes: not enough leather or cloth: the AI buys both from the caravans and "
                 "makes them once there is")
    return None
