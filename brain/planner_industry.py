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
from planner_orders import *  # noqa: F401,F403  (13c: split out by theme)
from planner_trade import *  # noqa: F401,F403  (13c: split out by theme)
from planner_labor import *  # noqa: F401,F403  (13c: split out by theme)
from planner_farms import *  # noqa: F401,F403  (13c: split out by theme)

__all__ = ["CONTAINER_RECIPES", "GEAR_ORDER_METALS", "_supply_rules", "_slow_game_rules", "_clutter_rules", "_kiln_rules", "_soap_rule", "_pasture_rule", "LABOR_MODES_FIXED", "INDUSTRY_SHOPS", "_industry_rules", "_steel_rule", "_bottleneck_rule", "drink_short", "_crop_rules", "_farm_crops_rule", "farm_plots_live", "crops_owned", "drink_known_short", "_kitchen_rule", "_fishery_rule", "_bench_coffins_rule", "STONE_CRAFTS", "order_shop", "_order_slots_rule", "_orphan_jobs_rule", "_unsuspend_rule", "_approve_rule", "_stuck_orders_rule", "COAL_STONES", "_coal_rule", "_picks_order", "_stone_rule", "stone_crisis", "PRECIOUS_ORES", "_cloth_rule", "_trade_rules", "_gems_rule", "trade_wants", "_spare_mechanisms_rule", "_hauling_rule", "_surface_basics", "trees_this_year", "_keep_rule", "DEEP_SURFACE_KINDS", "_deep_surface_filter", "_deep_depot_choice", "_deep_depot_watch", "_free_time_rule", "_labor_rules", "OWN_LABOR_RULES", "FEEDER_ORDER", "_feeder_rule", "woodcutters", "gatherers", "trade_margin_for", "keeps_treasures", "spare_mechanisms", "_dairy_rule", "_eggs_rule", "EXCESS_SHOPS", "_excess_shops_rule", "drink_below_target", "drink_crisis", "drink_target_per_dwarf", "crisis_brew_room", "brew_jobs_open", "_labor_waiting_rule", "farm_target", "thirsty_farm_extra", "_farm_rule", "_smelting_rule", "_shoes_recipe", "_glass_rule", "PRECIOUS_METALS", "precious_metal"]

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
    crisis_brew = 0
    if memory is not None and drink_crisis(s, memory, cfg):
        # (0.104.169) in a crisis every brew job the drink target still needs
        # wants an empty barrel or pot (the brew order is cut to the free ones)
        gap = (citizens * drink_target_per_dwarf(s, memory, cfg) - int(st.get("drink") or 0)
               - queued(s, BREW_RECIPES) * cfg["drinks_per_job"])
        crisis_brew = min(cfg["crisis_containers_max"], max(0, math.ceil(gap / cfg["drinks_per_job"])))
        want = max(want, crisis_brew)
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
                f"brewing and cooking stop without them: make {what}"
                + (f" (crisis: {crisis_brew} brew jobs wait for one)" if crisis_brew >= want else ""), 2, True))

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
                # (0.104.140) Needs you only for what a waiting patient lacks and
                # the AI isn't making (Teacheroar: "powder 0 of 5" asked of the
                # player for 83 days while the kiln waited for bags); the rest a note
                text_ = ("the hospital keeps less than it should: " + ", ".join(
                    f"{k} {h} of {w}" for k, (h, w) in short.items())
                    + ("; plaster powder comes from gypsum at a kiln" if "powder" in short else ""))
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
        # (0.104.149) no more `tidy` (DFHack cleanowned scattered x) here: it
        # took every owned thing off the floor (the trinkets just given) and
        # every slightly worn garment off its wearer, all carried to the dump
        # (68 times a night in Teacheroar), and the dump keeps them on the map;
        # prune_remains' "clothes" below rots the thrown-down clothes for real
    # (0.105.3) B (2 Nov): 17,471 items at 1-3 FPS, so none of the clean-ups
    # below (all behind fps_items_heavy, 30,000) ran. The census' own counts
    # decide them now (_clutter_rules, run at any speed); `heavy` still lets
    # the old corpses rot when the census hasn't counted yet
    _clutter_rules(s, cfg, proposals, notes, memory, heavy=items >= cfg["fps_items_heavy"])


def _clutter_rules(s: dict, cfg: dict, proposals: list, notes: list, memory=None, heavy: bool = False) -> None:
    """(0.105.3) What the last census says lies about, cleared: loose spider
    webs far from the fort (remove_webs), dead creatures on the game's unit
    list (fix/dead-units) and old corpses on the ground (deteriorate). Lower
    bars while the game runs slowly. Called by the slow-game rules and, at any
    speed, by the planner itself (with heavy False)."""
    slow = bool(s.get("fps_low"))
    now = abs_tick(s)
    cen = _d(getattr(memory, "census", None)) if memory is not None else {}
    # a census older than four weeks says too little to act on (heavy alone still prunes)
    if not (isinstance(cen.get("tick"), int) and 0 <= now - cen["tick"] < 28 * TICKS_PER_DAY):
        cen = {}
    last = (lambda r: memory.last_fired.get(r)) if memory is not None else (lambda r: None)

    def due(rule, days):
        t = last(rule)
        return t is None or not 0 <= now - t < days * TICKS_PER_DAY

    ic = _d(_d(cen.get("items")).get("counts"))
    items = int(_d(_d(s.get("logistics")).get("counts")).get("items") or ic.get("total") or 0)
    # (0.105.3) loose webs outside the fort's areas (the census' webs_removable,
    # from 0.105.3's bridge): past 1,000 while slow, past 5,000 at any speed, a
    # week apart, a batch a day while the last call left more. Webs are silk
    # for cloth, but thousands far off cost more FPS than their thread is worth
    far = ic.get("webs_removable")
    if isinstance(far, int):
        more = bool(_d(cen.get("webs_left")).get("more"))
        if (far >= (cfg["remove_webs_slow_min"] if slow else cfg["remove_webs_min"])
                and due("remove_webs", cfg["remove_webs_more_days"] if more else cfg["remove_webs_days"])):
            kept = _d(_d(_d(cen.get("items")).get("webs")).get("kept"))
            near = int(kept.get("fort") or 0)
            proposals.append(Proposal("remove_webs", {"type": "remove_webs", "max": cfg["remove_webs_max"]},
                                      f"{far} spider webs lie far from the fort ({ic.get('webs')} in all, "
                                      f"{items} items on the map): remove up to {cfg['remove_webs_max']}"
                                      + (f"; the {near} near the fort stay for the weavers" if near else ""), 7))
    elif heavy and slow:
        # (0.104.116) a census from an older bridge: every web, a season apart
        webs = ic.get("webs")
        if isinstance(webs, int) and webs >= cfg["webs_clear_min"] and due("webs", 84):
            proposals.append(Proposal("webs", {"type": "clear_webs"},
                                      f"{webs} spider webs lie in the caverns, a big share of the {items} items "
                                      "slowing the game: clear them (DFHack's clear-webs)", 7))
    # (0.104.158) dead creatures on the game's unit list: DFHack's
    # fix/dead-units scrubs the slaughtered, nameless and foreign dead a month
    # old, never the fort's own race (its isOwnRace test; merchants' and
    # diplomats' too are kept). (0.105.3) B: 151 scrubbable (100 turkeys),
    # under the old 1,000: now 100 while slow, two weeks apart
    uc = _d(_d(cen.get("units")).get("counts"))
    scrub = uc.get("dead_scrubbable")
    if isinstance(scrub, int):
        lo, days = ((cfg["dead_scrub_slow_min"], cfg["dead_scrub_slow_days"]) if slow
                    else (cfg["dead_scrub_min"], cfg["dead_scrub_days"]))
        if scrub >= lo and due("dead_units", days):
            proposals.append(Proposal("dead_units", {"type": "scrub_dead_units"},
                                      f"{uc.get('dead')} of the {uc.get('total')} creatures on the game's list are dead "
                                      f"(up to {scrub} slaughtered or nameless): clear the old ones (DFHack's "
                                      "fix/dead-units; the fort's own dead are kept)", 7))
    if not slow:
        return
    # (0.104.0) old remains rot away: non-entombed corpses and body parts
    # nobody can craft with (DFHack deteriorate; stays on in the save)
    # (0.104.115) the census says what lies about: thousands of butchered
    # bones and shells, or worn clothes thrown down, rot away too
    ground = {str(_d(x).get("name")): int(_d(x).get("n") or 0)
              for x in _l(_d(cen.get("items")).get("on_ground"))}
    # (0.105.3) B: 69 corpses, 76 parts and 52 remains on the ground with
    # 17,471 items: rotted from 100 while slow, but only with no citizen
    # unburied (deteriorate spares only the entombed, so a dwarf's body
    # waiting for a coffin would rot too)
    bodies = sum(ground.get(k, 0) for k in ("CORPSE", "CORPSEPIECE", "REMAINS"))
    unburied = _d(s.get("dead")).get("unburied")
    few_bodies = bodies >= cfg["corpses_ground_min"] and unburied == 0
    if not (heavy or few_bodies):
        return
    extra = []
    if ground.get("CORPSEPIECE", 0) >= cfg["prune_parts_min"]:
        extra.append("usable-parts")
    worn = {str(_d(x).get("name")): int(_d(x).get("n") or 0) for x in _l(_d(cen.get("items")).get("worn"))}
    if sum(worn.get(k, 0) for k in ("SHOES", "GLOVES", "PANTS", "ARMOR", "HELM")) >= cfg["prune_worn_min"]:
        extra.append("clothes")
    action = {"type": "prune_remains"}
    if extra:
        action["extra"] = extra
    what = (" (and " + ", ".join({"usable-parts": f"{ground.get('CORPSEPIECE', 0)} bones, shells and hair on the "
                                                   "ground", "clothes": "worn clothes thrown down"}[e]
                                  for e in extra) + ")") if extra else ""
    if heavy:
        reason = (f"{items} items on the map slow the game: old corpses and useless body "
                  f"parts lying about rot away{what} (entombed dead are kept)")
    else:
        reason = (f"{bodies} corpses and remains lie on the ground while the game runs slowly: they rot "
                  f"away{what} (no citizen waits for burial; entombed dead are kept)")
    proposals.append(Proposal("prune", action, reason, 7))


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
        proposals.append(Proposal("bottleneck", {"type": "start_project", "kind": "workshops", "shops": [shop],
                                                 **({"urgent": True} if thirsty and shop == "Still" else {})},
                                  f"{n} jobs of the AI's orders wait on {places.get(shop)} {shop} and "
                                  + (f"drink is under the crisis's target ({cfg['crisis_drink_share']:g}x): build "
                                     "another (being drunk eases the fort's stress most)"
                                     if crisis_dry and shop == "Still" else
                                     f"{round(100 * idle)}% of the dwarves are idle: build another"),
                                  3 if shop in ("Still", "Kitchen") else 6))


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
    # (0.105.19) ghosts need a slab each, not 30 boulders: C (3 Nov) had 2
    # ghosts haunting 31 citizens, limonite 27 and tetrahedrite 27, the slab
    # ordered and cancelled as stuck six times in an hour
    ore_min = cfg["stone_ore_min"]
    if int(_d(s.get("dead")).get("ghosts") or 0) > 0:
        ore_min = min(ore_min, cfg["stone_ore_ghost_min"])
    ores = sorted(((int(v.get("n") or 0), k) for k, v in econ.items()
                   if v.get("ore") and k not in PRECIOUS_ORES and int(v.get("n") or 0) >= ore_min),
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
    # (0.105.22) never the dead's slabs and coffins while ghosts walk or bodies
    # wait: they can't be made in wood, and B (3-5 Nov) ordered and cancelled
    # the slab 181 times while 41 ghosts rose (the ore, the quarry and the
    # mason's labour are what get them made)
    dd = _d(s.get("dead"))
    keep = {"stone_slab", "stone_coffin"} if (int(dd.get("ghosts") or 0) > 0
                                             or int(dd.get("unburied") or 0) > 0) else set()
    for k, w in sorted(memory.order_watch.items()) if memory is not None else []:
        if (isinstance(w, dict) and w.get("by_ai") and str(w.get("what", "")).startswith("stone_")
                and str(w.get("what")) not in keep
                and isinstance(w.get("since"), int) and (now - watch_since(w)) // TICKS_PER_DAY >= cfg["order_stuck_days"]):
            # (0.105.24) booked as stuck (`stuck`), so the recipe waits its 28-112
            # days and a rule asking again gets the wooden one (stuck_fallback):
            # A (2-5 Nov) cancelled stone_door and stone_slab 276 times, the
            # planned-parts rule ordering stone_door again after each
            proposals.append(Proposal("stone", {"type": "cancel_work_order", "order_id": int(k),
                                                "stuck": str(w.get("what"))},
                                      f"no stone the masons may use and {w.get('what')} hasn't moved in "
                                      f"{(now - watch_since(w)) // TICKS_PER_DAY} days: cancel it (made in wood instead)", 4))
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
    # (0.105.24) a strange mood waiting for a rough or a cut gem it can't find:
    # the jewellers leave the last ones alone (E, 3 Nov: moods failed on "a
    # rough gem" while the AI cut 4-7 at a time down to under 5)
    waits = mood_waits(s)
    if (_has_shop(s["buildings"], "Jewelers") and int(cg.get("n") or 0) >= cfg["gems_cut_at"]
            and "cut_gem" not in waits
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
        # (0.105.23) the bridge looks round every way in first, then for open
        # flat ground near the surface farms (F: 39 refusals on a slope)
        why = ("Surface ambition: a walled keep with one door, the first building above ground: "
               "round the way in from the surface, else on open ground near the fields")
    elif k.get("stage") == "clearing":
        why = "the keep: the trees are down, raise its walls and door"
    elif k.get("stage") == "walls":
        why = "the keep: its walls stand, put a roof over the inside"
    else:
        why = "the keep: its roof is built, call it finished"
    proposals.append(Proposal("keep", {"type": "place_keep"}, why, 7))


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


def _deep_depot_watch(s: dict, notes: list) -> None:
    """(0.105.23, 14.1 step 4c) Once the underground depot stands, what the
    game says of the wagons: when it says they can't reach it, a Needs you
    line (the AI doesn't dig on blindly). Nothing when the game doesn't show
    it (the report's `wagon_access` is then missing)."""
    dd = _d(_d(s.get("buildings")).get("deep_depot"))
    if dd.get("depot") != "built":
        return
    at = f"x{dd.get('x')} y{dd.get('y')} elevation {dd.get('elevation')}"
    if dd.get("wagon_access") is False:
        notes.append(NEEDS_YOU + f"the game says the caravans' wagons can't reach the underground trade depot at {at}: "
                     "look at its road (3 tiles wide all the way from the map's edge, ramps not stairs, nothing "
                     "built, no trees or boulders on it) or build a depot on the surface")


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
EXCESS_SHOPS = {"SoapMaker": 2}


def _excess_shops_rule(s: dict, cfg: dict, proposals: list) -> None:
    places = {**_d(_d(s.get("buildings")).get("workshops"))}
    for name, most in EXCESS_SHOPS.items():
        n = sum(places.get(k, 0) for k in SHOP_ALIASES.get(name, (name,)))
        if n > most:
            proposals.append(Proposal("excess_shops", {"type": "remove_workshops", "kind": name, "keep": 1,
                                                       "max": 20},
                                      f"{n} {name} workshops (one is enough): take down the idle extras", 6))


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
