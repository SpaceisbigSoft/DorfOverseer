"""planner_industry: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

from __future__ import annotations
import json
import math
import re
from dataclasses import asdict, dataclass, field
from culture import layout_style, new_history, pick_stone, profile_from, stone_for
from learning import held_levels
import masterplan
import phases
from quirks import has_rule
from digest import _d, _l, normalize
from planner_core import *  # noqa: F401,F403

__all__ = ["CONTAINER_RECIPES", "GEAR_ORDER_METALS", "_supply_rules", "_slow_game_rules", "_kiln_rules", "_soap_rule", "_pasture_rule", "LABOR_MODES_FIXED", "INDUSTRY_SHOPS", "_industry_rules", "_steel_rule", "_bottleneck_rule", "drink_short", "_crop_rules", "_kitchen_rule", "_fishery_rule", "_bench_coffins_rule", "STONE_CRAFTS", "order_shop", "_order_slots_rule", "_orphan_jobs_rule", "_unsuspend_rule", "_approve_rule", "_stuck_orders_rule", "COAL_STONES", "_coal_rule", "_picks_order", "_stone_rule", "stone_crisis", "PRECIOUS_ORES", "_cloth_rule", "_trade_rules", "_gems_rule", "trade_wants", "_spare_mechanisms_rule", "_hauling_rule", "_surface_basics", "trees_this_year", "_keep_rule", "_free_time_rule", "_labor_rules", "OWN_LABOR_RULES", "FEEDER_ORDER", "_feeder_rule", "woodcutters", "gatherers", "trade_margin_for", "keeps_treasures", "spare_mechanisms", "_dairy_rule", "_eggs_rule", "EXCESS_SHOPS", "_excess_shops_rule", "drink_below_target", "_labor_waiting_rule", "farm_target", "_farm_rule", "_smelting_rule", "_shoes_recipe", "_glass_rule", "PRECIOUS_METALS", "precious_metal"]

CONTAINER_RECIPES = {"wooden_barrel", "stone_large_pot"}
# ore worth mining for gear, most wanted first (iron makes steel; tin with copper makes bronze)
GEAR_ORDER_METALS = ("IRON", "COPPER", "TIN", "BISMUTH", "SILVER")


def _supply_rules(s: dict, citizens: int, cfg: dict, proposals: list, notes: list,
                  stonebound: bool = False, memory=None) -> None:
    """Things that stall a fort quietly: no free barrels or pots (brewing and
    cooking just stop), a hospital with nothing to treat with, no well."""
    st, sup = s["stocks"], s["supplies"]
    wood, boulders = st.get("wood", 0), st.get("boulders", 0)
    other = _d(s["buildings"].get("other"))
    wells = other.get("Well", 0)

    # Containers: barrels when there's wood to spare, otherwise rock pots
    # (always rock pots for a Stonebound fort, while it has the stone).
    free = (sup.get("empty_barrels") or 0) + (sup.get("empty_pots") or 0)
    want = max(cfg["min_empty_containers"], math.ceil(citizens * cfg["empty_containers_per_dwarf"]))
    pending = queued(s, CONTAINER_RECIPES)
    if free + pending < want:
        amount = _clamp(want * 2 - free - pending, 5, 30)
        wood_spare = wood - citizens * cfg["wood_per_dwarf"]
        if stonebound and boulders >= amount:
            recipe, what = "stone_large_pot", "rock pots (Stonebound: stone wherever stone will do)"
        elif wood_spare >= amount:
            recipe, what = "wooden_barrel", "barrels"
        elif boulders >= amount:
            recipe, what = "stone_large_pot", "rock pots"
        else:
            recipe = None
            ask_player(notes, f"only {free} empty barrels/pots (brewing and cooking stop without them), "
                         "and too little wood or stone to make more")
        if recipe:
            proposals.append(Proposal(
                "containers", {"type": "work_order", "recipe": recipe, "amount": amount},
                f"only {free} empty barrels/pots (+{pending} queued) for {citizens} dwarves; "
                f"brewing and cooking stop without them: make {what}", 2, True))

    # Bins hold finished goods, bars, cloth and the like: a stockpile with
    # bins takes far more, and haulers carry a bin's worth in one trip.
    bins, bins_want = st.get("bins") or 0, max(cfg["min_bins"], math.ceil(citizens * cfg["bins_per_dwarf"]))
    # (0.104.75) the finished-goods piles full with crafts one to a tile: a bin
    # holds many, so more bins before more storage levels (Enxah: 1520 of 1522
    # tiles used, 166 loose, 48 bins in the fort, a storage level dug every 168
    # days for the crafts)
    fg = _d(_d(_d(s.get("logistics")).get("storage")).get("finished_goods"))
    fg_tiles, fg_used, fg_loose = int(fg.get("tiles") or 0), int(fg.get("used") or 0), int(fg.get("loose") or 0)
    if fg_tiles and fg_used >= fg_tiles * 0.95 and fg_loose >= 20:
        bins_want = max(bins_want, min(bins + cfg["bins_for_goods_step"], bins + fg_used // 20))
    if (bins + queued(s, {"wooden_bin"}) < bins_want and not young_fort(s, cfg)
            and wood - citizens * cfg["wood_per_dwarf"] >= bins_want - bins):
        proposals.append(Proposal(
            "bins", {"type": "work_order", "recipe": "wooden_bin", "amount": min(10, bins_want - bins)},
            (f"the finished-goods piles are full ({fg_used} of {fg_tiles} tiles, {fg_loose} loose) and the "
             f"fort has {bins} bins: make more (a bin holds many crafts)"
             if fg_tiles and fg_used >= fg_tiles * 0.95 and fg_loose >= 20 else
             f"only {bins} bins for {citizens} dwarves (goods and bars pile up loose and take many trips): "
             "make some"), 5, True))

    # Bags hold seeds, flour and gathered plants.
    bags, bags_want = sup.get("empty_bags") or 0, max(cfg["min_empty_bags"],
                                                       math.ceil(citizens * cfg["empty_bags_per_dwarf"]))
    # (0.86) of the kind of cloth there is: a plant-cloth order can't use the
    # silk or yarn cloth caravans bring (region2: cloth_bag stuck twice with 96 cloth)
    kinds = _d(sup.get("cloth_kinds"))
    kind = max(kinds, key=lambda k: kinds.get(k) or 0) if kinds else "plant"
    bag_recipe = {"plant": "cloth_bag", "silk": "silk_bag", "yarn": "yarn_bag"}.get(kind, "cloth_bag")
    have_cloth = (kinds.get(kind) or 0) if kinds else st.get("cloth", 0)
    # (only orders of this kind count: an old plant-cloth order that can't
    # move would otherwise hold the bags back)
    # (0.88) DF stores seeds in bags whenever it can, a bag for each kind of
    # seed (DF wiki, Bag): every kind of seed still lying loose takes the
    # next new bag before a kiln can, so those bags are made on top
    use = _d(sup.get("bag_use"))
    seed_bags = min(cfg["seed_bags_max"], int(use.get("seed_kinds_loose_unbagged") or 0)) if use else 0
    bags_want += seed_bags
    # (0.102.4) the cloth already promised to bag orders counts: 5 plant cloth
    # (2 bags' worth) got a new 2-bag order every cycle (Enxah: 3 in a minute)
    n_bags = min(bags_want - bags, have_cloth // 2 - queued(s, {bag_recipe}))
    # (0.87.1) bags filled as fast as they're made (live: ~30 yarn bags in 20
    # minutes, 70 -> 42 yarn cloth, empty bags still 0: seeds and plants take
    # them): no more until one stays empty, said once
    recent = 0
    if memory is not None:
        now = abs_tick(s)
        for key, log in (getattr(memory, "action_log", None) or {}).items():
            if str(key).startswith("bags:"):
                recent += sum(1 for t in log if isinstance(t, int) and 0 <= now - t < cfg["bag_sink_days"] * TICKS_PER_DAY)
    sink_orders = cfg["bag_sink_orders"] + math.ceil(seed_bags / 5)
    held = _d(use.get("held")) if use else {}
    held_txt = ", ".join(f"{n} {k.lower()}" for k, n in sorted(held.items(), key=lambda kv: -kv[1])[:4]) if held else ""
    if bags == 0 and recent >= sink_orders:
        notes.append(f"{recent} bag orders in {cfg['bag_sink_days']} days and still no empty bag: they fill as fast as "
                     "they're made" + (f" (the bags hold {held_txt})" if held_txt else " (seeds, flour, gathered plants)")
                     + ": no more for now")
    elif (bags + queued(s, {bag_recipe}) < bags_want and n_bags > 0
          and not _has_shop(s["buildings"], "Clothiers")):
        # (0.104.87) bags are sewn at a clothier's: without one the order never
        # moved (Teacheroar, y50: cloth_bag stuck, cancelled, ordered again, 54 days)
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            proposals.append(Proposal("bags", {"type": "start_project", "kind": "workshops", "shops": ["Clothiers"]},
                                      f"only {bags} empty bags and no clothier's workshop to sew them: build one", 5))
    elif bags + queued(s, {bag_recipe}) < bags_want and n_bags > 0:
        proposals.append(Proposal(
            "bags", {"type": "work_order", "recipe": bag_recipe, "amount": min(n_bags, 10)},
            f"only {bags} empty bags (seeds, flour, quicklime and plaster need them)"
            + (f"; {seed_bags} kind(s) of seed lie loose and take the next new bags" if seed_bags else "")
            + (f": make them of {kind} cloth ({have_cloth})" if kinds else ""), 4, True))

    # Hospital supplies, once there is a hospital (or someone needs care).
    hospital = _d(s["locations"].get("count")).get("HOSPITAL", 0)
    patients = _d(s.get("dwarves")).get("needs_medical_care") or 0
    if hospital or patients:
        need = max(cfg["min_hospital_items"], math.ceil(citizens * cfg["hospital_items_per_dwarf"]))
        # (0.104.37) and one for each patient waiting for one: Enxah's doctors
        # cancelled "Immobilize: Need splint" with 3 splints counted in the
        # fort (none to hand) and 4 patients waiting
        waits = [set(_l(p.get("needs"))) for p in _l(_d(s.get("health")).get("patients")) if isinstance(p, dict)]
        n_splint = sum(1 for w in waits if w & {"immobilize", "traction"})
        n_crutch = sum(1 for w in waits if "crutch" in w)
        hh = _d(s.get("health"))                  # (0.104.133) the full counts: the list stops at 30
        if isinstance(hh.get("splint_wait"), int):
            n_splint = hh["splint_wait"]
        if isinstance(_d(hh.get("needs_counts")).get("crutch"), int):
            n_crutch = hh["needs_counts"]["crutch"]
        wants = [("splints", "wooden_splint", need + n_splint), ("crutches", "wooden_crutch", need + n_crutch),
                 ("buckets", "wooden_bucket", max(cfg["min_buckets"], wells))]
        short = [(k, r, n - (sup.get(k) or 0) - queued(s, {r})) for k, r, n in wants]
        short = [(k, r, n) for k, r, n in short if n > 0]
        if short:
            k, r, n = short[0]          # one order per cycle; the next comes after
            if wood >= n:
                proposals.append(Proposal(
                    "hospital", {"type": "work_order", "recipe": r, "amount": n},
                    f"the hospital has {sup.get(k) or 0} {k}; it should keep {n + (sup.get(k) or 0)}", 2, True))
            else:
                ask_player(notes, f"the hospital is short of {k} but there is no wood to make them")
        # Needs you only while someone needs care; otherwise a note
        say = (lambda t: ask_player(notes, t)) if patients else notes.append
        _soap_rule(s, cfg, proposals, notes, say, memory)
        # (0.84) the hospital's own stock against what it keeps (DF's location
        # screen: thread and cloth in 15000 and 10000 units, soap and plaster
        # powder in 150): region2 kept all its thread and cloth while the
        # fort-wide count said "5 thread"
        loc = _location(s, "HOSPITAL")
        if loc is not None:
            short = _location_short(loc, ("thread", "cloth", "splints", "crutches", "soap", "powder"))
            thread_short = "thread" in short
        else:
            short, thread_short = {}, st.get("thread", 0) < cfg["hospital_thread_min"]
        if thread_short and not thread_plants_here(s) and wool_route(s):
            # (0.104.28) the wool route: no fibre crop, but animals to shear:
            # shorn at the farmer's workshop, spun into thread there
            for recipe, n, what in (("shear_creature", min(5, int(sup.get("shearable") or 0)), "shear"),
                                    ("spin_thread", 5, "spin the wool into thread")):
                if not queued(s, {recipe}):
                    proposals.append(Proposal("hospital", {"type": "work_order", "recipe": recipe, "amount": max(1, n)},
                                              f"the hospital is short of thread and no plant here gives it, but "
                                              f"{sup.get('shearable')} tame animal(s) can be shorn: {what}", 4, True))
        elif thread_short and not thread_plants_here(s):
            # (0.104.11) no plant here gives thread: the order would only stand
            # still (Enxah: 59 ordered and cancelled, patients waiting for
            # sutures died in the hospital)
            needing = sum(1 for p in _l(_d(s.get("health")).get("patients"))
                          if isinstance(p, dict) and ({"suture", "dressing"} & set(_l(p.get("needs")))))
            if isinstance(_d(s.get("health")).get("stitch_wait"), int):
                needing = _d(s.get("health"))["stitch_wait"]           # (0.104.133)
            text = ("no plant here gives thread (pig tail, rope reed, hemp...) and no animal to shear: thread and "
                    "cloth come only from the caravans (the AI buys them) or from seeds of a fibre plant")
            if needing:
                ask_player(notes, f"{needing} patient(s) wait for sutures or dressings and " + text)
            else:
                notes.append(text)
        elif (thread_short and _has_shop(s["buildings"], "Farmers")
                and (st.get("plants") or 0) > 0 and not queued(s, {"process_plants"})):
            # (0.83) stitches need thread; the cloth rule only asks for thread
            # when cloth runs short (region2: 100 cloth, 5 thread)
            proposals.append(Proposal("hospital", {"type": "work_order", "recipe": "process_plants",
                                                   "amount": cfg["cloth_batch"]},
                                      f"the hospital is short of thread for stitches (the fort has "
                                      f"{st.get('thread', 0)}): process plants for thread (the ones with fibre in them)",
                                      4, True))
        if loc is not None:
            if short:
                say("the hospital keeps less than it should: " + ", ".join(
                    f"{k} {h} of {w}" for k, (h, w) in short.items())
                    + ("; plaster powder comes from gypsum at a kiln" if "powder" in short else ""))
        elif st.get("thread", 0) < 10 or st.get("cloth", 0) < 10:
            say(f"the hospital needs thread and cloth for stitches and dressings "
                f"(thread {st.get('thread', 0)}, cloth {st.get('cloth', 0)})")
        # (its staff: _staff_rule makes the posts and fills them, 0.85)

    # Water: the injured can only drink water, carried from a well. With no
    # well the AI places one itself (_well_rule).
    if wells and (sup.get("buckets") or 0) == 0 and not (hospital or patients):
        proposals.append(Proposal("hospital", {"type": "work_order", "recipe": "wooden_bucket", "amount": 3},
                                  "the wells have no buckets", 3, True))


def _slow_game_rules(s: dict, citizens: int, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """The game runs slowly (FPS measured by the overseer): besides holding
    newcomers and new luxury levels, what the counts point at. Many items:
    a garbage dump outside, then worn-out clothes lying about marked for it
    (DFHack's cleanowned, at most once a week). Big herds: autobutcher (the
    tools rule). Said with the counts either way."""
    c = _d(_d(s.get("logistics")).get("counts"))
    items, units = int(c.get("items") or 0), int(c.get("units") or 0)
    if not c:
        return
    # (0.104.113) what fills the map, counted once a week while slow
    cen = _d(getattr(memory, "census", None)) if memory is not None else {}
    if not isinstance(cen.get("tick"), int) or not 0 <= abs_tick(s) - cen["tick"] < 7 * TICKS_PER_DAY:
        proposals.append(Proposal("census", {"type": "census"},
                                  f"{units} creatures and {items} items on the map: count what they are", 6))
    notes.append(f"the game runs slowly (FPS {s.get('fps_low')}): {items} items, {units} creatures, "
                 f"{c.get('jobs')} jobs on the map")
    if items >= cfg["fps_items_heavy"]:
        zones = _d(_d(s.get("buildings")).get("zones"))
        if not zones.get("Dump") and not _d(_d(s.get("buildings")).get("clearing")).get("dump"):
            proposals.append(Proposal("dump", {"type": "place_surface", "kind": "dump"},
                                      f"{items} items on the map slow the game: make a garbage dump outside "
                                      "for worn-out things", 5))
        else:
            proposals.append(Proposal("tidy", {"type": "tidy"},
                                      f"{items} items on the map slow the game: worn-out clothes lying about "
                                      "go to the garbage dump", 6))
        # (0.104.0) old remains rot away: non-entombed corpses and body parts
        # nobody can craft with (DFHack deteriorate; stays on in the save)
        # (0.104.115) the census says what lies about: thousands of butchered
        # bones and shells, or worn clothes thrown down, rot away too
        ground = {str(_d(x).get("name")): int(_d(x).get("n") or 0)
                  for x in _l(_d(cen.get("items")).get("on_ground"))}
        extra = []
        if ground.get("CORPSEPIECE", 0) >= cfg["prune_parts_min"]:
            extra.append("usable-parts")
        worn = {str(_d(x).get("name")): int(_d(x).get("n") or 0) for x in _l(_d(cen.get("items")).get("worn"))}
        if sum(worn.get(k, 0) for k in ("SHOES", "GLOVES", "PANTS", "ARMOR", "HELM")) >= cfg["prune_worn_min"]:
            extra.append("clothes")
        # (0.104.116) spider webs by the thousand: cleared, once a season at most
        webs = _d(_d(cen.get("items")).get("counts")).get("webs")
        last_w = memory.last_fired.get("webs") if memory is not None else None
        if (isinstance(webs, int) and webs >= cfg["webs_clear_min"]
                and (last_w is None or not 0 <= abs_tick(s) - last_w < 84 * TICKS_PER_DAY)):
            proposals.append(Proposal("webs", {"type": "clear_webs"},
                                      f"{webs} spider webs lie in the caverns, a big share of the {items} items "
                                      "slowing the game: clear them (DFHack's clear-webs)", 7))
        action = {"type": "prune_remains"}
        if extra:
            action["extra"] = extra
        what = (" (and " + ", ".join({"usable-parts": f"{ground.get('CORPSEPIECE', 0)} bones, shells and hair on the "
                                                       "ground", "clothes": "worn clothes thrown down"}[e]
                                      for e in extra) + ")") if extra else ""
        proposals.append(Proposal("prune", action,
                                  f"{items} items on the map slow the game: old corpses and useless body "
                                  f"parts lying about rot away{what} (entombed dead are kept)", 7))


def _kiln_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.86) What a kiln makes (DF's reaction_other raws, read from the game):
    plaster powder for the hospital's casts (a gypsum boulder and an empty
    bag, with fuel) and the library's writing materials, one step a cycle:
    quicklime (a calcium carbonate boulder, a bag, fuel) at the kiln -> milk
    of lime (quicklime and an empty bucket) at the ashery -> parchment (a
    fresh hide and milk of lime) at the tanner's -> a blank quire (a sheet)
    at a Craftsdwarf's workshop. A kiln and a tanner's are built when
    missing and there is stone for them. Tanners take fresh hides for
    leather by themselves, so parchment only gets what they leave."""
    sup = _d(s.get("supplies"))
    if "gypsum" not in sup or young_fort(s, cfg):
        return
    b = s["buildings"]
    hosp, lib = _location(s, "HOSPITAL"), _location(s, "LIBRARY")
    powder_short = _location_short(hosp, ("powder",)).get("powder") if hosp else None
    paper_short = _location_short(lib, ("paper",)).get("paper") if lib else None
    need_plaster = bool(powder_short) and (sup.get("plaster") or 0) == 0 and (sup.get("gypsum") or 0) > 0
    need_paper = bool(paper_short) and (sup.get("blank_quires") or 0) < paper_short[1] - paper_short[0]
    if not (need_plaster or need_paper):
        return
    chain = ("make_plaster_powder", "make_quicklime", "make_milk_of_lime", "make_parchment", "make_quire")
    if any(queued(s, {r}) for r in chain):
        return
    bags, buckets, fuel = int(sup.get("empty_bags") or 0), int(sup.get("buckets") or 0), int(sup.get("fuel") or 0)
    missing = []
    if not _has_shop(b, "Kiln") and (need_plaster or (sup.get("calcium_carbonate") or 0) > 0):
        missing.append("Kiln")
    if need_paper and not _has_shop(b, "Tanners") and (sup.get("calcium_carbonate") or 0) > 0:
        missing.append("Tanners")
    if missing:
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            why = []
            if need_plaster:
                why.append(f"plaster powder for the hospital ({sup.get('gypsum')} gypsum boulders)")
            if need_paper:
                why.append("writing materials for the library")
            proposals.append(Proposal("kiln", {"type": "start_project", "kind": "workshops", "shops": missing},
                                      f"{' and '.join(why)}: build {', '.join(missing)}", 6))
        return
    step = None
    if need_plaster and _has_shop(b, "Kiln"):
        if bags and fuel:
            step = ("make_plaster_powder", 1, f"the hospital has {powder_short[0]} of {powder_short[1]} plaster "
                                               f"powder for casts: burn a gypsum boulder into plaster")
        else:
            notes.append(f"plaster for the hospital waits for an empty bag ({bags}) and fuel ({fuel})")
    if step is None and need_paper:
        short = paper_short[1] - paper_short[0] - (sup.get("blank_quires") or 0)
        sheets, milk, hides = int(sup.get("sheets") or 0), int(sup.get("milk_of_lime") or 0), int(sup.get("hides") or 0)
        lime, caco3 = int(sup.get("quicklime") or 0), int(sup.get("calcium_carbonate") or 0)
        if sheets and _has_shop(b, "Craftsdwarfs"):
            step = ("make_quire", min(sheets, short, 5), f"the library has {paper_short[0]} of {paper_short[1]} "
                                                          f"writing materials: bind {min(sheets, short, 5)} sheet(s) into quires")
        elif milk and hides and _has_shop(b, "Tanners"):
            step = ("make_parchment", min(milk, hides, short, 5), "parchment for the library from fresh hides")
        elif milk and not hides:
            notes.append("parchment for the library waits for a fresh hide (the tanners take them for leather)")
        elif lime and buckets and _has_shop(b, "Ashery"):
            step = ("make_milk_of_lime", min(lime, short, 3), "milk of lime (for parchment) from quicklime")
        elif caco3 and bags and fuel and _has_shop(b, "Kiln"):
            step = ("make_quicklime", min(caco3, short, 3), "quicklime (for parchment) from limestone")
        elif not caco3:
            notes.append("no limestone, marble, chalk or dolomite boulders for quicklime: the library's paper "
                         "would have to come from plants at a quern and screw press (not made by the AI yet)")
        elif not bags:
            notes.append("quicklime for the library's paper waits for an empty bag")
    if step:
        recipe, amount, what = step
        proposals.append(Proposal("kiln", {"type": "work_order", "recipe": recipe, "amount": max(1, amount)},
                                  what, 5, True))


def _soap_rule(s: dict, cfg: dict, proposals: list, notes: list, say, memory=None) -> None:
    """Soap for the hospital (wounds cleaned with it don't fester): tallow
    (fat rendered at the kitchen) and lye (ash from the wood furnace, through
    the ashery into a bucket) at a soap maker's workshop, one step a cycle.
    Without fat or tallow there is nothing to make it from: bought from the
    caravans instead (trade_wants)."""
    sup = _d(s.get("supplies"))
    if "ash" not in sup:                      # an older bridge: just say it
        if (sup.get("soap") or 0) == 0:
            say("no soap for the hospital (wounds get infected): it needs lye and tallow at a soap maker's workshop")
        return
    soap = int(sup.get("soap") or 0)
    # (0.104.37) and the bars the hospital keeps (its location stock, 150 a bar):
    # the loose count alone kept the fat ban and the soap orders on for good
    hosp = _location(s, "HOSPITAL")
    if hosp is not None:
        soap += int(_d(hosp.get("have")).get("soap") or 0) // LOCATION_UNITS["soap"]
    # (0.104.121) more kept while many wounds fester (Teacheroar: 29 infected,
    # 5 kept, a bar made at a time and used up as it came)
    keep = max(cfg["soap_keep"], min(cfg["soap_keep_max"], math.ceil(
        int(_d(s.get("health")).get("infected") or 0) / cfg["infected_per_soap"])))
    if soap >= keep:
        if memory is not None and memory.fat_ban:
            proposals.append(Proposal("fat_ban", {"type": "kitchen_fat", "ban": False},
                                      f"{soap} soap kept: fat and tallow may be cooked again", 5))
        return
    tallow, fat = int(sup.get("tallow") or 0), int(sup.get("fat") or 0)
    # (0.104.30) the cooks ate the soap's fat and tallow (Enxah: 149 fat, then
    # 13 tallow, gone into meals): kept from the kitchens while wounds fester
    # (a week apart, so new kinds from the butcher are kept too)
    if memory is not None and (tallow or fat) and int(_d(s.get("health")).get("infected") or 0) > 0:
        proposals.append(Proposal("fat_ban", {"type": "kitchen_fat", "ban": True},
                                  f"{tallow} tallow and {fat} fat for soap, wounds infected and no soap: keep them "
                                  "from the cooks", 3))
    ash, lye = int(sup.get("ash") or 0), int(sup.get("lye") or 0)
    if tallow == 0 and fat == 0:
        # (0.104.7) fat comes from butchering: one spare tame animal to the
        # butcher while wounds fester (Enxah: 7 infected, 42 tame animals,
        # no soap all year); a fort of Beast-friends never slaughters
        infected = int(_d(s.get("health")).get("infected") or 0)
        tame = int(_d(s.get("others_on_map")).get("tame_animals") or 0)
        if (soap == 0 and infected > 0 and tame >= cfg["slaughter_min_tame"] and _has_shop(s["buildings"], "Butchers")
                and not (memory is not None and has_rule(getattr(memory, "culture", None), "no_slaughter"))):
            proposals.append(Proposal("slaughter", {"type": "slaughter_one"},
                                      f"{infected} infected wound(s), no soap and no fat to make it from: one spare "
                                      f"tame animal of the {tame} to the butcher (its fat becomes tallow, then soap)", 4))
        if soap == 0:
            say("no soap for the hospital (wounds get infected), and no tallow to make it from (fat comes from "
                "butchered animals): the AI buys soap from the caravans meanwhile")
        return
    b = s["buildings"]
    missing = [w for w in ("Ashery", "SoapMaker") if not _has_shop(b, w)]
    if not _has_shop(b, "WoodFurnace"):
        missing.append("WoodFurnace")
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if missing:
        infected = int(_d(s.get("health")).get("infected") or 0)
        # (0.104.14) festering wounds don't wait behind another workshops level
        # (Enxah, spring y62: a kiln level at 0 of 47 tiles since winter held
        # the soap shops back, 149 fat, 8 infected wounds) unless one being
        # dug brings them already
        coming = set()
        for p in open_:
            if p.get("kind") == "workshops":
                coming |= set(_l(_d(p.get("summary")).get("workshops"))) | set(_d(p.get("furniture")).keys())
        # (0.104.14) the fat rendered into tallow at the kitchen meanwhile
        # (the first step, and fat rots in the stores)
        if (infected and fat and not tallow and _has_shop(b, "Kitchen")
                and not queued(s, {"render_fat"})):
            proposals.append(Proposal("soap", {"type": "work_order", "recipe": "render_fat", "amount": min(fat, 5)},
                                      f"{infected} infected wound(s) and no soap: render {min(fat, 5)} fat into tallow "
                                      "while the soap maker's workshops come", 4, True))
        if infected and coming & {"Ashery", "SoapMaker"}:
            return
        if not _workshops_busy(open_) or infected:
            # (0.104.11) with wounds festering the workshops take the urgent slot
            # (Enxah: refused 7 times for want of a building slot, held 64 days,
            # 27 tallow waiting and 7 infected wounds)
            action = {"type": "start_project", "kind": "workshops", "shops": missing}
            if infected:
                action["urgent"] = True
            proposals.append(Proposal("soap", action,
                                      f"{soap} soap for the hospital and {tallow + fat} tallow or fat to make it: "
                                      f"build {', '.join(missing)}" + (f" ({infected} wounds infected: urgent)" if infected else ""),
                                      3 if infected else 5))
        return
    # (0.104.32) each step waits only on its own order: a render_fat order
    # left with no fat to render (Enxah, summer y63: 25 tallow, 5 ash, 29
    # buckets, 16 infected wounds) held the lye and the soap back for weeks
    need = keep - soap
    steps = []
    if lye and tallow:
        steps.append(("make_soap_from_tallow", min(lye, tallow, need), "make soap from lye and tallow"))
    if fat and not tallow:
        steps.append(("render_fat", min(fat, 5), f"render {min(fat, 5)} fat into tallow"))
    if not lye and ash and (sup.get("buckets") or 0) > 0:
        steps.append(("make_lye", min(ash, need), "make lye from ash"))
    if lye + ash < need and (_d(s.get("stocks")).get("wood") or 0) >= 10:
        # (0.104.121) ash for the next bars too, not only when there is none
        # (Teacheroar: 1 ash, so one bar of lye, then one of soap, at a time)
        steps.append(("make_ash", min(5, need - lye - ash), "burn wood to ash (for lye)"))
    if fat and 0 < tallow < need:
        steps.append(("render_fat", min(fat, 5), f"render {min(fat, 5)} fat into tallow"))
    step = next((st for st in steps if not queued(s, {st[0]})), None)
    if step is None:
        return
    recipe, amount, what = step
    proposals.append(Proposal("soap", {"type": "work_order", "recipe": recipe, "amount": max(1, amount)},
                              f"{soap} soap for the hospital (lye {lye}, tallow {tallow}, fat {fat}, ash {ash}): {what}",
                              3 if int(_d(s.get("health")).get("infected") or 0) else 5, True))


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
    if need is None:
        ask_player(notes, f"{waiting} grazing animals have no pasture and will starve: make a pasture zone "
                   "on grass; the AI puts animals in it")
        return
    if memory.pasture_failure:
        ask_player(notes, f"{waiting} grazing animals have no pasture and will starve, and the AI couldn't "
                   f"make one: {memory.pasture_failure}. Make a pasture zone on grass and the AI will fill it")
    # room for the herd to grow with Husbandry ("large herds")
    tiles = math.ceil(need * cfg["pasture_margin"] * max(1.0, factor(traits, "husbandry")))
    tiles = max(9, min(600, tiles))
    proposals.append(Proposal("new_pasture", {"type": "make_pasture", "tiles": tiles},
                              f"{waiting} grazing animal(s) need about {need} tiles of grass and "
                              + ("no pasture has room" if so.get("pastures") else "there is no pasture")
                              + f": make a {tiles}-tile pasture on grass near the fort", 3))


LABOR_MODES_FIXED = ("EverybodyDoesThis", "NobodyDoesThis")


INDUSTRY_SHOPS = ["WoodFurnace", "Smelter", "MetalsmithsForge"]


def _industry_rules(s: dict, memory, cfg: dict, citizens: int, proposals: list, notes: list) -> None:
    """Metal: once ore is uncovered near the fort, the furnaces and forge;
    a vein of the most wanted metal mined while bars run low; charcoal for
    the smelter. Smelting itself is DFHack's smelting orders (_smelting_rule)."""
    ores = {k: v for k, v in _d(_d(s.get("industry")).get("ores")).items() if isinstance(v, dict)}
    if not ores or young_fort(s, cfg) and not has_farms(s):
        return
    b = s["buildings"]
    missing = [w for w in INDUSTRY_SHOPS if not _has_shop(b, w)]
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if missing and not _workshops_busy(open_):
        best = next((m for m in GEAR_ORDER_METALS if m in ores), next(iter(ores)))
        proposals.append(Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": missing},
                                  f"{ores[best]['tiles']} tiles of {best.lower()} ore uncovered near the fort: "
                                  f"dig and build {', '.join(missing)} to turn it into metal", 5))
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    total = sum(v for v in bars.values() if isinstance(v, (int, float)))
    lb = _d(s.get("labor"))
    stock = _d(s.get("industry")).get("ore_stock") or 0
    mp = mining_plan(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)   # (0.96) Mining
    if (mp["veins"] and total < mp["bars_below"] and (lb.get("dig") or 0) < 50 and (lb.get("miners") or 0) > 0
            and stock < mp["ore_stock_max"]):
        metal = next((m for m in GEAR_ORDER_METALS if m in ores), None)
        if metal:
            proposals.append(Proposal("ore", {"type": "mine_ore", "metal": metal, "count": mp["vein_tiles"]},
                                      f"only {total} bars of weapon-grade metal and {ores[metal]['tiles']} tiles of "
                                      f"{metal.lower()} ore uncovered: mine the vein", 5))
    elif not mp["veins"] and total < cfg["smelt_when_bars_below"]:
        notes.append(f"only {total} bars of weapon-grade metal, but Mining is low: no vein mined (metal by trade)")
    su, st = _d(s.get("supplies")), _d(s.get("stocks"))
    furnaces = _d(b.get("furnaces"))
    # Coke from coal first (bituminous coal 9 bars, lignite 5, one fuel a job):
    # far more fuel than charcoal, and no wood burnt
    coal = sorted(((int(_d(v).get("n") or 0), k) for k, v in _d(_d(s.get("stone_use")).get("economic")).items()
                   if k in COAL_STONES and int(_d(v).get("n") or 0) > 0), reverse=True)
    coke_made = False
    # (0.100.1, review) waiting coke orders go only at twice the threshold:
    # at 39/40 fuel they were ordered and cancelled by turns
    if (su.get("fuel") or 0) >= 2 * cfg["coke_when_fuel_below"]:
        # fuel enough: the AI's coke orders still waiting go (0.54 piled a dozen
        # on the one smelter, ahead of pig iron and steel)
        waiting = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
                   and o.get("recipe") in COAL_STONES.values() and (o.get("amount_left") or 0) > 0]
        if waiting:
            proposals.append(Proposal("fuel_trim", {"type": "cancel_work_order", "order_id": waiting[0]["id"]},
                                      f"{su.get('fuel')} charcoal and coke in stock and {len(waiting)} coke order(s) "
                                      "still waiting: cancel one (the smelter has other work)", 5))
    if (furnaces.get("Smelter") and "fuel" in su and 0 < (su.get("fuel") or 0) < cfg["coke_when_fuel_below"]
            and coal and not queued(s, set(COAL_STONES.values()), ai_only=True)):
        n, k = coal[0]
        amount = max(1, min(n, cfg["coke_batch"], (su.get("fuel") or 0)))
        p = Proposal("fuel", {"type": "work_order", "recipe": COAL_STONES[k], "amount": amount},
                     f"only {su.get('fuel') or 0} charcoal or coke and {n} {k.lower().replace('_', ' ')} "
                     f"dug: make coke from {amount}", 4, True)
        # refused (a game without that reaction): charcoal meanwhile
        if memory is None or _refused_wait(memory, p, abs_tick(s)) is None:
            proposals.append(p)
            coke_made = True
    if (furnaces.get("Smelter") and "fuel" in su and (su.get("fuel") or 0) < cfg["fuel_min"] and not coke_made
            and (st.get("wood") or 0) >= 20 and furnaces.get("WoodFurnace") and not queued(s, {"make_charcoal"})):
        proposals.append(Proposal("fuel", {"type": "work_order", "recipe": "make_charcoal", "amount": 10},
                                  f"only {su.get('fuel') or 0} charcoal or coke for the smelter: burn some wood", 5, True))
    # Smelting: the AI's own orders, one ore stone and one charcoal a bar.
    # DFHack's smelting library (imported since 0.42) only smelts with 100
    # charcoal in stock: region2 sat on 89 ore and 15 charcoal for a season.
    by_ore = {k: v for k, v in _d(_d(s.get("industry")).get("ore_stock_by")).items() if isinstance(v, dict)}
    fuel = su.get("fuel") or 0
    # (0.97) the Rules switch "Smelt ore when metal runs low" (it was DFHack's
    # smelting library only, which current bridges no longer use)
    # (0.104.96) a magma smelter needs no fuel
    magma = bool(furnaces.get("MagmaSmelter"))
    if ((furnaces.get("Smelter") or magma) and by_ore and (fuel > 0 or magma) and total < cfg["smelt_when_bars_below"]
            and player_rules(s)["import_smelting"] and not queued(s, {"smelt_ore"}, ai_only=True)):
        def rank(item):
            ore, v = item
            metals = [m for m in _l(v.get("metals")) if isinstance(m, str)]
            order = min((GEAR_ORDER_METALS.index(m) for m in metals if m in GEAR_ORDER_METALS), default=99)
            return (order, -int(v.get("n") or 0), ore)
        ore, v = min(by_ore.items(), key=rank)
        amount = max(1, min(int(v.get("n") or 0), fuel if not magma else 99, cfg["smelt_batch"]))
        metals = ", ".join(m.lower() for m in _l(v.get("metals")))
        proposals.append(Proposal("smelt", {"type": "work_order", "recipe": "smelt_ore", "amount": amount,
                                            "material": f"INORGANIC:{ore}"},
                                  f"{v.get('n')} {ore.lower()} ore waiting and only {total} bars of weapon-grade "
                                  f"metal: smelt {amount} into {metals}", 4, True))
    _steel_rule(s, cfg, bars, furnaces, fuel, proposals, notes)


def _steel_rule(s: dict, cfg: dict, bars: dict, furnaces: dict, fuel: int, proposals: list, notes: list) -> None:
    """Steel, the best gear metal, from iron in two steps at the smelter:
    pig iron (an iron bar, flux stone, fuel), then steel (a pig iron bar, an
    iron bar, flux, fuel: two steel bars). Some iron is always kept back
    for gear made now; steel is made while there's less than the gear wants."""
    gear = _d(_d(s.get("military")).get("gear"))
    flux = int(_d(s.get("industry")).get("flux_stock") or 0)
    iron, pig, steel = int(bars.get("IRON") or 0), int(gear.get("pig_iron") or 0), int(bars.get("STEEL") or 0)
    magma = bool(furnaces.get("MagmaSmelter"))     # (0.104.96) no fuel needed there
    if not (furnaces.get("Smelter") or magma) or not player_rules(s)["make_gear"] or steel >= cfg["steel_want"]:
        return
    if queued(s, {"pig_iron", "steel"}, ai_only=True):
        return
    spare_iron = iron - cfg["iron_keep"]
    if spare_iron <= 0 or (fuel <= 0 and not magma):
        return
    if flux <= 0:
        if iron >= cfg["iron_keep"] + 4:
            notes.append(f"{iron} iron bars and no flux stone (limestone, dolomite, marble, chalk, calcite) "
                         "dug: no steel until some is")
        return
    if pig < 1:
        n = max(1, min(spare_iron // 2, flux, fuel if not magma else 99, cfg["steel_batch"]))
        proposals.append(Proposal("steel", {"type": "work_order", "recipe": "pig_iron", "amount": n},
                                  f"{iron} iron bars and {flux} flux stone: make {n} pig iron (the first step "
                                  "to steel)", 5, True))
    else:
        n = max(1, min(pig, spare_iron, flux, fuel if not magma else 99, cfg["steel_batch"]))
        proposals.append(Proposal("steel", {"type": "work_order", "recipe": "steel", "amount": n},
                                  f"{pig} pig iron, {iron} iron bars and {flux} flux stone: make steel "
                                  f"({2 * n} bars)", 5, True))


def _bottleneck_rule(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """One workshop with a long queue of the AI's orders while dwarves stand
    idle (region2's one smelter: coke, pig iron, steel and ore, 40% idle):
    another workshop of that kind, through a workshops level."""
    # (0.103.1) under the urgent drink line a second still comes young fort or
    # not, idle hands or not (Enxah: 18 dwarves, 1 still, 28 brews queued,
    # drink 0-8 for a year)
    thirsty = int(_d(s.get("stocks")).get("drink") or 0) < citizens * cfg["urgent_drink_per_dwarf"]
    if young_fort(s, cfg) and not thirsty:
        return
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    if idle < cfg["idle_share"] and not thirsty:
        return
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if _workshops_busy(open_):
        return
    b = _d(s.get("buildings"))
    places = {**_d(b.get("workshops")), **_d(b.get("furnaces"))}
    backlog: dict[str, int] = {}
    for o in _l(s.get("orders")):
        if not isinstance(o, dict) or not o.get("by_ai"):
            continue
        shop = RECIPE_SHOPS.get(str(o.get("recipe"))) or JOB_SHOPS.get(str(o.get("job")))
        if shop:
            backlog[shop] = backlog.get(shop, 0) + max(0, int(o.get("amount_left") or 0))
    # (0.104.137) stills and kitchens past the cap while drink or meals run short
    # (Teacheroar: 6 stills and 7 kitchens against a cap of 5 at 221 dwarves)
    st_ = _d(s.get("stocks"))
    short_ = {"Still": int(st_.get("drink") or 0) < citizens * cfg["drink_per_dwarf"],
              "Kitchen": int(st_.get("prepared_meals") or 0) < citizens * cfg["meals_per_dwarf"]}
    def cap_(shop):
        return shops_max(cfg, citizens) * (2 if short_.get(shop) else 1)
    worst = sorted(((n / max(1, places.get(shop, 0)), n, shop) for shop, n in backlog.items()
                    if shop in BUILDABLE_SHOPS and places.get(shop, 0) >= 1
                    and places.get(shop, 0) < cap_(shop)), reverse=True)
    if thirsty and (young_fort(s, cfg) or idle < cfg["idle_share"]):
        worst = [w for w in worst if w[2] == "Still"]       # only the still, for the thirsty
    need = cfg["shop_backlog"]
    if thirsty and worst and worst[0][2] == "Still":
        need = cfg["thirsty_still_backlog"]                 # (Enxah: 12 brews on one still, drink 13 for 18)
    if worst and worst[0][0] >= need:
        _, n, shop = worst[0]
        # (0.99.4) drink and food first: a still or kitchen goes ahead of the
        # craft shops wanted for needs (one workshops level at a time)
        proposals.append(Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": [shop],
                                                 **({"urgent": True} if thirsty and shop == "Still" else {})},
                                  f"{n} jobs of the AI's orders wait on {places.get(shop)} {shop} and "
                                  f"{round(100 * idle)}% of the dwarves are idle: build another",
                                  3 if shop in ("Still", "Kitchen") else 6))


def drink_short(s: dict, cfg: dict) -> bool:
    """(0.99.6) Under the urgent drink line and little a still can brew."""
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    sup = _d(s.get("supplies"))
    brewable = int(sup.get("brewable_plants") or 0) + int(sup.get("brewable_growths") or 0)
    return drink < citizens * cfg["urgent_drink_per_dwarf"] and brewable < citizens


def _crop_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.99.6) Crops for drink: while drink is short, autofarm's thresholds
    favour the crops a still can brew (the fort has seeds of) and hold back
    the rest; put back to autofarm's default once drink has recovered.
    region2: 18 of 151 plants brewable, drink 42 for 243 dwarves."""
    if memory is None:
        return
    farms = _d(s.get("farms"))
    crops = {k: v for k, v in _d(farms.get("crops")).items() if isinstance(v, dict)}
    if not crops or not has_farms(s):
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    # crops a plot can grow: seeds in stock and a season (trees have none)
    seeded = {k: v for k, v in crops.items() if int(v.get("seeds") or 0) > 0
              and (v.get("seasons") is None or _l(v.get("seasons")))}
    brew = sorted(k for k, v in seeded.items() if v.get("brews"))
    if drink_short(s, cfg):
        # (0.99.6) region2: 10 plots, all underground, nothing planted (25
        # plump helmet seeds, 3 cave wheat) while 500+ seeds of brewable
        # surface crops waited: plots on the surface's soil for them
        under_brew = sum(int(v.get("seeds") or 0) for k, v in seeded.items() if v.get("brews") and v.get("underground"))
        surface_brew = sum(int(v.get("seeds") or 0) for k, v in seeded.items()
                           if v.get("brews") and not v.get("underground"))
        plots_under = int(farms.get("plots_underground") or 0)
        if (int(farms.get("plots_surface") or 0) == 0 and surface_brew >= cfg["surface_farm_seeds"]
                and under_brew < plots_under * cfg["seeds_per_plot"]):
            n = min(cfg["surface_farm_tiles"], surface_brew)
            proposals.append(Proposal("surface_farm", {"type": "farm_plots", "tiles": n, "dig": False, "outside": True},
                                      f"drink is short ({drink} for {citizens}): the {plots_under} plots are "
                                      f"underground with {under_brew} seeds of underground crops to brew, and "
                                      f"{surface_brew} seeds of surface crops wait: lay out {n} tiles of plots "
                                      "on the surface's soil for them", 2))
        if not brew:
            ask_player(notes, f"drink is short ({drink} for {citizens}) and the fort has no seeds of a crop a "
                       "still can brew: buy seeds or brewable plants from a caravan (the dwarves gather shrubs "
                       "meanwhile)")
            return
        if memory.farm_steer == "drink":
            notes.append("the farms grow brewable crops while drink is short: " + ", ".join(
                f"{_d(crops[k]).get('name') or k.lower()} ({crops[k].get('seeds')} seeds)" for k in brew[:4]))
            return
        th = {k: cfg["crop_brew_threshold"] for k in brew}
        th.update({k: cfg["crop_other_threshold"] for k in seeded if k not in th})
        proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": "drink"},
                                  f"drink is short ({drink} for {citizens}): farm the crops a still can brew ("
                                  + ", ".join(_d(crops[k]).get("name") or k.lower() for k in brew[:4])
                                  + ") ahead of the rest (autofarm's thresholds)", 2))
    elif memory.farm_steer == "drink" and drink >= citizens * cfg["drink_recovered_per_dwarf"]:
        th = {k: cfg["crop_default_threshold"] for k in seeded}
        if th:
            proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": ""},
                                      f"drink has recovered ({drink} for {citizens}): the farms go back to "
                                      "autofarm's own choice of crops", 5))
    else:
        # (0.104.79) plots left fallow: autofarm plants a crop only while its
        # stock is under the threshold, and its default (50) is a small fort's
        # (Enxah, 88 dwarves: 12 plots, none planted this season, 131 plump
        # helmet seeds, 73 in stock, the stills short of plants for the
        # winter's drink): thresholds that grow with the fort, more for the
        # brewable crops
        plots = int(farms.get("plots") or farms.get("built") or 0)
        planted = sum(int(v.get("planted") or 0) for v in crops.values())
        if plots and planted * 2 < plots and seeded and memory.farm_steer != "pop":
            th = {k: max(cfg["crop_default_threshold"], citizens * cfg["crop_per_dwarf"]) for k in seeded}
            th.update({k: max(cfg["crop_default_threshold"], citizens * cfg["crop_brew_per_dwarf"]) for k in brew})
            proposals.append(Proposal("crops", {"type": "farm_thresholds", "thresholds": th, "steer": "pop"},
                                      f"{plots - planted} of {plots} farm plots lie fallow this season (autofarm's "
                                      f"thresholds are a small fort's): keep more of each crop for {citizens} "
                                      "dwarves, the brewable ones most", 4))


def _kitchen_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.100) Cooking eats brewable plants and fruit and keeps no seed
    (brewing keeps it): while drink is short the kitchen may not cook them;
    the ban is lifted once drink has recovered (only the AI's own bans)."""
    if memory is None:
        return
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = int(_d(s.get("stocks")).get("drink") or 0)
    if drink_short(s, cfg) and not memory.kitchen_ban:
        proposals.append(Proposal("kitchen", {"type": "kitchen_brewables", "ban": True},
                                  f"drink is short ({drink} for {citizens}): the kitchen stops cooking the "
                                  "plants and fruit a still can brew (cooking keeps no seed)", 2))
    elif memory.kitchen_ban and drink >= citizens * cfg["drink_recovered_per_dwarf"]:
        proposals.append(Proposal("kitchen", {"type": "kitchen_brewables", "ban": False},
                                  f"drink has recovered ({drink} for {citizens}): the kitchen may cook "
                                  "brewable plants again", 5))


def _fishery_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(0.99.4) Raw fish piling up and no fishery to clean them: only a young
    fort got one (region2: 7940 raw fish at 228 dwarves, meals for the
    lavish cooks cancelled for want of meat or fish)."""
    b = _d(s.get("buildings"))
    if _has_shop(b, "Fishery") or int(_d(s.get("stocks")).get("raw_fish") or 0) < cfg["fishery_raw_fish"]:
        return
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if _workshops_busy(open_):
        return
    n = int(_d(s.get("stocks")).get("raw_fish") or 0)
    for p in proposals:                    # one workshops level: join the still or kitchen's
        if p.rule == "bottleneck" and p.action.get("kind") == "workshops":
            p.action["shops"] = list(p.action.get("shops") or []) + ["Fishery"]
            p.reason += f"; and a fishery for {n} raw fish"
            p.priority = min(p.priority, 3)
            return
    proposals.append(Proposal("fishery", {"type": "start_project", "kind": "workshops", "shops": ["Fishery"]},
                              f"{n} raw fish and no fishery to clean them for the kitchen: build one", 3))


def _bench_coffins_rule(s: dict, memory, proposals: list) -> None:
    """(0.104.21) A tomb level waits for coffins and the AI's coffin order has
    made no job at a workshop for 3 days (Enxah: 29 coffins ordered, none
    started in two game months, 106 dead unburied): coffin jobs put straight
    on a mason's bench (a carpenter's while stone is short), 5 at a time."""
    if memory is None or not jobs_reported(s):
        return
    waiting = sum(int(_d(_d(p.get("furnish")).get("waiting")).get("Coffin") or 0)
                  for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict))
    if waiting <= 0:
        return
    now = abs_tick(s)
    idle = []
    for o in _l(s.get("orders")):
        if (isinstance(o, dict) and o.get("by_ai") and str(o.get("recipe") or "").endswith("_coffin")
                and not (_d(o.get("jobs")).get("n") or 0)):
            w = _d(memory.order_watch.get(str(o.get("id"))))
            if isinstance(w.get("since"), int) and now - w["since"] >= 3 * TICKS_PER_DAY:
                idle.append(o)
    if not idle:
        return
    material = "wood" if stone_short(s, 5) else "stone"
    action = {"type": "bench_jobs", "kind": "coffin", "count": min(5, waiting), "material": material}
    if material == "stone" and masons_jammed(s):
        action["make_room"] = True             # (0.104.32) lift autoslab's stuck engrave jobs
    proposals.append(Proposal("coffins", action,
                              f"a tomb level waits for {waiting} coffin(s) and the AI's coffin order has made no job "
                              f"in {(now - _d(memory.order_watch.get(str(idle[0].get('id')))).get('since', now)) // TICKS_PER_DAY} "
                              f"days: put {min(5, waiting)} straight on a {'carpenter' if material == 'wood' else 'mason'}'s bench", 3))


STONE_CRAFTS = ("crafts", "ring", "bracelet", "earring", "amulet", "figurine", "mug", "scepter", "crown", "goblet")


def order_shop(recipe) -> str | None:
    """(0.104.23) The workshop an AI order is made at, where it's sure: the
    table above, then stone furniture and blocks at the mason's."""
    r = str(recipe or "")
    shop = recipe_shop(r)
    if shop:
        return shop
    if r.startswith("stone_"):
        return "Craftsdwarfs" if any(r.endswith(k) or k in r for k in STONE_CRAFTS) else "Masons"
    return None


def _order_slots_rule(s: dict, proposals: list) -> None:
    """(0.104.23) A workshop whose order slots ("max general orders") are all
    held by jobs nobody is on, while the AI's orders for it get no job:
    five more slots (to 15 at most). Enxah's masons: autoslab's 5 engrave
    jobs waited 250 days for blank slabs and held every slot, so the AI's
    slab, coffin and block orders never reached the bench."""
    if not jobs_reported(s):
        return
    waiting = {}
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and o.get("active") and not (_d(o.get("jobs")).get("n") or 0):
            shop = order_shop(o.get("recipe"))
            if shop:
                waiting.setdefault(shop, []).append(str(o.get("recipe")))
    for w in _l(_d(s.get("order_desk")).get("workshops")):
        if not isinstance(w, dict) or not isinstance(w.get("job_list"), list):
            continue
        mx = int(w.get("max_orders") or 0)
        from_orders = [j for j in w["job_list"] if isinstance(j, dict) and j.get("order")]
        if (mx and mx < 15 and len(from_orders) >= mx and not any(j.get("worker") for j in from_orders)
                and waiting.get(str(w.get("type")))):
            proposals.append(Proposal("order_slots", {"type": "order_slots", "workshop_id": w.get("id"),
                                                      "max": min(15, mx + 5)},
                                      f"the {w.get('type')} workshop's {mx} order slots are all held by jobs nobody is "
                                      f"on ({', '.join(sorted({str(j.get('type')) for j in from_orders}))}) while the "
                                      f"AI's {', '.join(sorted(set(waiting[str(w.get('type'))]))[:3])} get none: "
                                      f"{min(15, mx + 5)} slots", 2))
            return


def _orphan_jobs_rule(s: dict, proposals: list) -> None:
    """(0.104.34) Jobs left on the benches by work orders that are gone (the
    AI cancels a stuck order, DF keeps its jobs, unworked for good: Enxah's
    three craftsdwarf's held 14 such jewellery and craft jobs while 21 dwarves
    badly wanted to craft): taken off."""
    n = int(_d(s.get("order_desk")).get("orphan_jobs") or 0)
    if n > 0:
        proposals.append(Proposal("orphan_jobs", {"type": "clear_orphan_jobs"},
                                  f"{n} job(s) wait on the workshops' benches for work orders that are gone: take "
                                  "them off, so the benches take new work", 3))


def _unsuspend_rule(s: dict, proposals: list) -> None:
    """(0.104.13) The AI's own orders whose jobs a workshop suspended: taken
    up again (the player's "resume"). An order's suspended job never moves by
    itself, so it was cancelled as stuck after 28 days and placed again, round
    and round (Enxah: the wooden bucket 31 times while patients waited for
    water). Never a construction or a player's job (the bridge checks)."""
    held = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
            and (_d(o.get("jobs")).get("suspended") or 0) > 0]
    if not held:
        return
    what = sorted({str(o.get("recipe") or o.get("job")) for o in held})
    proposals.append(Proposal("unsuspend", {"type": "unsuspend_orders"},
                              f"{len(held)} of the AI's work order(s) have a suspended job ({', '.join(what[:4])}): "
                              "resume them", 3))


def _approve_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.101.2) The AI's own orders the manager hasn't approved in
    `approve_after_days` (no working office yet: an office needs a chair, a
    chair needs an approved order) are approved by the AI itself."""
    if memory is None:
        return
    now = abs_tick(s)
    waiting = []
    for o in _l(s.get("orders")):
        if isinstance(o, dict) and o.get("by_ai") and o.get("validated") is False:
            w = _d(memory.order_watch.get(str(o.get("id"))))
            if isinstance(w.get("since"), int) and now - w["since"] >= cfg["approve_after_days"] * TICKS_PER_DAY:
                waiting.append(o)
    # (0.101.4) no order in the fort has started at all (none active) after
    # `approve_after_days`+2 days: the manager has no office chair to hand them
    # out from. One chair is made straight at a workshop.
    mine = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")]
    if mine and not any(isinstance(o, dict) and o.get("active") for o in _l(s.get("orders"))):
        old = [o for o in mine if isinstance(_d(memory.order_watch.get(str(o.get("id")))).get("since"), int)
               and now - memory.order_watch[str(o.get("id"))]["since"] >= (cfg["approve_after_days"] + 2) * TICKS_PER_DAY]
        if old:
            proposals.append(Proposal("bootstrap_chair", {"type": "bootstrap_chair"},
                                      f"none of the fort's {len(mine)} AI work orders has started: the manager hands "
                                      "orders out only from an office with a chair, and the chair waits on an order. "
                                      "Make one chair straight at a workshop", 1))
    if waiting:
        # (0.104.71) say why as it is: Enxah's manager has an office with a chair
        # and is busy hauling, so "no working office" was wrong
        offices = [x for x in _l(_d(s.get("order_desk")).get("offices")) if isinstance(x, dict)]
        has_office = any(x.get("manager_owns") and _d(x.get("built")).get("Chair") for x in offices)
        job = _d(_d(s.get("order_desk")).get("manager")).get("job")
        why = (f"the manager is busy ({job})" if has_office and job else
               "the manager has an office but hasn't come to it" if has_office else
               "no working office yet: it needs a chair, which needs an approved order")
        proposals.append(Proposal("approve_orders", {"type": "approve_orders"},
                                  f"{len(waiting)} of the AI's work orders have waited "
                                  f"{cfg['approve_after_days']}+ days for the manager's approval ({why}): approve them", 2))


def _stuck_orders_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """The AI's own work orders that have stood still: copies of one order
    (0.54 piled up two dozen coke orders on one smelter) after 2 weeks, all
    but the one that moved last; a single one after 4 weeks. Cancelled, a few
    a cycle, and not placed again for 4 weeks (select holds it); one that gets
    stuck again after that is Needs you (_watchdog_notes)."""
    if memory is None:
        return
    if "orders" in _d(s.get("_errors")):
        return          # (0.104.81, 13c) no fresh order list: the watch is stale, cancel nothing
    now = abs_tick(s)
    groups: dict[str, list] = {}
    # (0.101.2) an order still waiting for the manager's approval isn't stuck
    unapproved = {str(o.get("id")) for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("validated") is False}
    # (0.101.4) nor is any order while none at all has started (no manager's
    # office: cancelling and placing them again only churns)
    orders = [o for o in _l(s.get("orders")) if isinstance(o, dict)]
    if any("validated" in o for o in orders) and not any(o.get("active") for o in orders):
        return
    for k, w in memory.order_watch.items():
        if k in unapproved:
            continue
        if (isinstance(w, dict) and w.get("by_ai") and isinstance(w.get("since"), int)
                and (w.get("left") or 0) > 0):
            groups.setdefault(str(w.get("what")), []).append((w["since"], k, w))
    out = []
    for what, lst in sorted(groups.items()):
        lst.sort()
        if len(lst) > 1:
            for since, k, w in lst[:-1]:
                days = (now - since) // TICKS_PER_DAY
                if days >= cfg["order_stuck_days"]:
                    out.append((0, k, what, f"{len(lst)} of the AI's {what} orders and this one hasn't moved in "
                                            f"{days} days: cancel it (one is kept)", False))
            lst = lst[-1:]
        since, k, w = lst[0]
        days = (now - since) // TICKS_PER_DAY
        if days >= cfg["order_stuck_you_days"] and not _stuck_before(memory, what, now, cfg):
            out.append((1, k, what, f"the AI's {what} order ({w.get('left')} left) hasn't moved in {days} days: "
                                    f"cancel it (not placed again for {cfg['stuck_retry_days']} days)", True))
    taken = {p.action.get("order_id") for p in proposals if p.action.get("type") == "cancel_work_order"}
    for _, k, what, why, single in sorted(out)[:cfg["stuck_cancel_max"]]:
        try:
            oid = int(k)
        except ValueError:
            continue
        if oid in taken:                    # (another rule cancels it this cycle)
            continue
        action = {"type": "cancel_work_order", "order_id": oid}
        if single:
            action["stuck"] = what
        proposals.append(Proposal("stuck_order", action, why, 6))


COAL_STONES = {"COAL_BITUMINOUS": "coke_bituminous", "LIGNITE": "coke_lignite"}


def _coal_rule(s: dict, proposals: list) -> None:
    """Coal the masons may use (0.52 let them have bituminous coal) goes back
    to being kept: it's the smelter's fuel, as coke."""
    for k in sorted(_d(_d(s.get("stone_use")).get("fuel_free"))):
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "keep": True},
                                  f"{k.lower().replace('_', ' ')} is free for the masons: keep it for coke "
                                  "(the smelter's fuel)", 2))
        return


def _picks_order(s: dict, cfg: dict, proposals: list) -> None:
    """(0.99.4) Picks for more miners while stone is short: DF lets a dwarf
    mine only with a pick, so region2 dug its quarries with 3 miners for 228
    dwarves (57% idle) and every boulder went at once. One pick for every
    picks_per_dwarves dwarves (3 at least, picks_max at most), forged in the
    first of copper, bronze, iron or steel there are bars for (steel last:
    the soldiers want it)."""
    lb = _d(s.get("labor"))
    if not isinstance(lb.get("picks"), int) or queued(s, {"metal_pick"}):
        return
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    # (0.104.4) and one more for every picks_per_backlog tiles waiting to be dug
    # (Enxah: 93 dwarves, 3 picks, 126 tiles waiting, no stone)
    want = min(cfg["picks_max"], max(3, citizens // cfg["picks_per_dwarves"])
               + int(lb.get("dig") or 0) // cfg["picks_per_backlog"])
    have = int(lb["picks"]) + int(lb.get("soldier_picks") or 0)
    if have >= want or not _has_shop(_d(s.get("buildings")), "MetalsmithsForge"):
        return
    n = want - have
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    metal = next((m for m in ("COPPER", "BRONZE", "IRON", "STEEL") if (bars.get(m) or 0) >= n), None)
    if metal:
        proposals.append(Proposal("picks", {"type": "work_order", "recipe": "metal_pick", "amount": n,
                                            "material": f"INORGANIC:{metal}"},
                                  f"stone is short and {have} pick(s) let only {have} dwarves mine: forge {n} "
                                  f"more in {metal.lower()}", 4, True))


PRECIOUS_ORES = {"NATIVE_GOLD", "NATIVE_SILVER", "NATIVE_PLATINUM", "HORN_SILVER", "NATIVE_ALUMINUM"}


def stone_crisis(s: dict, cfg: dict) -> str:
    """(0.104.124) What only stone answers now: ghosts with no slab, the dead
    with no coffin, a fort strained by unhappiness. "" when none."""
    dead = _d(s.get("dead"))
    out = []
    if int(dead.get("ghosts") or 0) > 0:
        out.append(f"{dead.get('ghosts')} ghosts wait for slabs")
    if int(dead.get("unburied") or 0) >= cfg["stone_crisis_unburied"] and int(dead.get("free_tombs") or 0) == 0:
        out.append(f"{dead.get('unburied')} dead wait for coffins")
    import outcomes
    un = outcomes.measure(s).get("unhappy_pct")
    if isinstance(un, (int, float)) and un >= cfg["strain_unhappy_pct"]:
        out.append(f"{un:g}% unhappy")
    return "; ".join(out)


def _stone_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """No stone the masons may use: DF keeps "economic" stone (ores, flux
    and the like) from ordinary jobs, and region2's boulders were all
    economic by y52, every stone order standing still. The commonest
    economic stone that is neither ore nor flux is allowed (DF's stone
    settings); without one, stone orders the AI gave that haven't moved are
    cancelled, and the furniture rule makes them in wood."""
    _coal_rule(s, proposals)
    # (0.104.124) an ore freed for the masons in a crisis goes back to being
    # kept once the crisis is over
    freed = list(getattr(memory, "ores_freed", None) or []) if memory is not None else []
    if freed and not stone_crisis(s, cfg):
        k = freed[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "keep": True},
                                  f"the ghosts are laid and the dead buried: {k.lower().replace('_', ' ')} is kept "
                                  "for the smelter again", 5))
        return
    if not stone_short(s, cfg["stone_low"]):
        # (0.104.117) picks for the digging that waits, stone short or not
        # (Teacheroar: 88 tiles waiting, 9 picks, levels stalled for years)
        if int(_d(s.get("labor")).get("dig") or 0) >= cfg["picks_per_backlog"]:
            _picks_order(s, cfg, proposals)
        return
    su = _d(s.get("stone_use"))
    econ = {k: v for k, v in _d(su.get("economic")).items() if isinstance(v, dict)}
    free = sorted(((int(v.get("n") or 0), k) for k, v in econ.items()
                   if not v.get("ore") and not v.get("flux") and not v.get("fuel")
                   and k not in COAL_STONES and int(v.get("n") or 0) >= cfg["stone_low"]),
                  reverse=True)
    if free:
        n, k = free[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k},
                                  f"only {su.get('usable')} boulders of stone the masons may use and {n} of "
                                  f"{k.lower().replace('_', ' ')} kept as \"economic\": let them use it", 3))
        return
    # (0.104.124) no ordinary stone at all and a crisis that stone answers
    # (Teacheroar: 13 ghosts with no slab, 38 dead with no coffin, 73% unhappy,
    # 51 dead in three minutes of tantrums): the commonest ore of a common
    # metal goes to the masons until the crisis is over
    crisis = stone_crisis(s, cfg)
    ores = sorted(((int(v.get("n") or 0), k) for k, v in econ.items()
                   if v.get("ore") and k not in PRECIOUS_ORES and int(v.get("n") or 0) >= cfg["stone_ore_min"]),
                  reverse=True)
    if crisis and ores:
        n, k = ores[0]
        proposals.append(Proposal("stone", {"type": "allow_stone", "stone": k, "ore": True},
                                  f"only {su.get('usable')} boulders of stone the masons may use and {crisis}: "
                                  f"let them use {k.lower().replace('_', ' ')} ({n} boulders of ore) until it's over", 2))
        return
    # dig a small quarry in ordinary stone (each tile a boulder), while
    # little other digging waits
    # (0.104.4) with no usable stone at all the quarry comes whatever else waits,
    # every quarry_dry_days at most (Enxah: 126 tiles of bedrooms waited for 3
    # miners, so no quarry for days while no crafts, mugs or jewellery could
    # be made: 42 dwarves badly wanted to craft)
    dig_now = int(_d(s.get("labor")).get("dig") or 0)
    last_q = (memory.last_fired.get("quarry") if memory is not None else None)
    dry = (int(su.get("usable") or 0) == 0
           and (last_q is None or not 0 <= abs_tick(s) - last_q < cfg["quarry_dry_days"] * TICKS_PER_DAY))
    if dig_now < cfg["quarry_when_dig_below"] or dry:
        n = mining_plan(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)["quarry"]
        proposals.append(Proposal("quarry", {"type": "quarry", "count": n},
                                  f"only {su.get('usable')} boulders of stone the masons may use: dig a small "
                                  "quarry in ordinary stone near the fort", 4))
    _picks_order(s, cfg, proposals)
    now = abs_tick(s)
    for k, w in sorted(memory.order_watch.items()) if memory is not None else []:
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what", "")).startswith("stone_")
                and isinstance(w.get("since"), int) and (now - w["since"]) // TICKS_PER_DAY >= cfg["order_stuck_days"]):
            proposals.append(Proposal("stone", {"type": "cancel_work_order", "order_id": int(k)},
                                      f"no stone the masons may use and {w.get('what')} hasn't moved in "
                                      f"{(now - w['since']) // TICKS_PER_DAY} days: cancel it (made in wood instead)", 4))
            return
    notes.append(f"only {su.get('usable')} boulders of stone the masons may use (the rest is ore, flux or other "
                 "economic stone): furniture in wood, no stone crafts until more is dug")


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


def _trade_rules(s: dict, cfg: dict, citizens: int, proposals: list, notes: list,
                 traits: dict | None = None, memory=None) -> None:
    """Caravans: the fort's crafts taken to the depot while one is coming or
    there (the trade itself is yours: DFHack can't barter); crafts made in
    quiet times so there is something to sell."""
    tr = _d(s.get("trade"))
    if not tr.get("depot"):
        return
    cs = [c for c in _l(tr.get("caravans")) if isinstance(c, dict)]
    # (0.103.18) Hermit Kingdom: no goods to the depot, no broker called, no
    # deal; the caravans come and go (the depot is still emptied after them)
    hermit = memory is not None and has_rule(getattr(memory, "culture", None), "no_trade")
    if hermit:
        if cs:
            notes.append("a hermit kingdom: the caravan is left alone, nothing is traded")
        cs = []
    nd = _d(s.get("needs"))
    acq = unmet(s, "AcquireObject")
    # (0.103.9) rings, figurines and the like stay home while dwarves want
    # something to own and there aren't free ones for each (Enxah: 16 wanted,
    # every craft went to the depot, 163 there after the caravan left)
    keep_trinkets = acq >= cfg["needs_note_at"] and isinstance(nd.get("trinkets"), int) and nd["trinkets"] < acq
    if cs and (tr.get("goods") or 0) > 0:
        keep = keeps_treasures(traits or _traits(s), memory)
        # (0.104.78) the finished-goods piles full of crafts: more to the depot
        # at a time (40 a call while 1520 of 1522 tiles were used)
        fg = _d(_d(_d(s.get("logistics")).get("storage")).get("finished_goods"))
        full = int(fg.get("tiles") or 0) and int(fg.get("used") or 0) >= int(fg.get("tiles") or 0) * 0.95
        per = cfg["bring_goods_full"] if full else 40
        proposals.append(Proposal("trade", {"type": "bring_goods", "count": min(per, tr["goods"])}
                                  | ({"keep_treasures": True} if keep else {})
                                  | ({"keep_trinkets": True} if keep_trinkets else {}),
                                  f"a caravan from {cs[0].get('civ')} is "
                                  f"{ {'AtDepot': 'at the depot', 'Approaching': 'coming'}.get(str(cs[0].get('state')), 'coming') }: "
                                  f"take up to {min(per, tr['goods'])} crafts to the depot"
                                  + (" (the goods piles are full)" if full else ""), 3))
    trader = _d(tr.get("trader"))
    if cs and not trader.get("at_depot") and not _d(tr.get("screen")).get("open"):
        here = any(str(c.get("state")) == "AtDepot" for c in cs)
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  f"a caravan from {cs[0].get('civ')} is {'at the depot' if here else 'coming'}: "
                                  + ("ask for the broker at the depot" if not trader.get("requested") else
                                     "the broker is asked for; if nobody comes within a day, anyone may trade"), 3))
    if not cs and (tr.get("at_depot") or 0) > 0 and not _d(tr.get("screen")).get("open"):
        # (0.103.9) the caravans have gone and the fort's goods sit in the
        # depot, where nobody can own or use them, until the next one
        proposals.append(Proposal("unload_depot", {"type": "unload_depot", "max": cfg["unload_depot_max"]},
                                  f"the caravans have gone and {tr['at_depot']} of the fort's goods sit in the "
                                  "depot: take them back out (stored again, there to own)", 4))
    if not cs and trader.get("anyone") and trader.get("anyone_by_ai", True):
        proposals.append(Proposal("call_trader", {"type": "call_trader",
                                                  "wait_ticks": cfg["trade_anyone_after_ticks"]},
                                  "the caravans have gone: the depot back to the broker only (if the AI opened it "
                                  "to anyone)", 8))
    screen = _d(tr.get("screen"))
    here = any(str(c.get("state")) == "AtDepot" for c in cs)
    if (here and trader.get("at_depot") and not screen.get("open") and trader.get("can_open")
            and trader.get("fresh", True)):
        proposals.append(Proposal("open_trade", {"type": "open_trade"},
                                  f"{'the broker' if not trader.get('anyone') else 'a trader'} is at the depot with "
                                  f"the caravan from {cs[0].get('civ')}: open the trade screen", 2))
    if screen.get("ready") and not hermit:
        wants = trade_wants(s, cfg, citizens)
        if not wants and screen.get("by_ai"):
            proposals.append(Proposal("close_trade", {"type": "close_trade"},
                                      "the fort needs nothing the caravan might sell: close the trade screen", 2))
        if wants and not screen.get("by_ai"):
            notes.append("the trade screen you opened is yours: the AI leaves the deal to you")
        elif wants:
            proposals.append(Proposal("trade_deal", {"type": "trade_deal", "wants": wants,
                                                     "margin": trade_margin_for(traits or _traits(s), cfg),
                                                     "press": True, "close": True},
                                      "the trade screen is open and the merchants are ready: buy "
                                      + ", ".join(f"{w['count']} {w['key'].lower()}" for w in wants[:4])
                                      + " with the fort's crafts", 2))
    elif screen.get("open") and screen.get("by_ai") and screen.get("unloading"):
        # opened before the merchants had unloaded: the screen holds time still,
        # so they never would. Closed; opened again once they're done.
        proposals.append(Proposal("close_trade", {"type": "close_trade", "unloading": True},
                                  "the trade screen opened while the merchants were still unloading (time stands "
                                  "still while it's open): close it and open it again once they're done", 2))
    elif here and trader.get("at_depot") and not trader.get("can_open"):
        ask_player(notes, f"a caravan from {cs[0].get('civ')} is at the trade depot "
                          f"and {'the broker' if not trader.get('anyone') else 'a trader'} is there "
                          f"({tr.get('at_depot') or 0} of the fort's goods there): open the trade screen; "
                          "the AI then ticks a deal and presses Trade. To let the AI open it too, show it the "
                          "depot's Trade button once: python brain\\probe_trade.py --here-depot")
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    if (_has_shop(s["buildings"], "Craftsdwarfs") and not young_fort(s, cfg) and idle >= cfg["idle_share"]
            and not stone_short(s, 10) and not hermit
            and not (memory is not None and has_rule(getattr(memory, "culture", None), "small_storage"))   # (0.103.19) Waste Not
            and (tr.get("goods") or 0) < citizens * 2 * factor(traits or {}, "trade")
            * (2 if memory is not None and has_rule(getattr(memory, "culture", None), "merchant_princes") else 1)
            and not queued(s, {"stone_crafts", "metal_crafts"})):
        # (0.104.95) a precious metal the fort has to spare first: its crafts sell
        # for 10-40 times rock's
        metal = precious_metal(s, cfg)
        if metal:
            proposals.append(Proposal("crafts", {"type": "work_order", "recipe": "metal_crafts", "amount": 3,
                                                 "material": f"INORGANIC:{metal}"},
                                      f"{round(100 * idle)}% of the dwarves are idle and there are only "
                                      f"{tr.get('goods') or 0} crafts to sell: make 3 of {metal.lower()} (worth far "
                                      "more than rock)", 6, True))
            return
        proposals.append(Proposal("crafts", {"type": "work_order", "recipe": "stone_crafts", "amount": 10},
                                  f"{round(100 * idle)}% of the dwarves are idle and there are only {tr.get('goods') or 0} "
                                  "crafts to sell: make some from rock", 6, True))



# (0.104.95) Metals worth far more as crafts than as anything the fort needs:
# a craft's value is its material's (DF: silver 10, gold 30, platinum 40, rock 1-3)
PRECIOUS_METALS = ("PLATINUM", "GOLD", "ROSE_GOLD", "ELECTRUM", "SILVER", "STERLING_SILVER", "BILLON")


def precious_metal(s: dict, cfg: dict) -> str | None:
    """The precious metal with the most bars over `precious_crafts_bars`, when
    the fort has a forge and fuel for it; None otherwise."""
    gear = _d(_d(s.get("military")).get("gear"))
    if not gear.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < 3:
        return None
    bars = _d(gear.get("all_bars"))
    best = None
    for m in PRECIOUS_METALS:
        n = bars.get(m)
        if isinstance(n, (int, float)) and n - cfg["precious_crafts_bars"] >= 3 and (best is None or n > best[0]):
            best = (int(n), m)
    return best[1] if best else None


def _glass_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.95) Glass from the fort's sand (phase 13): green glass crafts
    when the dwarves are idle or there's no rock for crafts. One step a cycle:
    a glass furnace (and a wood furnace when there's no fuel), a sand zone on
    sand the dwarves reach, charcoal for fuel, bags filled with sand at the
    furnace, then the crafts. Only where the geology has sand."""
    sup = _d(s.get("supplies"))
    layers, zones = _l(sup.get("sand_layers")), int(sup.get("sand_zones") or 0)
    if not layers and not zones:
        return
    if young_fort(s, cfg):
        return
    tr = _d(s.get("trade"))
    dw = _d(s.get("dwarves"))
    idle = (dw.get("idle_adults") or 0) / max(1, dw.get("adults") or 1)
    citizens = int(dw.get("citizens") or dw.get("adults") or 0)
    goods_short = (tr.get("goods") or 0) < max(10, citizens * 2)
    if not ((idle >= cfg["idle_share"] or stone_short(s, 10)) and goods_short):
        return
    b = s["buildings"]
    chain = ("collect_sand", "glass_crafts", "make_charcoal")
    if any(queued(s, {r}) for r in chain):
        return
    fuel, bags = int(sup.get("fuel") or 0), int(sup.get("sand_bags") or 0)
    empty_bags = int(sup.get("empty_bags") or 0)
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    if not _has_shop(b, "GlassFurnace"):
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            shops = ["GlassFurnace"] + (["WoodFurnace"] if not _has_shop(b, "WoodFurnace") and fuel < 5 else [])
            proposals.append(Proposal("glass", {"type": "start_project", "kind": "workshops", "shops": shops},
                                      f"the fort has sand ({', '.join(map(str, layers[:2])) or 'a sand zone'}) and "
                                      f"{round(100 * idle)}% of the dwarves idle: build {' and '.join(shops)} for glass", 6))
        return
    if zones == 0:
        proposals.append(Proposal("glass", {"type": "sand_zone"},
                                  "glass is made from sand: a sand collection zone where the dwarves can fill bags", 6))
        return
    if fuel < cfg["glass_fuel_min"]:
        if _has_shop(b, "WoodFurnace") and wood >= 20:
            proposals.append(Proposal("glass", {"type": "work_order", "recipe": "make_charcoal", "amount": 3},
                                      f"the glass furnace burns fuel and the fort has {fuel}: make charcoal "
                                      f"({wood} logs)", 6, True))
        else:
            notes.append(f"glass waits for fuel ({fuel} coal; charcoal needs a wood furnace and 20 logs)")
        return
    if bags < cfg["glass_sand_bags"]:
        if empty_bags:
            n = min(cfg["glass_sand_bags"] - bags, empty_bags)
            proposals.append(Proposal("glass", {"type": "work_order", "recipe": "collect_sand", "amount": n},
                                      f"glass is made from bags of sand ({bags} filled): fill {n} at the glass furnace",
                                      6, True))
        else:
            notes.append("glass waits for an empty bag to fill with sand")
        return
    n = min(bags, fuel, 5)
    proposals.append(Proposal("glass", {"type": "work_order", "recipe": "glass_crafts", "amount": n},
                              f"{round(100 * idle)}% of the dwarves are idle and there are only {tr.get('goods') or 0} "
                              f"crafts to sell: make {n} of green glass", 6, True))


def _gems_rule(s: dict, cfg: dict, proposals: list) -> None:
    """Gems: rough gems are cut at a jeweller's (DFHack's autogems, the tools
    rule) and sold; the workshop first. Cut gems in stock are set into the
    crafts waiting to be sold (several times their value), a few at a time."""
    tr = _d(s.get("trade"))
    cg = _d(tr.get("cut_gem"))
    if (_has_shop(s["buildings"], "Jewelers") and int(cg.get("n") or 0) >= cfg["gems_cut_at"]
            and int(tr.get("goods") or 0) >= cfg["gems_cut_at"] and str(cg.get("token", "")).startswith("INORGANIC:")
            and not queued(s, {"encrust_goods"})):
        n = min(5, int(cg["n"]) // 2)
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
            and int(rg.get("n") or 0) >= 1 and rough >= cfg["gems_cut_at"]
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


def trade_wants(s: dict, cfg: dict, citizens: int) -> list[dict]:
    """What the fort would buy from a caravan, most needed first: food and
    drink when short, then metal for gear, cloth, leather, thread, fuel, wood."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    citizens = max(1, citizens)
    wants: list[dict] = []

    def want(key: str, n: float) -> None:
        n = int(n)
        if n > 0:
            wants.append({"key": key, "count": min(n, 500)})

    food = sum(int(st.get(k) or 0) for k in ("prepared_meals", "meat", "fish", "cheese", "eggs", "plants"))
    want("FOOD", citizens * cfg["established_food_per_dwarf"] - food)
    want("DRINK", citizens * cfg["trade_drink_per_dwarf"] - int(st.get("drink") or 0))
    if player_rules(s)["make_gear"]:
        want("BAR:STEEL", min(30, cfg["steel_want"] - int(bars.get("STEEL") or 0)))
        want("BAR:IRON", cfg["trade_bars_iron"] - int(bars.get("IRON") or 0))
    want("CLOTH", max(cfg["cloth_min"], citizens * cfg["cloth_per_dwarf"]) - int(st.get("cloth") or 0))
    want("SKIN_TANNED", cfg["trade_leather"] - int(st.get("leather") or 0))
    want("THREAD", cfg["trade_thread"] - int(st.get("thread") or 0))
    want("BAR:COAL", cfg["coke_when_fuel_below"] - int(su.get("fuel") or 0))
    want("WOOD", cfg["trade_wood"] - int(st.get("wood") or 0))
    if _d(_d(s.get("locations")).get("count")).get("HOSPITAL"):
        soap = int(su.get("soap") or 0)
        want("SOAP", cfg["soap_keep"] - soap)
        if soap < cfg["soap_keep"] and not su.get("tallow") and not su.get("fat"):
            want("TALLOW", cfg["soap_keep"] - soap)
    return wants


def _spare_mechanisms_rule(s: dict, cfg: dict, traits: dict, proposals: list) -> None:
    """(0.96) Engineering +50 or more: a few mechanisms kept spare for levers,
    traps and links (spare_mechanisms), made at a mechanic's workshop."""
    want = spare_mechanisms(traits)
    have = int(_d(s.get("stocks")).get("mechanisms") or 0)
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


def trees_this_year(s: dict, memory) -> tuple[int, int | None]:
    """(0.89) Trees felled this game year, and the elves' cap if elves trade
    with the fort (None otherwise: no quota to keep)."""
    dp = _d(s.get("diplomacy"))
    tr, cap = dp.get("trees_removed"), dp.get("tree_cap")
    ty = getattr(memory, "tree_year", None) if memory is not None else None
    felled = 0
    if isinstance(tr, int) and isinstance(ty, dict) and isinstance(ty.get("base"), int) \
            and ty.get("year") == _d(s.get("date")).get("year"):
        felled = max(0, tr - ty["base"])
    if not dp.get("elves") or not isinstance(cap, int) or cap <= 0:
        return felled, None
    return felled, cap


def _keep_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list, memory=None) -> None:
    """Building above ground (Surface ambition 50+): a keep round the fort's way
    in from the surface, walls with a door first, then a roof over the inside.
    One step at a time (the bridge keeps where it's got to); not in a young or
    small fort, not while enemies can reach the dwarves, and only with stone,
    blocks or logs to build with."""
    if traits.get("surface", 0) < cfg["keep_surface_min"] and not (
            memory is not None and has_rule(memory.culture, "keep_above")):     # (0.103.18) Sky-reachers
        return
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
        if stage == "roof" and k.get("roof_planned"):
            notes.append(f"the keep: {k['roof_planned']} roof tile(s) still to build")
            return
    if young_fort(s, cfg) or citizens < cfg["keep_min_citizens"]:
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    st = _d(s.get("stocks"))
    if st.get("boulders", 0) + st.get("blocks", 0) + st.get("wood", 0) < cfg["keep_min_material"]:
        notes.append(f"the keep waits for building stone, blocks or logs (needs {cfg['keep_min_material']})")
        return
    if not isinstance(k, dict):
        why = ("Surface ambition: wall in the way in from the surface, a keep with one door, "
               "the first building above ground")
    elif k.get("stage") == "clearing":
        why = "the keep: the trees are down, raise its walls and door"
    elif k.get("stage") == "walls":
        why = "the keep: its walls stand, put a roof over the inside"
    else:
        why = "the keep: its roof is built, call it finished"
    proposals.append(Proposal("keep", {"type": "place_keep"}, why, 7))


def _free_time_rule(s: dict, citizens: int, cfg: dict, proposals: list, notes: list) -> None:
    """(0.104.10) Time to be with friends: DF's "everybody does this" for
    planting and plant gathering keeps every dwarf on call (Enxah: 3 of 88
    idle, 167 jobs, 44 badly wanting company). While many badly want friends
    and hardly anyone is idle, those details go to a crew (the most skilled:
    one planter a farm plot, 3 to 12; 3 gatherers); once company is no longer
    wanted badly by many, the AI's narrowed details go back to everybody. A
    detail you set yourself is never touched (the bridge checks)."""
    soc = _d(_d(s.get("needs")).get("social"))
    lb = _d(s.get("labor"))
    if not soc or not lb or citizens < cfg["free_time_min_pop"]:
        return
    friends = int(_d(_d(_d(s.get("needs")).get("needs")).get("BeWithFriends")).get("badly") or 0)
    idle_share = int(soc.get("idle") or 0) / max(1, int(soc.get("citizens") or citizens))
    narrowed = lb.get("narrowed") if isinstance(lb.get("narrowed"), dict) else {}
    jobs = _d(lb.get("jobs"))
    if friends >= citizens * cfg["free_time_friends_share"] and idle_share < cfg["free_time_idle_below"]:
        plots = int(_d(s.get("farms")).get("built") or 0)
        for job, keep in (("farming", max(3, min(12, plots))), ("gathering", 3)):
            if job in narrowed or _d(jobs.get(job)).get("mode") != "EverybodyDoesThis":
                continue
            proposals.append(Proposal("free_time", {"type": "narrow_detail", "job": job, "keep": keep},
                                      f"{friends} dwarves badly want time with friends and only "
                                      f"{round(idle_share * 100)}% are ever idle: {job} goes to a crew of {keep} "
                                      "(the most skilled), not everybody", 5))
            return                                              # one a cycle
    elif narrowed and friends < citizens * cfg["free_time_widen_share"]:
        job = sorted(narrowed)[0]
        proposals.append(Proposal("free_time", {"type": "narrow_detail", "job": job, "widen": True},
                                  f"only {friends} dwarves badly want company now: {job} back to everybody", 6))


def _labor_rules(s: dict, citizens: int, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """Who does what (lua/ai-labor.lua): enough miners for the digging while
    picks lie unused; plant gatherers, fishers, farmers and a woodcutter for
    what the fort has to do. Each through the game's own work details; a
    detail you set to everybody or nobody is left alone. Also: shrubs near
    the fort marked for gathering while it has no farm."""
    lb = _d(s.get("labor"))
    jobs = _d(lb.get("jobs"))
    if any(_d(j).get("unsorted") for j in jobs.values()):
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": "mining", "count": 0},
                                  "a work detail's member list is out of order (bridge 0.38.0): put it in order "
                                  "so the game gives everyone their labours again", 1))

    def want(job: str, n: int, why: str, pri: int = 3) -> None:
        j = _d(jobs.get(job))
        if not j or j.get("mode") in LABOR_MODES_FIXED or not j.get("candidates"):
            return
        short = n - int(j.get("doing") or 0)
        if short > 0:
            proposals.append(Proposal("labor", {"type": "assign_labor", "job": job, "count": min(10, short)},
                                      f"{why}: {j.get('doing') or 0} dwarf(s) do it, {n} wanted: put {short} "
                                      f"more on it", pri))

    # miners: the digging waiting, up to the free picks
    dig, need = lb.get("dig") or 0, lb.get("need") or 0
    if dig and need > 0 and (lb.get("candidates") or 0) > 0 and \
            _d(jobs.get("mining")).get("mode") not in LABOR_MODES_FIXED:
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": "mining", "count": min(10, need)},
                                  f"{dig} tile(s) to dig, {lb.get('miners') or 0} dwarf(s) mining and "
                                  f"{lb.get('picks') or 0} pick(s): let {need} more dwarf(s) mine", 2))
    if dig and (lb.get("miners") or 0) == 0 and (lb.get("picks") or 0) == 0:
        why = (f"{lb['soldier_picks']} pick(s) are in soldiers' hands (a uniform with \"any weapon\" takes them)"
               if lb.get("soldier_picks") else "the fort has no pick")
        ask_player(notes, f"{dig} tile(s) wait to be dug and nobody can dig: {why}. Give the squad a uniform "
                          "with a real weapon, or make a pick at a forge")
    elif lb.get("soldier_picks"):
        notes.append(f"{lb['soldier_picks']} pick(s) are in soldiers' hands, so fewer dwarves can dig")

    small = citizens < cfg["young_fort"]
    farms = has_farms(s)
    hungry = food_per_dwarf(s) < cfg["found_food_per_dwarf"]
    # far more gathering waiting than a fed fort needs (old marks): cancelled
    gathering = int(_d(_d(s.get("jobs")).get("by_type")).get("GatherPlants") or 0)
    if not hungry and gathering > cfg["gather_jobs_max"] and food_per_dwarf(s) >= cfg["established_food_per_dwarf"]:
        proposals.append(Proposal("gather_trim", {"type": "trim_gathering", "keep": cfg["gather_jobs_keep"]},
                                  f"{gathering} plant-gathering jobs wait and the fort has "
                                  f"{food_per_dwarf(s):g} food a dwarf: cancel all but {cfg['gather_jobs_keep']} "
                                  "(the farthest first)", 5))
    # while food is short: shrubs gathered (a few at a time: a fort where
    # everybody gathers drops everything else for it), fish caught
    thirsty = drink_short(s, cfg)          # (0.99.6) wild plants and fruit to brew, and their seeds
    if (hungry or thirsty) and (lb.get("shrubs") or 0) > 0 and (lb.get("gather_marked") or 0) < 5:
        n = max(20, min(100, citizens * 4, lb["shrubs"]))
        why = (f"only {food_per_dwarf(s):g} food a dwarf" + ("" if farms else " and no farm yet")
               if hungry else f"only {int(_d(s.get('stocks')).get('drink') or 0)} drink for {citizens} and "
               "little a still can brew")
        proposals.append(Proposal("gather", {"type": "gather_plants", "count": n},
                                  why + f": gather {n} of the {lb['shrubs']} shrub(s) near the fort "
                                  "(food and drink, and seeds)", 2))
    if (lb.get("gather_marked") or 0) > 0 or ((hungry or thirsty) and (lb.get("shrubs") or 0) > 0):
        want("gathering", gatherers(_traits(s) if isinstance(s.get("settings"), dict) else {}, small),
             "shrubs to gather")
    if (lb.get("fish_water") or 0) > 0:
        river = 1 if memory is not None and has_rule(memory.culture, "river_bridges") else 0   # (0.103) Riverfolk
        want("fishing", (1 if citizens < 10 else 2) + river, "water to fish in near the fort")
    if farms:
        want("farming", 2 if small else max(3, citizens // 10), "farm plots to tend")
    wc = _d(jobs.get("woodcutting"))
    axes = int(wc.get("tools") or 0)
    if axes:
        cutters = min(axes, woodcutters(_traits(s) if isinstance(s.get("settings"), dict) else {}, small))
        if memory is not None and has_rule(memory.culture, "elf_friends"):
            cutters = min(cutters, 1)               # (0.103.4) Elf-friends
        want("woodcutting", cutters,
             "trees to cut (wood for beds, barrels and bins)", 4)
    _labor_waiting_rule(lb, citizens, cfg, proposals, drink_below_target(s, citizens, cfg))


# Labours with rules of their own (miners by the digging and picks, woodcutters
# by the axes, gatherers, fishers, farmers by the work there)
OWN_LABOR_RULES = {"MINE", "CUTWOOD", "HERBALIST", "FISH", "PLANT"}


# workshops given a feeder stockpile first (the busiest hauling first)
FEEDER_ORDER = ("Masons", "Carpenters", "Smelter", "MetalsmithsForge", "Craftsdwarfs", "Depot", "Kitchen", "Still",
                "WoodFurnace", "Bowyers", "Loom", "Clothiers", "Leatherworks")


def _feeder_rule(s: dict, cfg: dict, proposals: list) -> None:
    """Hauling: a small stockpile beside each workshop for what it uses, and
    one for goods beside the depot (lua/ai-builder.lua place_feeder), one a
    cycle, busiest first. Not in a young fort (it has few piles to spare)."""
    if young_fort(s, cfg):
        return
    rows = [r for r in _l(_d(s.get("logistics")).get("feeders")) if isinstance(r, dict) and not r.get("has")]
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


def woodcutters(traits: dict, small: bool) -> int:
    """Surface (underground - above ground): woodcutters wanted (axes
    permitting): 1 at -50 or lower, 1-2 between, one more from +50."""
    v = traits.get("surface", 0) or 0
    base = 1 if small else 2
    return 1 if v <= -50 else base + (1 if v >= 50 else 0)


def gatherers(traits: dict, small: bool) -> int:
    """Surface: plant gatherers while shrubs wait: 2-3, one fewer at -50 or
    lower, one more from +50."""
    v = traits.get("surface", 0) or 0
    base = 2 if small else 3
    return max(1, base + (1 if v >= 50 else -1 if v <= -50 else 0))


def trade_margin_for(traits: dict, cfg: dict) -> float:
    """Greed (generous - grasping): how much more the fort gives than it
    gets: 1.2 at 0, 1.35 at -100 (1.6 at most), 1.05 at +100 (never less;
    the merchants' own floor, learned in the game, still applies)."""
    g = traits.get("greed", 0) or 0
    return round(max(1.05, min(1.6, cfg["trade_margin"] - 0.15 * g / 100)), 2)


def keeps_treasures(traits: dict, memory=None) -> bool:
    """Greed +50 or more: gems and precious-metal goods stay home, never to
    the depot. (0.103.15) Gem-mad too."""
    return ((traits.get("greed", 0) or 0) >= 50
            or (memory is not None and has_rule(getattr(memory, "culture", None), "keep_gems")))


def spare_mechanisms(traits: dict) -> int:
    """Engineering +50 or more: mechanisms kept spare for levers and traps,
    one per 25 (2 at +50, 4 at +100, 8 at +200)."""
    e = traits.get("engineering", 0) or 0
    return int(e // 25) if e >= 50 else 0


def _dairy_rule(s: dict, cfg: dict, citizens: int, proposals: list) -> None:
    """(0.104.79) Milk and cheese: the tame cows, goats and the like milked at
    the farmer's workshop, their milk made into cheese there. Cheese is a
    cook's ingredient of more worth than fish and plants (Enxah: no cheese,
    no eggs, 28 dwarves wanting a good meal and 27 good meals for 88), and it
    keeps. Up to `dairy_batch` at a time while the cheese kept is under
    `cheese_per_dwarf` a dwarf; a Beast-friends fort still milks (no harm)."""
    if young_fort(s, cfg) or not _has_shop(s["buildings"], "Farmers"):
        return
    sup, st = _d(s.get("supplies")), _d(s.get("stocks"))
    milkable, milk = int(sup.get("milkable") or 0), int(sup.get("milk") or 0)
    cheese = int(st.get("cheese") or 0)
    if cheese >= citizens * cfg["cheese_per_dwarf"]:
        return
    if milk > 0 and not queued(s, {"make_cheese"}):
        proposals.append(Proposal("dairy", {"type": "work_order", "recipe": "make_cheese",
                                            "amount": min(cfg["dairy_batch"], milk)},
                                  f"{milk} milk and {cheese} cheese for {citizens} dwarves: make cheese "
                                  "(it lifts the meals and keeps)", 6, True))
    elif milkable > 0 and milk == 0 and not queued(s, {"milk_creature"}):
        proposals.append(Proposal("dairy", {"type": "work_order", "recipe": "milk_creature",
                                            "amount": min(cfg["dairy_batch"], milkable)},
                                  f"{milkable} tame animals give milk and the fort has no cheese: milk them "
                                  "(for cheese)", 6, True))


def _eggs_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(0.104.80) Eggs: a hen lays only in a nest box (DF wiki, Nest box);
    Enxah had none. Stone nest boxes are ordered at the mason's while fewer
    are built or free than hens (up to `nest_box_max`), and the bridge pens
    the loose hens and plans the boxes in their pasture."""
    if young_fort(s, cfg):
        return
    sup = _d(s.get("supplies"))
    hens = int(sup.get("egg_layers") or 0)
    if hens < 2:
        return
    want = min(hens, cfg["nest_box_max"])
    built, free = int(sup.get("nest_boxes") or 0), int(sup.get("nest_box_items") or 0)
    if built >= want:
        return
    short = want - built - free - queued(s, {"stone_nest_box"})
    if short > 0 and _has_shop(s["buildings"], "Masons"):
        proposals.append(Proposal("nest_box_order", {"type": "work_order", "recipe": "stone_nest_box",
                                                     "amount": min(5, short)},
                                  f"{hens} hens and {built} nest boxes: make stone nest boxes (hens lay only in one)",
                                  5, True))
    loose = hens - int(sup.get("egg_layers_penned") or 0)
    if free > 0 or loose > 0:
        proposals.append(Proposal("eggs", {"type": "nest_boxes", "max": 3},
                                  f"{hens} hens, {built} nest boxes built, {free} free"
                                  + (f", {loose} hens in no pasture" if loose else "")
                                  + ": pen the hens together and put nest boxes in their pasture (for eggs)", 5))


# workshops the fort can have far too many of (0.75.0 built 116 soap maker's): name -> most kept
EXCESS_SHOPS = {"SoapMaker": 2}


def _excess_shops_rule(s: dict, cfg: dict, proposals: list) -> None:
    places = {**_d(_d(s.get("buildings")).get("workshops"))}
    for name, most in EXCESS_SHOPS.items():
        n = sum(places.get(k, 0) for k in SHOP_ALIASES.get(name, (name,)))
        if n > most:
            proposals.append(Proposal("excess_shops", {"type": "remove_workshops", "kind": name, "keep": 1,
                                                       "max": 20},
                                      f"{n} {name} workshops (one is enough): take down the idle extras", 6))


def drink_below_target(s: dict, citizens: int, cfg: dict) -> bool:
    """(0.102.2) Drink under the fort's own target per dwarf."""
    drink = _d(s.get("stocks")).get("drink")
    return isinstance(drink, (int, float)) and citizens > 0 and drink < citizens * cfg["drink_per_dwarf"]


def _labor_waiting_rule(lb: dict, citizens: int, cfg: dict, proposals: list, thirsty: bool = False) -> None:
    """Work that waits for a worker (lua/ai-labor.lua's waiting_work): a
    labour with jobs nobody has taken while none of its dwarves is free gets
    more dwarves, through the detail that carries it (a few at a time, up to a
    quarter of the fort). And dwarves skilled in a detail's trade who aren't
    on it (migrants come with trades) are put on it."""
    made = 0
    for w in _l(lb.get("waiting")):
        if not isinstance(w, dict) or made >= cfg["labor_moves_per_cycle"]:
            continue
        lab, jobs, holders = str(w.get("labor")), int(w.get("jobs") or 0), int(w.get("holders") or 0)
        # (0.102.2) brewing while drink is short: one waiting job is enough
        # (Monastery: 5 stills, 4 brewers, drink 1.9 -> 0.1 a dwarf)
        least = 1 if (thirsty and lab == "BREWER") else cfg["labor_waiting_jobs"]
        if (lab in OWN_LABOR_RULES or lab.startswith("HAUL") or jobs < least
                or (w.get("idle") or 0) > 0 or w.get("mode") in LABOR_MODES_FIXED
                or holders >= max(2, citizens // 4)):
            continue
        n = min(3, max(1, math.ceil(jobs / 5)))
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": lab, "count": n},
                                  f"{jobs} {lab.lower().replace('_', ' ')} job(s) wait and none of the {holders} "
                                  f"dwarf(s) who do it is free: put {n} more on it"
                                  + (f" (the {w.get('detail')} work detail)" if w.get("detail") else ""), 4))
        made += 1
    for k in _l(lb.get("skilled_off")):
        if not isinstance(k, dict) or made >= cfg["labor_moves_per_cycle"]:
            continue
        lab, n = str(k.get("labor")), int(k.get("skilled") or 0)
        if lab in ("MINE", "CUTWOOD") or n <= 0:       # (those go by the picks and axes)
            continue
        proposals.append(Proposal("labor", {"type": "assign_labor", "job": lab, "count": min(3, n),
                                            "min_skill": 3},
                                  f"{n} dwarf(s) skilled in {lab.lower().replace('_', ' ')} aren't on the "
                                  f"{k.get('detail')} work detail: put them on their trade", 5))
        made += 1


def farm_target(s: dict, traits: dict, citizens: int, cfg: dict) -> int:
    """Farm tiles wanted: per dwarf of the population the fort is growing
    toward (as for bedrooms), more with a higher Agriculture."""
    pop = citizens
    if player_rules(s)["fort_goal"] != "maintain":
        target = growth_target(s, cfg)
        if target > citizens:
            pop = min(target, citizens + cfg["beds_ahead"])
    tiles = math.ceil(pop * cfg["farm_tiles_per_dwarf"] * factor(traits, "agriculture"))
    return max(cfg["min_farm_tiles"], min(cfg["max_farm_tiles"], tiles))


def _farm_rule(s: dict, memory, traits: dict, citizens: int, cfg: dict, proposals: list, notes: list) -> None:
    """Farm plots, placed by the AI itself: on soil or muddy floor the fort
    already has, else a farm level dug in a soil layer."""
    if traits.get("agriculture", 0) <= -100 or citizens < cfg["min_dwarves_for_farms"]:
        return                                   # Hunt and gather: no farms
    have = idle_surface = int(_d(s.get("farms")).get("tiles") or 0)
    # (0.102.3) surface plots with nothing to sow (no seeds of a surface crop
    # that grows in a season; trees' seeds don't go in plots) don't count: the
    # Enxah fort had 42 tiles, 4 of its 6 plots on the surface and bare, and
    # ran dry on its 2 plump helmet plots
    fm = _d(s.get("farms"))
    plots, under = int(fm.get("plots") or 0), int(fm.get("plots_underground") or 0)
    crops = [v for v in _d(fm.get("crops")).values() if isinstance(v, dict)]
    if crops and plots and under < plots and not any(
            int(v.get("seeds") or 0) > 0 and _l(v.get("seasons")) and not v.get("underground") for v in crops):
        have = round(have * under / plots)
    idle_surface -= have
    pr = _d(s.get("projects"))
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    levels = [p for p in open_ if p.get("kind") == "farms"]
    # plots of a farm level still being dug aren't buildings yet
    coming = sum(int(_d(p.get("summary")).get("farm_tiles") or 0) for p in levels if p.get("phase") == "dig")
    want = farm_target(s, traits, citizens, cfg)
    if have + coming >= want * cfg["farm_refill_share"]:
        return
    if memory.farm_failure:
        # Only the player's problem when the fort is going hungry or thirsty;
        # while it's fed, a smaller field than the rule of thumb is fine.
        st = _d(s.get("stocks"))
        hungry = ("stocks" not in s["_errors"]
                  and (st.get("drink", 0) < citizens * cfg["urgent_drink_per_dwarf"]
                       or st.get("prepared_meals", 0) < citizens * cfg["urgent_meals_per_dwarf"]))
        text = f"farm plots: {memory.farm_failure}"
        if hungry:
            ask_player(notes, f"{text}. Food or drink is running low: make soil or muddy floor inside "
                       "the fort (dig into soil, or flood a floor to muddy it) and the AI will lay the "
                       "plots out")
        else:
            notes.append(f"{text} (the fort is fed, so this can wait)")
    # a farm level that couldn't be dug (no soil) isn't tried, or asked about, again for 4 weeks
    failed = memory.farm_failure_tick
    recent_fail = (failed is not None
                   and 0 <= abs_tick(s) - failed < cfg["farm_dig_retry_days"] * TICKS_PER_DAY)
    if recent_fail:
        return            # nowhere to farm a few days ago: asking every cooldown changes nothing
    # (a farm level gets one more slot than other levels: food comes first)
    dig = not levels and len(open_) < (pr.get("max_open") or 2) + 1
    n = max(4, min(400, want - have - coming))
    action = {"type": "farm_plots", "tiles": n, "dig": dig}
    first = not has_farms(s)
    if first:
        action["outside"] = True     # no farm at all: soil or grass under the sky will do until there's better
    if dig:
        action["style"] = layout_style(profile_from(traits, memory.culture or new_history()))
    proposals.append(Proposal(
        "farms", action,
        f"{have} farm tiles" + (f" (+{idle_surface} on the surface with nothing to sow)" if idle_surface else "")
        + (f" (+{coming} being dug)" if coming else "")
        + f" for a fort heading to {want} tiles: lay out {n} more on soil or muddy floor"
        + (", or dig a farm level in soil" if dig else "")
        + (" (or on the surface: the fort has no farm)" if first else ""), 2 if first else 5))


def _smelting_rule(s: dict, memory, cfg: dict, rules_: dict, proposals: list, notes: list) -> None:
    """When weapon-grade metal runs low, import DFHack's own smelting orders
    once: they smelt ore whenever bars drop below their limits."""
    gear = _d(_d(s.get("military")).get("gear"))
    bars = _d(gear.get("bars"))
    if not bars and "bars" not in gear:
        return                                       # older bridge: unknown
    total = sum(v for v in bars.values() if isinstance(v, (int, float)))
    if total >= cfg["smelt_when_bars_below"] or "smelting" in memory.libraries_imported:
        return
    if not rules_["import_smelting"]:
        return
    if "ore_stock_by" in _d(s.get("industry")):
        return              # bridge 0.49+: the AI gives its own smelting orders (_industry_rules)
    furnaces = _d(_d(s.get("buildings")).get("furnaces"))
    if not (furnaces.get("Smelter") or furnaces.get("MagmaSmelter")):
        if not _d(_d(s.get("industry")).get("ores")):
            notes.append(f"only {total} bars of weapon-grade metal, and no ore uncovered near the fort yet "
                         "(the AI builds a smelter once there is)")
        return                         # (the industry rule builds the furnaces once ore is known)
    proposals.append(Proposal("smelting", {"type": "import_orders", "library": "smelting"},
                              f"only {total} bars of weapon-grade metal: add DFHack's smelting orders "
                              "(they smelt ore whenever bars run low)", 5))


def _shoes_recipe(m: dict, stocks: dict, notes: list) -> str | None:
    """Footwear for a mandate: shoes in leather (else cloth), socks in cloth,
    low boots in leather, high boots in metal at a forge. Sandals and the
    rest are left to you."""
    sub = m.get("subtype")
    need = m.get("remaining") or 1
    if sub == "ITEM_SHOES_SOCKS":
        if stocks.get("cloth", 0) >= need:
            return "cloth_socks"
        ask_player(notes, "mandate for socks: not enough cloth")
        return None
    if sub == "ITEM_SHOES_BOOTS_LOW":
        if stocks.get("leather", 0) >= need:
            return "leather_low_boots"
        ask_player(notes, "mandate for low boots: not enough leather")
        return None
    if sub == "ITEM_SHOES_BOOTS":
        return "metal_high_boots"
    if sub not in (None, "ITEM_SHOES_SHOES"):
        ask_player(notes, f"mandate for {str(sub).replace('ITEM_SHOES_', '').lower()}: the AI has no "
                          "recipe for these; make them yourself")
        return None
    if stocks.get("leather", 0) >= need:
        return "leather_shoes"
    if stocks.get("cloth", 0) >= need:
        return "cloth_shoes"
    ask_player(notes, "mandate for shoes: not enough leather or cloth")
    return None
