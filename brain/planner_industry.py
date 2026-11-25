"""planner_industry: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

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
from planner_industry_disposal import *  # noqa: F401,F403  (r7 d4: split out by theme)
from planner_industry_stone import *  # noqa: F401,F403  (r7 d4: split out by theme)
from planner_industry_crafts import *  # noqa: F401,F403  (r7 d4: split out by theme)

__all__ = ["quarry_size", "note_quarry", "quarry_wait", "note_quarry_dug", "CONTAINER_RECIPES", "GEAR_ORDER_METALS", "_supply_rules", "_slow_game_rules", "_clutter_rules", "_disposal_rules", "DISPOSAL_RULES", "disposal_report", "disposal_places_dump", "_kiln_rules", "_soap_rule", "_pasture_rule", "LABOR_MODES_FIXED", "INDUSTRY_SHOPS", "_industry_rules", "_steel_rule", "_bottleneck_rule", "drink_lacks_containers", "drink_short", "_crop_rules", "_farm_crops_rule", "farm_plots_live", "crops_owned", "drink_known_short", "_kitchen_rule", "_seed_reserve_rule", "_fishery_rule", "_order_remake_rule", "remake_due", "_bench_coffins_rule", "STONE_CRAFTS", "order_shop", "_order_slots_rule", "_orphan_jobs_rule", "_unsuspend_rule", "_approve_rule", "_stuck_orders_rule", "COAL_STONES", "_coal_rule", "_picks_order", "_stone_rule", "stone_crisis", "PRECIOUS_ORES", "_cloth_rule", "_trade_rules", "_gems_rule", "GEMS_GENEROUS_GREED", "trade_wants", "_spare_mechanisms_rule", "_hauling_rule", "_surface_basics", "trees_this_year", "_keep_rule", "DEEP_SURFACE_KINDS", "_deep_surface_filter", "_deep_depot_choice", "_deep_depot_watch", "_free_time_rule", "_labor_rules", "OWN_LABOR_RULES", "FEEDER_ORDER", "_feeder_rule", "woodcutters", "gatherers", "trade_margin_for", "keeps_treasures", "spare_mechanisms", "_dairy_rule", "_eggs_rule", "EXCESS_SHOPS", "_excess_shops_rule", "drink_below_target", "drink_crisis", "drink_target_per_dwarf", "crisis_brew_room", "brew_jobs_open", "_labor_waiting_rule", "farm_target", "thirsty_farm_extra", "_farm_rule", "_smelting_rule", "_shoes_recipe", "_glass_rule", "PRECIOUS_METALS", "precious_metal", "_deep_plan_hint"]

CONTAINER_RECIPES = {"wooden_barrel", "stone_large_pot"}


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
    crisis_brew = 0
    if memory is not None and drink_crisis(s, memory, cfg):
        # (0.104.169) in a crisis every brew job the drink target still needs
        # wants an empty barrel or pot (the brew order is cut to the free ones)
        gap = (citizens * drink_target_per_dwarf(s, memory, cfg) - int(st.get("drink") or 0)
               - queued(s, BREW_RECIPES) * cfg["drinks_per_job"])
        crisis_brew = min(cfg["crisis_containers_max"], max(0, math.ceil(gap / cfg["drinks_per_job"])))
        want = max(want, crisis_brew)
    # (fix41) the crisis words follow the brew jobs' want, before the food raises it
    crisis_words = crisis_brew > 0 and crisis_brew >= want
    # (0.105.40b, M6) the food lying out of barrels wants some (0 without a food_store section)
    food_want = food_containers_want(s, cfg)
    food_more = food_want > want
    want = max(want, food_want)
    pending = queued(s, CONTAINER_RECIPES)
    # (r1g8) brewing waits for an empty barrel or pot: the containers come
    # first (priority 1, before the brew), from the workshop the fort has and
    # whatever wood or stone there is (F y250: "no empty barrels or pots to
    # brew into" for 3 seasons; the barrels held for want of a Carpenters')
    try:
        dry = drink_lacks_containers(s, citizens, cfg, memory)
    except Exception:
        dry = False
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
            recipe, what = None, ""
        if dry:
            recipe, what, amount = _dry_containers(s, cfg, recipe, what, amount, wood, boulders)
        if recipe is None:
            # (0.105.35) nothing waits for the player: what the AI does about it
            notes.append(f"only {free} empty barrels/pots (brewing and cooking stop without them), "
                         "and too little wood or stone to make more: the AI makes them as soon as there is "
                         "(its woodcutters fell trees, it quarries stone and buys wood from the caravans)")
        if recipe:
            proposals.append(Proposal(
                "containers", {"type": "work_order", "recipe": recipe, "amount": amount},
                f"only {free} empty barrels/pots (+{pending} queued) for {citizens} dwarves; "
                f"brewing and cooking stop without them: make {what}"
                + (f" (crisis: {crisis_brew} brew jobs wait for one)" if crisis_words else "")
                + (" (drink is under its target and the stills have nothing to brew into: first)" if dry else "")
                + (" (food lies out of barrels, where it rots or vermin eat it)" if food_more else ""),
                1 if dry else 2, True))

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
        # (0.104.138) and what the hospital itself keeps too little of: the
        # fort-wide count held crutches in use or elsewhere, and the Needs you
        # "crutches 3 of 5" never cleared (Teacheroar, 83 days)
        loc0 = _location(s, "HOSPITAL")
        lshort = _location_short(loc0, ("splints", "crutches")) if loc0 is not None else {}
        wants = [(k, r, max(n, (sup.get(k) or 0) + (lshort[k][1] - lshort[k][0]) if k in lshort else n))
                 for k, r, n in wants]
        short = [(k, r, n - (sup.get(k) or 0) - queued(s, {r})) for k, r, n in wants]
        short = [(k, r, n) for k, r, n in short if n > 0]
        if short:
            k, r, n = short[0]          # one order per cycle; the next comes after
            if wood >= n:
                proposals.append(Proposal(
                    "hospital", {"type": "work_order", "recipe": r, "amount": n},
                    f"the hospital has {sup.get(k) or 0} {k}; it should keep {n + (sup.get(k) or 0)}", 2, True))
            else:
                notes.append(f"the hospital is short of {k} but there is no wood to make them: the AI makes them "
                             "as soon as there is (its woodcutters fell trees, it buys wood from the caravans)")
        # (0.105.35) nothing waits for the player: the hospital's shortages are
        # notes of what the AI does about them (it makes, orders and buys what
        # it can), never a Needs you
        say = notes.append
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
                notes.append(f"{needing} patient(s) wait for sutures or dressings and " + text)
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
                # (0.104.140) Needs you only for what a waiting patient lacks and
                # the AI isn't making (Teacheroar: "powder 0 of 5" asked of the
                # player for 83 days while the kiln waited for bags); the rest a note
                text_ = ("the hospital keeps less than it should: " + ", ".join(
                    f"{k} {h} of {w}" for k, (h, w) in short.items())
                    + ("; plaster powder comes from gypsum at a kiln" if "powder" in short else "")
                    + ": the AI makes what it has the means for and buys the rest from the caravans")
                making = {"splints": "wooden_splint", "crutches": "wooden_crutch", "soap": "make_soap_from_tallow",
                          "powder": "make_plaster_powder"}
                lacking = [k for k in short
                           if not (k in making and queued(s, {making[k]}))
                           and ((k == "splints" and n_splint) or (k == "crutches" and n_crutch)
                                or (k in ("thread", "cloth") and care_waiting(s))
                                # (review) casts for the waiting with no gypsum to make powder from
                                or (k == "powder" and n_splint and not (sup.get("gypsum") or 0)))]
                (say if lacking else notes.append)(text_)
        elif st.get("thread", 0) < 10 or st.get("cloth", 0) < 10:
            say(f"the hospital needs thread and cloth for stitches and dressings "
                f"(thread {st.get('thread', 0)}, cloth {st.get('cloth', 0)}): the AI has them made from plants "
                "where it can and buys them from the caravans")
        # (its staff: _staff_rule makes the posts and fills them, 0.85)

    # Water: the injured can only drink water, carried from a well. With no
    # well the AI places one itself (_well_rule).
    if wells and (sup.get("buckets") or 0) == 0 and not (hospital or patients):
        proposals.append(Proposal("hospital", {"type": "work_order", "recipe": "wooden_bucket", "amount": 3},
                                  "the wells have no buckets", 3, True))


def _soap_rule(s: dict, cfg: dict, proposals: list, notes: list, say, memory=None) -> None:
    """Soap for the hospital (wounds cleaned with it don't fester): tallow
    (fat rendered at the kitchen) and lye (ash from the wood furnace, through
    the ashery into a bucket) at a soap maker's workshop, one step a cycle.
    Without fat or tallow there is nothing to make it from: bought from the
    caravans instead (trade_wants)."""
    sup = _d(s.get("supplies"))
    if "ash" not in sup:                      # an older bridge: just say it
        if (sup.get("soap") or 0) == 0:
            say("no soap for the hospital (wounds get infected): it needs lye and tallow at a soap maker's workshop; "
                "the AI buys soap from the caravans meanwhile")
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
    # (0.104.168) many wounds festering (Teacheroar: 77 infected, a bar of
    # ash, then of lye, then of soap, one step every 2 days): bigger batches,
    # and a second step of the chain in the same cycle (rule soap_rush)
    infected_n = int(_d(s.get("health")).get("infected") or 0)
    rush = infected_n >= cfg["soap_rush_infected"]
    if rush:
        need = max(need, cfg["soap_rush_batch"])
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
    if rush:      # (0.104.168) the next step of the chain too, not two days later
        nxt = next((st for st in steps if st[0] != recipe and not queued(s, {st[0]})), None)
        if nxt is not None:
            proposals.append(Proposal("soap_rush", {"type": "work_order", "recipe": nxt[0], "amount": max(1, nxt[1])},
                                      f"{infected_n} dwarves with infected wounds and {soap} of {keep} soap: "
                                      f"{nxt[2]} at the same time", 3, True))


def _bottleneck_rule(s: dict, cfg: dict, citizens: int, proposals: list, memory=None) -> None:
    """One workshop with a long queue of the AI's orders while dwarves stand
    idle (region2's one smelter: coke, pig iron, steel and ore, 40% idle):
    another workshop of that kind, through a workshops level."""
    # (0.103.1) under the urgent drink line a second still comes young fort or
    # not, idle hands or not (Enxah: 18 dwarves, 1 still, 28 brews queued,
    # drink 0-8 for a year)
    thirsty = int(_d(s.get("stocks")).get("drink") or 0) < citizens * cfg["urgent_drink_per_dwarf"]
    # (0.104.169) and in a crisis, under the crisis's drink target: the
    # stills are the lever (Teacheroar, 41% unhappy: 6 stills, drink 704 for
    # 129, 13 of 117 idle, so the idle gate never let a still through)
    crisis_dry = memory is not None and drink_crisis(s, memory, cfg) and drink_below_target(s, citizens, cfg, memory)
    thirsty = thirsty or crisis_dry
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
    # (0.105.33 merge, T1) a count that isn't a number (a None from an odd
    # report) is none: `None >= 1` stopped the rule
    places = {k: (v if isinstance(v, int) and not isinstance(v, bool) else 0)
              for k, v in {**_d(b.get("workshops")), **_d(b.get("furnaces"))}.items()}
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
    short_ = {"Still": int(st_.get("drink") or 0) < citizens * drink_target_per_dwarf(s, memory, cfg),
              "Kitchen": int(st_.get("prepared_meals") or 0) < citizens * cfg["meals_per_dwarf"],
              # (0.104.141) and Masons' workshops while the open levels wait for
              # much furniture (Teacheroar: 122 pieces on 5, the cap at 209)
              "Masons": sum(int(n or 0) for p in open_ for k, n in _d(_d(p.get("furnish")).get("waiting")).items()
                            if k in ("Table", "Chair", "Coffin", "Door", "Cabinet", "Box", "Statue", "Slab"))
                        >= cfg["furniture_short_pieces"]}
    def cap_(shop):
        if shop == "Still" and crisis_dry:
            return shops_max(cfg, citizens) * cfg["crisis_stills_cap_factor"]     # (0.104.169)
        return shops_max(cfg, citizens) * (2 if short_.get(shop) else 1)
    worst = sorted(((n / max(1, places.get(shop, 0)), n, shop) for shop, n in backlog.items()
                    if shop in BUILDABLE_SHOPS and places.get(shop, 0) >= 1
                    and places.get(shop, 0) < cap_(shop)), reverse=True)
    if thirsty and (young_fort(s, cfg) or idle < cfg["idle_share"]):
        worst = [w for w in worst if w[2] == "Still"]       # only the still, for the thirsty
    need = cfg["shop_backlog"]
    if thirsty and worst and worst[0][2] == "Still":
        need = cfg["thirsty_still_backlog"]                 # (Enxah: 12 brews on one still, drink 13 for 18)
    elif worst and worst[0][2] == "Masons" and short_["Masons"]:
        need = cfg["shop_backlog"] // 2                     # (0.104.141) furniture the levels wait for
    if worst and worst[0][0] >= need:
        _, n, shop = worst[0]
        # (0.99.4) drink and food first: a still or kitchen goes ahead of the
        # craft shops wanted for needs (one workshops level at a time)
        # (0.105.51) a second Carpenters' while drink is short for want of
        # barrels and pots goes in as urgent (F: one Carpenters' with 15-21
        # jobs queued, refused 25 times by the full slots, drink under its
        # target with no empty barrel to brew into)
        dry_casks = shop == "Carpenters" and drink_lacks_containers(s, citizens, cfg, memory)
        proposals.append(Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": [shop],
                                                 **({"urgent": True} if (thirsty and shop == "Still") or dry_casks
                                                    else {})},
                                  f"{n} jobs of the AI's orders wait on {places.get(shop)} {shop} and "
                                  + (f"drink is under the crisis's target ({cfg['crisis_drink_share']:g}x): build "
                                     "another (being drunk eases the fort's stress most)"
                                     if crisis_dry and shop == "Still" else
                                     "drink is under its target with no empty barrels or pots to brew into: "
                                     "build another (URGENT)" if dry_casks else
                                     f"{round(100 * idle)}% of the dwarves are idle: build another"),
                                  3 if shop in ("Still", "Kitchen") or dry_casks else 6))


def _dry_containers(s: dict, cfg: dict, recipe, what, amount: int, wood: int, boulders: int):
    """(r1g8) The containers order while brewing waits for them: barrels or
    rock pots from the workshop the fort has (a barrel order with no
    Carpenters' is held, a pot order with no Craftsdwarf's likewise), and
    from the wood or stone there is, not only the spare (drink comes before
    beds). Returns (recipe, what, amount); recipe None when neither can go."""
    from order_check import order_feasible
    small = int(cfg.get("r1g8_dry_containers_min", 3))
    stock = {"wooden_barrel": int(wood or 0), "stone_large_pot": int(boulders or 0)}
    words = {"wooden_barrel": "barrels", "stone_large_pot": "rock pots"}
    order = [recipe] if recipe else []
    order += [r for r in ("wooden_barrel", "stone_large_pot") if r not in order]
    for r in order:
        n = min(amount, stock[r])
        if n < small:
            continue
        try:
            ok = order_feasible(r, s, {"recipe": r, "amount": n}, cfg)["ok"]
        except Exception:
            ok = True
        if ok:
            return r, (what if r == recipe and what else words[r]), n
    return None, what, amount


def drink_lacks_containers(s: dict, citizens: int, cfg: dict, memory=None) -> bool:
    """(0.105.51) Drink under its target and fewer than `drink_containers_low`
    empty barrels and pots left once the open brew jobs have theirs."""
    sup = _d(s.get("supplies"))
    if not isinstance(sup.get("empty_barrels"), int) or not drink_below_target(s, citizens, cfg, memory):
        return False
    free = sup["empty_barrels"] + int(sup.get("empty_pots") or 0) - brew_jobs_open(s)
    return free < cfg["drink_containers_low"]


# (0.105.23, 14.1 step 4c) Surface -80 or lower (the Deep mine): what may
# still go above ground. The trade depot only when no wagon road down was
# found (then at the way in, the nearest open spot 4 tiles out; the player:
# a depot can be underground when the wagons' way is 3 wide with ramps, so
# it goes down a road the bridge digs: `deep_depot`), the refuse pile
# (rot indoors makes miasma), the garbage dump and the cage pile (marked
# ground, nothing built). Pastures stay too: grazers starve without grass and
# the AI has no underground pasture (cavern moss is not looked for). Farm
# plots go underground only (on the surface only before the first stair);
# no keep, no surface farm, no level at or above the surface.
DEEP_SURFACE_KINDS = ("depot", "refuse", "dump", "cages")


def _deep_surface_filter(s: dict, traits: dict, memory, proposals: list, notes: list) -> list:
    """(0.105.23, 14.1 step 4c) The Deep mine keeps under the ground: the
    six forts at y257 each had a level at or above the surface, E (Surface
    -100) as much as F (+80). Drops what would go above ground, sends every
    new level (and farm level) a ceiling one under the surface (`max_elev`,
    the builder's search keeps under it), and farms underground only."""
    if not masterplan.underground_only(traits):
        if customs.has(traits, "hidden_hold"):
            # (0.105.29) the Hermit hold's custom: no new level at or above the
            # surface; farms, the depot, the keep and the surface stay as they are
            ceil = masterplan.ceiling(memory, traits) if memory is not None else None
            if ceil is not None:
                for p in proposals:
                    a = p.action
                    if isinstance(a, dict) and a.get("type") == "start_project":
                        own = a.get("max_elev")
                        if isinstance(own, int) and own <= ceil:
                            continue       # (customs fixes) already under it: the custom changed nothing
                        p.action = dict(a, max_elev=ceil,
                                        customs=sorted(set(_l(a.get("customs"))) | {"hidden_hold"}))
        return proposals
    ceil = masterplan.ceiling(memory, traits) if memory is not None else None
    founding = _d(s.get("founding")).get("stairs") is False
    out, dropped = [], []
    for p in proposals:
        a = p.action
        t = a.get("type")
        if t == "place_keep" or p.rule == "surface_farm":
            dropped.append(p.rule)
            continue
        if t == "place_surface" and a.get("kind") not in DEEP_SURFACE_KINDS:
            dropped.append(p.rule)
            continue
        if t == "farm_plots":
            a = dict(a)
            if a.get("outside") and not founding:
                a.pop("outside", None)          # soil or muddy floor inside the fort only
            if a.get("dig") and ceil is not None:
                a["max_elev"] = ceil
            p.action = a
        elif t == "start_project" and ceil is not None:
            p.action = dict(a, max_elev=ceil)
            plan = _deep_plan_hint(p.action, memory, traits, s)
            if plan:
                p.action["plan"] = plan
        elif t == "place_surface" and a.get("kind") == "depot":
            p = _deep_depot_choice(s, p, notes)
            if p is None:
                continue
        out.append(p)
    if dropped:
        notes.append("Surface " + str(traits.get("surface", 0)) + ": nothing above ground ("
                     + ", ".join(sorted(set(dropped))) + " left out); the trade depot goes underground down a "
                     "wagon road, only the refuse pile and the pastures stay outside")
    return out


def _deep_plan_hint(action: dict, memory, traits: dict, s: dict) -> dict | None:
    """(group 6) The Deep mine's levels go to their district of the deep plan,
    every rule's level and not only the build ladder's. Fort E (y264-267): 53
    of its 83 levels came from other rules (bottleneck, paper_shop,
    needs_shops, industry, kiln...) with no hint, and the builder's ordinary
    search put each on the level nearest the dwarves (the homes, elevation
    32-35) instead of the industry band at the bottom of the plan (22-25).
    Urgent levels (a mood's workshop, tombs for ghosts, the tavern) keep the
    nearest level: speed first. None when the level has its own hint, the
    fort has no plan, or the plan has no district for the kind. The builder
    tries the district first and falls back to its ordinary search."""
    kind = action.get("kind")
    if (memory is None or not isinstance(kind, str) or kind == "farms" or action.get("urgent")
            or isinstance(action.get("plan"), dict) or not masterplan.has_plan(memory)):
        return None
    try:
        profile = profile_from(traits, (memory.culture if isinstance(memory.culture, dict) else None)
                               or new_history())
    except Exception:  # noqa: BLE001  (the door rule only)
        profile = {}
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    where = masterplan.hint(memory, kind, slot=action.get("set_piece"), traits=traits, profile=profile,
                            action=action, citizens=citizens)
    if not where:
        return None
    where["doors"] = ("fortified" if (traits.get("fortification", 0) or 0) >= 70
                      else "doored" if profile.get("entry_doors") else "open")
    cs = sorted(set(_l(action.get("customs"))) | set(_l(where.get("customs"))))
    if cs:
        action["customs"] = cs
    return where


def _deep_depot_choice(s: dict, p, notes: list):
    """(0.105.23, 14.1 step 4c) The Deep mine's trade depot: underground,
    down a 3-wide ramp road the wagons can use (the player: a depot can be
    underground when the wagons' way is right), dug by the bridge a step at a
    time (`deep_depot`); while the road is being dug, a note; when no road
    was found (the bridge says `no_road`), the surface depot at the way in."""
    dd = _d(_d(s.get("buildings")).get("deep_depot"))
    stage = dd.get("stage")
    if stage == "no_road":
        why = dd.get("why") or "no safe way down"
        if "the way in" not in p.reason:
            p.reason += " (the Deep mine's one building above ground: at the way in; no wagon road down was found)"
        notes.append(f"the underground trade depot: no wagon road down ({why}); the depot goes up at the way in")
        return p
    if stage == "digging" and (dd.get("tiles_left") or 0) > 0 and not dd.get("stalled"):
        notes.append(f"the underground trade depot: {dd['tiles_left']} tile(s) of its wagon road and hall "
                     "still to dig")
        return None
    if stage == "digging" and (dd.get("tiles_left") or 0) > 0:
        why = f"the underground trade depot: {dd['stalled']} tile(s) of the wagon road lost their digging, mark them again"
    elif stage in ("digging", "placed"):
        why = "the underground trade depot: its road and hall are dug, place the depot in the hall"
    else:
        why = ("no trade depot: the Deep mine's goes underground: a wagon road 3 tiles wide, ramps not stairs, "
               "down from open ground by the way in to a hall with the depot (cloth, rope, metal, seeds the "
               "fort can't make)")
    return Proposal(p.rule, {"type": "deep_depot"}, why, p.priority, p.is_order)


def _deep_depot_watch(s: dict, notes: list, proposals: list | None = None) -> None:
    """(0.105.23, 14.1 step 4c) Once the underground depot stands, what the
    game says of the wagons: when it says they can't reach it, a note
    (the AI doesn't dig on blindly). Nothing when the game doesn't show
    it (the report's `wagon_access` is then missing).

    (0.105.30, deep depot) Fort E's depot read "wagons can't reach it" and the
    line said only "look at its road". The bridge now walks the road as a
    wagon would (DFHack's own rule: 3x3 round every step, ramps, no doors) and
    names the first thing in the way (`wagon_block`); DFHack's own check is
    read too (`dfhack_wagon_access`). A tree, a boulder, a tile left undug or
    a door on the AI's own road: `deep_depot` clears it. Anything else: a
    note that names the tile (0.105.35: never a Needs you; the caravans'
    pack animals still come)."""
    dd = _d(_d(s.get("buildings")).get("deep_depot"))
    if dd.get("depot") != "built":
        return
    at = f"x{dd.get('x')} y{dd.get('y')} elevation {dd.get('elevation')}"
    acc, dh = dd.get("wagon_access"), dd.get("dfhack_wagon_access")
    if acc is True:
        return
    # (0.105.35) nothing waits for the player: whatever the AI can't clear,
    # the caravans still come, their pack animals walking to the depot without
    # the wagons (DF wiki, "Their wagons have bypassed your inaccessible
    # site"), and the AI trades with them as with any; the game looks at the
    # wagons' way again as each caravan comes. A note, never a Needs you.
    meanwhile = ("; meanwhile the caravans still come, with pack animals and no wagons (fewer goods), and the "
                 "AI trades with them as usual")
    if acc is False and dh is True:
        notes.append(f"the game says the caravans' wagons can't reach the underground trade depot at {at}, "
                     "but DFHack's own wagon check finds a 3-wide way to it: the game looks at the wagons' way "
                     "again when the next caravan comes" + meanwhile)
        return
    blk = _d(dd.get("wagon_block"))
    check = dd.get("wagon_check")
    text = blk.get("text") or (f"{blk.get('what')} at x{blk.get('x')} y{blk.get('y')} "
                               f"elevation {blk.get('elevation')}" if blk else "")
    opens = _d(dd.get("opens_fort"))
    open_words = (f"; the depot's hall opens into the fort at x{opens.get('x')} y{opens.get('y')} elevation "
                  f"{opens.get('elevation')}, and what stands there may be the fort's gate, so the AI leaves "
                  "it") if opens else ""
    if check == "blocked" and blk:
        fix = blk.get("fix")
        if fix and blk.get("pending"):
            notes.append(f"the underground trade depot: its wagons' way is being cleared ({text})")
            return
        if fix and proposals is not None:
            what = {"fell": "fell the tree(s)", "smooth": "smooth the boulder(s)", "redig": "dig it again",
                    "remove": "take it down (no door, hatch or trap on the wagons' road)"}.get(fix, fix)
            proposals.append(Proposal("depot", {"type": "deep_depot"},
                                      f"the caravans' wagons can't reach the underground trade depot at {at}: "
                                      f"{text}: {what}", 6))
            return
        if acc is False:
            notes.append(f"the game says the caravans' wagons can't reach the underground trade depot at "
                         f"{at}; the first thing in their way, as the AI sees it: {text}"
                         + (f" (the AI clears it: {fix})" if fix else
                            " (not the AI's to clear: the fort's own or the land's)")
                         + open_words + meanwhile)
        else:
            notes.append(f"the underground trade depot at {at}: the AI's own wagon check finds {text}")
        return
    if acc is False and check == "clear":
        notes.append(f"the game says the caravans' wagons can't reach the underground trade depot at {at}, "
                     "but the AI finds nothing in their way along its road and over the surface to the map's edge "
                     "(caravans bring wagons only to a fort with a landholder, a baron or higher, or the "
                     f"capital){open_words}" + meanwhile)
        return
    if acc is False:
        notes.append(f"the game says the caravans' wagons can't reach the underground trade depot at {at}, and "
                     "the AI's own wagon check can't tell what is in the way (3 tiles wide all the way from the map's "
                     "edge, ramps not stairs, nothing built, no trees or boulders)" + meanwhile)
