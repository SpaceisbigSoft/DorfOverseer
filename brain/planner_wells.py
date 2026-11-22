"""planner_wells: wells, cisterns and the water near the fort (split out of
planner_building in 0.105.25, 13c): the well and its lid, cavern wells and
their danger, the well's and the cistern's parts, water zones and traffic,
the water summary. planner_building re-exports every name here."""

from __future__ import annotations

import math
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_slots import need_slots_free  # noqa: E402  (R2 h3) the small needs' pool
from planner_wells_caverns import *  # noqa: F401,F403  (r7 d4: split out by theme)
from planner_wells_water import *  # noqa: F401,F403  (r7 d4: split out by theme)

__all__ = ["_well_rule", "_well_lid_rule", "SHAFT_LINK_LOST_MAX", "SHAFT_DANGER_TILES", "SHAFT_DANGER_OPEN", "SHAFT_DRY_REACH", "shaft_judged", "shaft_danger_words", "shaft_far_walker", "shaft_water_short", "cavern_danger", "_water_zone_rule", "cavern_points", "cavern_action", "cavern_well_need", "unfound_cavern", "cavern_well_safe", "WELL_PARTS_SHOPS", "CHAIN_SKIP", "chain_metal", "well_parts_plan", "_well_parts", "_water_traffic_rule", "cistern_pop", "WATER_WORDS", "magma_access", "water_summary", "_water_rules", "CISTERN_WORDS", "_cistern_parts", "_cistern_rule", "WELLS_CONFIG", "shut_wells", "usable_wells", "bad_wells", "water_zones_usable", "no_water_cancels", "cavern_open_danger", "ai_opens_cavern", "cavern_soldiers_ready", "cavern_open_words", "CISTERN_RETRY_SEALS", "CISTERN_RELINK_ROUNDS", "CISTERN_SHUT_RULE", "jailed", "cavern_failure_now", "drinkable_frost_wells", "frost_zone_case", "shut_columns", "winter_wells", "winter_water_need", "climate_freezes_now", "_winter_water_rule", "WELL_MIN_DEPTH", "filling_cisterns", "winter_cistern_action", "WINTER_CISTERN_WORDS"]


def _well_rule(s: dict, memory, traits: dict, cfg: dict, proposals: list, notes: list) -> None:
    """A well when there's none, placed by the AI itself; and what a new well
    is still waiting for."""
    # (0.105.33 B4) a cavern well with its shaft gate shut draws no water.
    # (0.105.36) But a shaft shut for a danger near it is shut for a while
    # only: still a well (no second shaft into the same cavern for a passing
    # cave spider), and no cavern well is begun while the danger is near
    pr = _d(s.get("projects"))
    lids = [x for x in _l(pr.get("well_lids")) if isinstance(x, dict) and x.get("gate")]
    shaft_danger = ""
    judged = shaft_judged(lids)
    if lids:
        # (group 2) by the bridge's own verdict when it gives one (a shut gate
        # whose hold runs is shut for a while only too); the report's threat
        # list only for an older bridge
        shaft_danger = "" if judged else cavern_danger(s, lids, SHAFT_DANGER_OPEN)
        if not shaft_danger:
            near = next((_d(x.get("watch_near")) for x in lids if _d(x.get("watch_near"))), None)
            if near:
                shaft_danger = str(near.get("name") or "a wild beast")
        if not shaft_danger and judged and any((x.get("shut_hold") or 0) > 0 for x in lids
                                               if x.get("gate") == "closed"):
            shaft_danger = "a danger lately"
    if shaft_danger:
        # (K48-K4) a dry well (nothing under it) is no well, shut shaft or not
        wells = max(0, int(_d(_d(s.get("buildings")).get("other")).get("Well", 0) or 0)
                    - bad_wells(s, ("dry",), ()))
        if shut_wells(s, ("closed",)) and not judged:
            notes.append(f"the cavern well's shaft is shut while {shaft_danger} is near: still counted as a well")
    else:
        # (K48-K4) frozen wells are left to the frost rule (planner_hazards places one inside)
        wells = usable_wells(s, ("closed",), drinkable=False)
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    building = [p for p in open_ if p.get("kind") == "well"]
    if building:
        _well_parts(s, memory, cfg, building, proposals, notes)
    # (r2 h2) a winter cistern being made is no well yet and is filled from
    # the fort's other water: the ordinary (shore) well goes on beside it
    if [p for p in building if not _d(p.get("summary")).get("filled")]:
        return
    # (0.105.3) Hammerstirred (2 Nov): the cavern well was refused once for
    # "no floor over cavern water" and never tried again, while the lake lay
    # beside the fort. Now it may dig a gallery out to it: tried once more.
    # (0.105.4 review) once, by a flag (record sets it when a cavern well with a
    # gallery comes back): the refusal's text is cut to 300 characters, so
    # "gallery" in it was no sure sign. plan() itself only reads it.
    cavern_failure = cavern_failure_now(s, memory, cfg)
    if (memory is not None and cfg["cavern_well_gallery"] > 0 and not memory.cavern_gallery_retried
            and cavern_failure.startswith("no floor inside the fort over cavern water")):
        cavern_failure = ""
    if wells:
        # (0.104.141, 12k) wells by the dwarves per well: Teacheroar's 209
        # dwarves (124 patients at the worst) shared one well
        cit = int(_d(s.get("dwarves")).get("total") or 0)
        per = cfg["dwarves_per_well"]
        if not per or wells >= math.ceil(cit / per):
            return
        # (r1 g3) the slot cap held every fort's building slots full (A3 B3),
        # so "a well for every 70" returned here without a word in all six
        # forts: another well takes g3_extra_well_slots over it
        slots = (pr.get("max_open") or 2) + int(cfg.get("g3_extra_well_slots", 1) or 0)
        # (R2 h3) or a place in the small needs' pool (the bridge's need_slots_free)
        if len(open_) >= slots and not need_slots_free(s):
            notes.append(f"{cit} dwarves share {wells} well(s) (one for every {per} wanted): another waits for a "
                         "free building slot")
            return
        # (the bridge takes a project over its cap only as urgent)
        over_cap = len(open_) >= (pr.get("max_open") or 2)
        last = memory.last_fired.get("extra_well") if memory is not None else None
        # (0.104.148) no ordinary spot because the only water below is a
        # cavern (Teacheroar, 1 Nov: 163 dwarves on one well, 4 dead of
        # thirst overnight, "another couldn't be placed ... in a cavern" every
        # season): the cavern well, as for a fort with none, when it's needed
        # and safe and none has failed before
        # (r1 g3) any refusal of an ordinary well, not only one naming the
        # cavern: E's "no open drop ...; no pond, brook or river within 40"
        # kept 90 dwarves on one cavern well for years, an ordinary well tried
        # again each season and the cavern never
        if (memory is not None and memory.extra_well_failure
                and not cavern_failure):
            patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
            need = cavern_well_need(s, cfg, patients) or f"{cit} dwarves share {wells} well(s)"
            safe = cavern_well_safe(s, cfg)
            if safe is True and shaft_danger:
                safe = f"{shaft_danger} is near the cavern well"
            if safe is True:
                urgent = bool(patients or int(_d(s.get("society")).get("parched") or 0))
                action = cavern_action(s, cfg, urgent or over_cap)       # (0.105.3)
                proposals.append(Proposal("well", action,
                                          f"{need} (one well for every {per} wanted), and another ordinary well "
                                          "can't be placed (the water below is in a cavern): dig a one-tile shaft "
                                          "through solid rock to the cavern lake, from a stair beside it (out to "
                                          "it along a short tunnel if no fort floor is over it), and "
                                          "build the well over it" + (" (urgent: dug first)" if urgent else "")
                                          + cavern_open_words(s, cfg),
                                          1 if urgent else 4))
                return
            notes.append(f"a cavern well would help ({need}) but not now: {safe}")
            if "cavern" in memory.extra_well_failure:
                return
        elif memory is not None and cavern_failure and memory.extra_well_failure:
            notes.append(f"{cit} dwarves share {wells} well(s); no cavern well either: "
                         f"{cavern_failure[:120]}")
            if "cavern" in memory.extra_well_failure:
                return
        if (memory is not None and memory.extra_well_failure and isinstance(last, int)
                and 0 <= abs_tick(s) - last < cfg["extra_well_retry_days"] * TICKS_PER_DAY):
            notes.append(f"{cit} dwarves share {wells} well(s); another couldn't be placed "
                         f"({memory.extra_well_failure[:100]}): tried again next season")
            return
        action = {"type": "place_well", "extra": True}
        if over_cap:
            action["urgent"] = True
        if _ice_now(s, memory, cfg):
            action["inside_only"] = True
        proposals.append(Proposal("well", action,
                                  f"{cit} dwarves share {wells} well(s) (one for every {per} wanted): "
                                  "channel a hole over clean water inside the fort and build another", 5))
        return
    patients = _d(s.get("dwarves")).get("needs_medical_care", 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    # (item5) prisoners drink only what is carried from a well: a fort with
    # none and someone in chains is as urgent as one with the injured
    # (Hammerstirred: 9 dead of thirst in the jail, the well never built)
    prisoners = jailed(s)
    # (0.104.13) the one-tile shaft could never be dug past its first levels
    # (a miner channels from beside the tile, on its level): Enxah's was given
    # up after six years with 2 of 24 tiles. The shaft is now dug from a stair
    # beside it, so that give-up no longer stands: tried once more.
    if not memory.cavern_shaft_stairs:
        memory.cavern_shaft_stairs = True
        if memory.cavern_well_failure.startswith("the last cavern well's shaft was under half dug"):
            memory.cavern_well_failure = ""
            cavern_failure = ""
    # (0.105.24) C and F (3 Nov): "the game would not place the well over the
    # hole" stopped every well for good. The cause (quickfort wants a floor
    # beside the well; a gallery's shaft top had none) is fixed and the bridge
    # takes such a well up again (a floor dug beside it): the old refusal,
    # from before the bridge said what it saw ("tiles: ..."), cleared once.
    if not memory.well_floor_retried:
        memory.well_floor_retried = True
        if "would not place the well over the hole" in memory.well_failure and "tiles:" not in memory.well_failure:
            memory.well_failure = ""
    # (0.104.13) the injured or the parched waiting: the well takes one of the
    # urgent slots (as soap, tombs and the hospital do) and is dug first
    urgent = bool(patients or parched or prisoners)
    limit = (pr.get("max_open") or 2) + (2 if urgent else 0)
    who = " and ".join(x for x in (f"{patients} injured" if patients else "",
                                    f"{parched} parched" if parched else "",
                                    f"{prisoners} jailed" if prisoners else "") if x)
    def say_failure(cavern_coming: bool) -> None:
        if not memory.well_failure:
            return
        if cavern_coming:      # (0.104.13) the AI digs to the cavern itself: nothing for the player
            notes.append(f"no ordinary well could be placed ({memory.well_failure[:120]}): a well to the "
                         "cavern instead")
            return
        # (0.105.35) nothing waits for the player: the AI tries another spot
        # (or the cavern) itself, and the water zone gives the injured water meanwhile
        days = cfg.get("well_retry_days", WELLS_CONFIG["well_retry_days"])
        text = (f"no well could be placed: {memory.well_failure}. The AI tries another spot (or the cavern) "
                f"within {days} days")
        if patients:
            notes.append(f"{patients} injured dwarves need water and " + text
                         + "; a water source zone at open water gives them water meanwhile")
        else:
            notes.append(text + " (no one is hurt, so it can wait)")
    if "place the well" in memory.well_failure:
        # the game refused a well over a hole the AI dug: not another hole at
        # once. (0.105.33 B4) But not for ever either: a well_retry_days after
        # the last try the cavern well (below) or another spot is tried (the
        # bridge keeps off the refused hole's spot).
        last = memory.last_fired.get("well")
        days = cfg.get("well_retry_days", WELLS_CONFIG["well_retry_days"])
        if isinstance(last, int) and 0 <= abs_tick(s) - last < days * TICKS_PER_DAY:
            say_failure(False)
            return
        notes.append(f"the game refused the last well over its hole ({memory.well_failure[:100]}): "
                     f"tried again after {days} days, on another spot (or to the cavern)")
    # no ordinary spot: the AI decides whether a well into a cavern is worth it
    if memory.well_failure and not cavern_failure and len(open_) < limit:
        need = cavern_well_need(s, cfg, patients) or (f"{parched} parched dwarves need water" if parched else "")
        safe = cavern_well_safe(s, cfg, urgent)
        if safe is True and shaft_danger:
            safe = f"{shaft_danger} is near the cavern well"
        if need and safe is True:
            action = cavern_action(s, cfg, urgent)           # (0.105.3)
            proposals.append(Proposal("well", action,
                                      f"{need}, and no ordinary well can be placed ({memory.well_failure[:80]}): "
                                      "dig a one-tile shaft through solid rock to the cavern lake, from a stair "
                                      "beside it (out to it along a short tunnel if no fort floor is over it), "
                                      "and build the well over it"
                                      + (" (urgent: dug first)" if urgent else "") + cavern_open_words(s, cfg),
                                      1 if urgent else 4))
            say_failure(True)
            return
        if need:
            notes.append(f"a cavern well would help ({need}) but not now: {safe}")
    elif cavern_failure:
        notes.append(f"no cavern well either: {cavern_failure}")
    say_failure(False)
    if len(open_) >= limit:
        notes.append("no well yet: waiting for a free building slot")
        return
    action = {"type": "place_well"}
    if urgent:
        action["urgent"] = True
    # (0.105.3) Hammerstirred: the pond 51 tiles from the gate, past the 40 looked at
    if cfg["well_shore_reach"] != 40:
        action["shore_reach"] = int(cfg["well_shore_reach"])
    if "far_reach" in _far_args(cfg):   # (0.105.38) a far bank: up to this (-1: the map's width; 0: none)
        action["far_reach"] = _far_args(cfg)["far_reach"]
    if _ice_now(s, memory, cfg):
        # (0.105.47) from the last half-month of autumn, or a surface near
        # freezing in any month (planner_ice.ice_season; was winter with ice
        # seen before: E's two drowned at the shore-well spot on winter's first day)
        # a well right over surface water is dismantled into its parts when
        # the water freezes (the DF wiki; region2's shore well went in winter
        # y51): in winter only inside the fort. From spring a shore well is
        # built again from the same parts; it serves three seasons of four.
        action["inside_only"] = True
    proposals.append(Proposal("well", action,
                              (f"{who} dwarves need water and there is no well" if urgent else "no well yet")
                              + ": channel a hole over clean water inside the fort and build one",
                              2 if urgent else 4))


WELL_PARTS_SHOPS = {"stone_blocks": "Masons", "wooden_bucket": "Carpenters", "mechanisms": "Mechanics",
                    "cloth_rope": "Clothiers", "weave_plant_cloth": "Loom", "weave_yarn_cloth": "Loom",
                    "weave_silk_cloth": "Loom", "yarn_rope": "Clothiers", "silk_rope": "Clothiers",
                    "process_plants": "Farmers", "shear_creature": "Farmers", "spin_thread": "Farmers"}


# (0.105.18) a well's chain: one bar of any metal but pig iron, the metals
# the military doesn't want first (A, 3 Nov: silver 12, copper 47)
CHAIN_SKIP = {"PIG_IRON"}


def chain_metal(s: dict, cfg: dict | None = None) -> str | None:
    """The metal for one chain at a forge with fuel, or None: a non-gear
    metal first, else the commonest gear metal. (fix41) Tin and bismuth are
    gear metal while the fort alloys bronze for its gear (planner_alloys
    gear_metals)."""
    g = _d(_d(s.get("military")).get("gear"))
    if not g.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < 3:
        return None
    bars = {k: int(v) for k, v in _d(g.get("all_bars") or g.get("bars")).items()
            if isinstance(v, (int, float)) and v >= 1 and k not in CHAIN_SKIP}
    if not bars:
        return None
    from planner_alloys import gear_metals
    if cfg is None:
        from planner_config import PLANNER_CONFIG as cfg
    keep = gear_metals(s, cfg)
    other = [k for k in bars if k not in keep]
    pool = other or list(bars)
    return max(pool, key=lambda k: (bars[k], k))


def well_parts_plan(s: dict, cfg: dict | None = None) -> tuple[list, list, list]:
    """What a well still needs, from the fort's real stocks: (orders to give
    [(recipe, why)], workshops to build first, parts the AI can't make).
    A well takes a block, a bucket, a mechanism and a rope or chain. (fix41
    re-review) cfg: the plan's config, passed on to chain_metal."""
    st, su = _d(s.get("stocks")), _d(s.get("supplies"))
    shops = _d(_d(s.get("buildings")).get("workshops"))
    orders, need_shops, stuck = [], [], []

    def want(recipe: str, why: str, extra: dict | None = None) -> None:
        if queued(s, {recipe}):
            return                                  # already on order
        shop = WELL_PARTS_SHOPS.get(recipe)
        if shop and not shops.get(shop):
            if shop not in need_shops:
                need_shops.append(shop)
            return
        orders.append((recipe, why, extra or {}))

    if not free_stock(s, "blocks"):
        want("stone_blocks", "a block")
    if not su.get("buckets"):
        if st.get("wood"):
            want("wooden_bucket", "a bucket")
        else:
            stuck.append("a bucket (no wood: autochop is on the way)")
    if not free_stock(s, "mechanisms"):
        want("mechanisms", "a mechanism")
    rope_queued = queued(s, {"cloth_rope", "yarn_rope", "silk_rope", "weave_plant_cloth", "weave_yarn_cloth",
                             "weave_silk_cloth"})
    if not free_stock(s, "chains") and not su.get("ropes") and not queued(s, {"metal_chain"}):
        # (0.105.18) a chain at a forge, else the rope from the cloth the
        # fort has, else cloth woven from the thread it has. A waited from 06:51
        # to 08:41 (3 Nov) on plant cloth from 0 plant thread (13 yarn), with
        # 2 forges and 47 copper bars, while its patients died of thirst
        ck, tk = _d(su.get("cloth_kinds")), _d(su.get("thread_kinds"))
        kinds = bool(ck or tk)
        metal = chain_metal(s, cfg)
        if metal:
            # first: one bar at a forge never waits on cloth (B's rope order
            # stuck 89 days on 1 plant cloth it couldn't use)
            want("metal_chain", f"a chain (in {metal.lower().replace('_', ' ')})",
                 {"material": f"INORGANIC:{metal}"})
        elif rope_queued:
            pass                                    # a rope (or its cloth) already on order
        elif (int(ck.get("plant") or 0) if kinds else int(st.get("cloth") or 0)) > 0:
            want("cloth_rope", "a rope")
        elif kinds and int(ck.get("yarn") or 0) > 0:
            want("yarn_rope", "a rope (of yarn)")
        elif kinds and int(ck.get("silk") or 0) > 0:
            want("silk_rope", "a rope (of silk)")
        elif (int(tk.get("plant") or 0) if kinds else int(st.get("thread") or 0)) > 0:
            want("weave_plant_cloth", "cloth for a rope")
        elif kinds and int(tk.get("yarn") or 0) > 0:
            want("weave_yarn_cloth", "cloth for a rope (of yarn)")
        elif kinds and int(tk.get("silk") or 0) > 0:
            want("weave_silk_cloth", "cloth for a rope (of silk)")
        # (0.105.35) nothing waits for the player: thread made by the AI itself,
        # from fibre plants in store, else from shorn wool
        elif (int(su.get("thread_plants") or 0) if "thread_plants" in su else 0) > 0:
            want("process_plants", "thread for a rope (from the fibre plants in store)")
        elif wool_route(s):
            want("shear_creature", "wool for a rope's thread")
            want("spin_thread", "thread for a rope (of the wool)")
        else:
            stuck.append("a rope or chain (no cloth, thread, fibre plants or metal bars to make one from: the "
                         "AI's trade asks the next caravan for cloth and thread, and makes the rope then)")
    return orders, need_shops, stuck


def _well_parts(s: dict, memory, cfg: dict, building: list, proposals: list, notes: list) -> None:
    """A well being made: order the parts it lacks, build the workshops that
    make them, and say what the AI can't make."""
    orders, need_shops, stuck = well_parts_plan(s, cfg)
    for recipe, why, extra in orders:
        proposals.append(Proposal("well_parts", {"type": "work_order", "recipe": recipe, "amount": 1, **extra},
                                  f"the new well needs {why}: make one", 3, True))
    pr = _d(s.get("projects"))
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    if need_shops and not _workshops_busy(open_):
        proposals.append(Proposal("well_parts", {"type": "start_project", "kind": "workshops", "shops": need_shops,
                                                  "urgent": True},
                                  f"the new well's parts are made at a {', '.join(need_shops)} workshop the fort "
                                  "lacks: dig and build it", 3))
    days = max((_d(p.get("furnish")).get("days") or 0) for p in building)
    if stuck and days >= cfg["well_parts_days"]:
        notes.append(f"the new well has waited {days} days: it needs " + "; ".join(stuck))   # (0.105.35)


CISTERN_RETRY_SEALS = 3         # (0.105.35) the game refused a wall/floor closing the cistern this often: retired
CISTERN_RELINK_ROUNDS = 2       # (0.105.35) rounds of 3 lost lever links asked afresh before the cistern is retired


# (0.105.36 X1) the cistern's "shut it now" (open, not closed all round): a
# rule of its own, outside the cooldown and the action limit. (0.105.36 fix)
# Not EMERGENCY: a refusal (no lever linked, the pull failed) backs off as
# any refusal does, instead of being asked every cycle for ever
CISTERN_SHUT_RULE = "cistern_shut"
NO_COOLDOWN.add(CISTERN_SHUT_RULE)
LIMIT_EXEMPT.add(CISTERN_SHUT_RULE)
LOOP_EXEMPT.add(CISTERN_SHUT_RULE)
STEER_PROTECTED.add(CISTERN_SHUT_RULE)
CISTERN_WORDS = {"digging": "being dug", "building": "its floodgate and lever being built",
                 "linking": "its lever being linked", "opening": "its floodgate opening",
                 "plug": "its plug being dug", "filling": "filling", "hole": "its well's hole being dug",
                 "well": "its well being built"}


def _cistern_parts(s: dict, st: dict, proposals: list, notes: list | None = None) -> None:
    """(0.92.1) The parts the cistern's floodgate and lever wait for: DF builds
    them only from a floodgate and a mechanism the fort has, and linking the
    lever takes 2 more mechanisms. region2's floodgate waited two years for a
    floodgate nobody made. Ordered when none is free or on its way to the job
    and none is queued (the bridge counts them only in these two stages)."""
    stage = st.get("stage")
    notes = notes if notes is not None else []
    if stage == "well":
        # (0.99.2) the well over the cistern takes a block, a bucket and a rope
        # or chain like any well: region2's waited a game year for a rope
        # nobody made (ropes 0, chains 0, cloth 33)
        orders, need_shops, stuck = well_parts_plan(s)
        for recipe, why, extra in orders:
            proposals.append(Proposal("cistern_parts", {"type": "work_order", "recipe": recipe, "amount": 1, **extra},
                                      f"the cistern's well needs {why}: make one", 4, is_order=True))
        # (0.105.35) nothing waits for the player: the workshop dug and built by the AI
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if need_shops and not _workshops_busy(open_):
            proposals.append(Proposal("cistern_parts", {"type": "start_project", "kind": "workshops",
                                                        "shops": need_shops, "urgent": True},
                                      f"the cistern's well's parts are made at a {', '.join(need_shops)} workshop "
                                      "the fort lacks: dig and build it", 4))
        elif need_shops:
            notes.append(f"the cistern's well needs parts made at a {', '.join(need_shops)} workshop: built "
                         "once the workshops being dug are done")
        if stuck:
            notes.append("the cistern's well waits for " + "; ".join(stuck))
        return
    fg_free, fg_res = st.get("floodgates_free"), st.get("floodgates_reserved")
    if (stage == "building" and st.get("gate") == "planned" and isinstance(fg_free, int)
            and fg_free + int(fg_res or 0) == 0 and not queued(s, {"stone_floodgate"})):
        proposals.append(Proposal("cistern_parts", {"type": "work_order", "recipe": "stone_floodgate", "amount": 1},
                                  "the cistern's floodgate waits for a floodgate the fort doesn't have: "
                                  "a mason makes one", 4, is_order=True))
    mf = st.get("mechanisms_free")
    if not isinstance(mf, int) or stage not in ("building", "linking"):
        return
    need = 3 if stage == "building" and st.get("lever") == "planned" else 2   # the lever, then its link
    held = _d(st.get("mechanisms_held"))
    held_words = ", ".join(f"{n} {why}" for why, n in sorted(held.items())) if held else ""
    if mf < need and not queued(s, {"mechanisms"}):
        n = need - mf
        proposals.append(Proposal("cistern_parts", {"type": "work_order", "recipe": "mechanisms", "amount": n},
                                  f"the cistern's lever needs mechanisms ({mf} free"
                                  + (f"; {held_words}" if held_words else "") + f"): a mechanic makes {n}",
                                  4, is_order=True))


def _cistern_rule(s: dict, memory, cfg: dict, proposals: list, notes: list, rules_: dict) -> None:
    """Water step W2: the cistern (lua/ai-builder.lua cistern_step), built a
    step at a time once the AI decides the fort needs one, then kept filled
    (the floodgate opened under 3/7, shut at 6/7)."""
    w = _d(s.get("water"))
    st = w.get("cistern_status")
    # (0.104.145) what the brain knows that weighs the source the bridge picks:
    # the climate freezes (a surface pond is dry half the year), a danger in
    # the caverns (no tunnel to a cavern lake then)
    dangers = [x for x in _l(_d(s.get("deep")).get("dangers")) if isinstance(x, dict) and not x.get("caged")]
    prefs = {"freezes": bool(memory is not None and memory.climate_freezes),
             "cavern_danger": any("cavern" in str(x.get("layer") or "").lower() for x in dangers)}
    step = {"type": "cistern_step", "prefs": prefs}
    if cfg["cistern_tunnel_max"] != 30:              # (0.105.3) the reach the survey planned it with
        step["tunnel"] = int(cfg["cistern_tunnel_max"])
    if "far_reach" in _far_args(cfg):  # (0.105.38) a far pool's tunnel: up to this (-1: the map's width; 0: none)
        step["far_reach"] = _far_args(cfg)["far_reach"]
    if cfg["cistern_hold"]:
        # (0.104.144) the player: as built, the cistern doesn't work and would
        # flood the fort if it did. No step (the bridge holds it too) until it
        # is designed again
        if isinstance(st, dict):
            notes.append(f"the cistern is on hold for a new design (stage {st.get('stage')}, floodgate "
                         f"{st.get('gate') or '?'}): the AI leaves its floodgate shut")
            if st.get("gate") == "open":
                # the bridge's held step shuts it (31 Oct 20:54: opened and the
                # plug dug minutes before the hold)
                proposals.append(Proposal("cistern", dict(step),
                                          "the cistern is on hold and its floodgate is open: shut it", 1))
        return
    if isinstance(st, dict):
        # (0.104.145) open and no longer closed all round (a dig beside the
        # shaft or tunnel): shut at once
        # (0.105.36 X1) its own rule, CISTERN_SHUT_RULE: never waits out the
        # cistern rule's cooldown after a routine step (priority 0: before
        # any other cistern step this cycle)
        if st.get("gate") == "open" and st.get("sealed_now") is False:
            proposals.append(Proposal(CISTERN_SHUT_RULE, {"type": "cistern_step", "shut": True},
                                      f"the cistern's floodgate is open and it isn't closed where the water goes "
                                      f"({st.get('unsealed')}): shut it now", 0))
        # (0.104.145) the leak guard shut it, or it isn't closed where the water goes
        # (0.105.35) nothing waits for the player: a cistern that leaked twice
        # (the bridge lets water in again once after the first, when dry and
        # closed all round) is retired by the AI, its floodgate shut, and the
        # next one planned elsewhere
        if st.get("leak"):
            gap_refused = (st.get("unsealed_why")
                           and int(st.get("unsealed_refusals") or 0) >= CISTERN_RETRY_SEALS)
            if int(st.get("leaks") or 1) >= 2:
                proposals.append(Proposal("cistern", {"type": "cistern_step", "retire": True,
                                                      "why": f"leaked twice (at {st['leak']})"},
                                          f"water got out of the cistern again (over it at {st['leak']}): retire it, "
                                          "its floodgate shut for good; another cistern is planned elsewhere", 2))
            elif gap_refused:
                # (0.105.36 D3) it leaked through a gap the game won't let the
                # AI close: retired (the bridge walls a gap up after a leak)
                proposals.append(Proposal("cistern", {"type": "cistern_step", "retire": True,
                                                      "why": f"leaked, could not be closed ({st['unsealed_why']})"[:120]},
                                          f"water got out of the cistern (over it at {st['leak']}) and the game won't "
                                          f"let the AI close it where it leaks ({st['unsealed_why']}; "
                                          f"{st.get('unsealed_refusals')} tries): retire it, its floodgate shut; "
                                          "another is planned elsewhere", 3))
            else:
                # (v35 fix) the step the bridge clears the leak in (the water
                # gone and closed all round) and carries on from: asked for,
                # every 2 days while the water still stands over it
                notes.append(f"water got out of the cistern (over it at {st['leak']}): its floodgate was shut. The AI "
                             "lets water in again once the water over it is gone and it is closed all round"
                             + (f" (it walls up the gap at {st['unsealed']} itself)" if st.get("unsealed") else "")
                             + "; a second leak retires it")
                proposals.append(Proposal("cistern", dict(step),
                                          f"the cistern leaked once (over it at {st['leak']}): its next step, once the "
                                          "water over it is gone and it is closed all round", 4))
            return
        if st.get("unsealed"):
            # (0.104.168) the AI walls the gaps up itself (cistern_step); the
            # player is asked only for a gap it can't close (water, a stair,
            # a wall that would cut a way), with the bridge's why
            # (0.105.35) a gap the game won't let it close: tried again, then
            # the cistern retired (no water ever let in) and another planned
            if st.get("unsealed_why") and int(st.get("unsealed_refusals") or 0) >= CISTERN_RETRY_SEALS:
                proposals.append(Proposal("cistern", {"type": "cistern_step", "retire": True,
                                                      "why": f"could not be closed ({st['unsealed_why']})"[:120]},
                                          f"the cistern isn't closed where its water would go and the game won't let "
                                          f"the AI close it ({st['unsealed_why']}; {st.get('unsealed_refusals')} "
                                          "tries): retire it before any water comes in; another is planned elsewhere", 3))
                return
            if st.get("unsealed_why"):
                notes.append(f"the cistern isn't closed where its water would go ({st['unsealed_why']}): the AI tries "
                             f"again ({int(st.get('unsealed_refusals') or 1)} of {CISTERN_RETRY_SEALS}), then retires it "
                             "and plans another; no water comes in until then")
            else:
                notes.append(f"the cistern isn't closed where its water would go ({st['unsealed']}): the AI builds "
                             "a wall or floor there itself"
                             + (f" ({st['sealing']} placed, being built)" if st.get("sealing") else "")
                             + " and lets no water in until it is")
        if int(st.get("v") or 1) < 2:
            proposals.append(Proposal("cistern", dict(step),
                                      "the cistern is of the first design (its water could reach the fort under "
                                      "pressure): shut its floodgate and retire it; a new one is planned", 2))
            return
        # (0.104.141) the bridge gave up relinking (3 links lost): not a refused
        # step every few minutes. (0.105.35) nothing waits for the player: the
        # AI asks for the link afresh (another 3 tries), CISTERN_RELINK_ROUNDS
        # times, then retires the cistern (no water was ever let in) and plans another
        if (st.get("stage") == "linking" and int(st.get("relinks") or 0) >= 3 and not st.get("linked")
                and not st.get("link_pending")):
            why = f": {st.get('link_why')}" if st.get("link_why") else ""
            rounds = int(st.get("relink_rounds") or 0)
            if rounds < CISTERN_RELINK_ROUNDS:
                proposals.append(Proposal("cistern", {"type": "cistern_step", "relink": True},
                                          f"the cistern's lever link to its floodgate was lost 3 times{why}: ask for "
                                          f"it afresh (round {rounds + 1} of {CISTERN_RELINK_ROUNDS})", 4))
            else:
                proposals.append(Proposal("cistern", {"type": "cistern_step", "retire": True,
                                                      "why": "its lever would not stay linked"},
                                          f"the cistern's lever won't stay linked to its floodgate{why} "
                                          f"({CISTERN_RELINK_ROUNDS} rounds of 3 links lost): retire it before any "
                                          "water comes in; another is planned elsewhere", 4))
            return
        if st.get("stage") != "done":
            notes.append(f"the cistern: {CISTERN_WORDS.get(st.get('stage'), st.get('stage'))}"
                         + (f", {st.get('depth')}/7 deep" if st.get("depth") else "")
                         + (f"; its water from the {st.get('source')}"
                            + (f" {st['intake_elevation'] - st['elevation']} level(s) up, down a shaft through a diagonal step"
                               if st.get("shaft") and isinstance(st.get("intake_elevation"), int)
                               and isinstance(st.get("elevation"), int) else "")
                            if st.get("source") else ""))
            proposals.append(Proposal("cistern", dict(step),
                                      f"the cistern: {CISTERN_WORDS.get(st.get('stage'), 'next step')}: the next step", 4))
            _cistern_parts(s, st, proposals, notes)
        elif (st.get("gate") == "shut" and (st.get("depth") or 0) < 3) or (st.get("gate") == "open" and (st.get("depth") or 0) >= 6):
            proposals.append(Proposal("cistern", dict(step),
                                      f"the cistern is {st.get('depth')}/7 deep: "
                                      + ("open the floodgate to refill it" if st.get("gate") == "shut" else "shut the floodgate"), 4))
        return
    plan = _d(w.get("cistern"))
    if not plan or plan.get("none") or not rules_.get("water_works", True):
        return
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    cpop = cistern_pop(_traits(s) if isinstance(s.get("settings"), dict) else {}, cfg)   # (0.96) Engineering
    if young_fort(s, cfg) or cpop is None or citizens < cpop or len(open_) >= (_d(s.get("projects")).get("max_open") or 2):
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return
    wells = _d(_d(s.get("buildings")).get("other")).get("Well", 0)
    bodies = [b for b in _l(w.get("bodies")) if isinstance(b, dict)]
    near = [b for b in bodies if b.get("kind") in ("surface", "pool", "river")]
    all_stagnant = bool(near) and all((b.get("stagnant_share") or 0) >= 90 for b in near)
    why = ("the fort has no well" if not wells
           else "surface water freezes in winter" if memory is not None and memory.climate_freezes
           else "the water near the fort is stagnant" if all_stagnant and not plan.get("stagnant") else "")
    if not why:
        return
    # (0.104.145) the source the bridge chose, and what it weighed
    seen = _d(plan.get("considered"))
    others = ", ".join(f"{k} {v}" for k, v in sorted(seen.items(), key=lambda kv: kv[1]) if k != plan.get("source"))
    via = (f" {plan['intake_elevation'] - plan['elevation']} level(s) up, down a shaft through a diagonal step"
           if plan.get("shaft") and isinstance(plan.get("intake_elevation"), int) and isinstance(plan.get("elevation"), int)
           else "")
    proposals.append(Proposal("cistern", dict(step),
                              f"{why}: dig a 5x5 cistern at elevation {plan.get('elevation')}, filled from the "
                              f"{plan.get('source')}{via} through a {plan.get('tunnel')}-tile tunnel and a floodgate, "
                              "a well over it"
                              + (f" (chosen over: {others}; lower is better)" if others else "")
                              + (f" ({plan['source_why']})" if plan.get("source_why") else ""), 5))


# --- (r1 g3) water in winter -------------------------------------------------
#
# B (R-B finding 1): the only well stood over a surface brook. It was dug
# every spring and frozen (or given up before the ice) every winter; in
# winter the well rule looked only for an open drop inside the fort, found
# none 78 times, and never dug a shaft. Every patient of every winter died of
# thirst (a patient gets only water). D's only wells were shore wells too
# (A1 5a). So a fort whose water freezes is given, before its first winter
# is out, a water source that works in winter: a cavern well (its shaft
# through solid rock, with its hatch, lever and watcher: the existing cavern
# well path and its safety; an unfound cavern only as the Rules switch
# allows), else the survey's cistern, filled while the water is liquid.

WINTER_WATER_RULE = "winter_water"
STEER_PROTECTED.add(WINTER_WATER_RULE)      # survival: the strategist never holds it
AGENDA_THEMES.setdefault(WINTER_WATER_RULE, "water that works in winter")


def winter_wells(s: dict) -> tuple[int, int] | None:
    """(winter, surface): the built wells whose water stays liquid in winter
    (water under them that isn't under the sky: a cavern or underground
    water; a cavern well shut for a while for a danger is still one), and
    the wells over surface water (under the sky) or drawing only ice now.
    None without the frost reading (an older bridge): nothing is said."""
    from planner_ice import _frost
    f = _frost(s)
    if not f or not isinstance(f.get("wells"), list):
        return None
    winter = surface = 0
    for w in _frost_wells(s):
        if w.get("water") == "water" and w.get("outside") is not True:
            winter += 1
        elif w.get("water") == "ice" or w.get("outside") is True:
            surface += 1
    return winter, surface


def _cistern_works(s: dict) -> bool:
    st = _d(s.get("water")).get("cistern_status")
    return isinstance(st, dict) and st.get("stage") == "done" and not st.get("retired") and not st.get("leak")


def _cistern_coming(s: dict) -> bool:
    st = _d(s.get("water")).get("cistern_status")
    return isinstance(st, dict) and st.get("stage") not in ("done", None) and not st.get("retired")


def climate_freezes_now(s: dict, memory, cfg: dict) -> str:
    """Why the fort's surface water freezes in winter ("" when nothing says
    so): ice seen here before, the ice season now (planner_ice), a well or
    water zone frozen, or an autumn surface within g3_winter_temp_margin of
    freezing (the first year's warning, before any ice is seen)."""
    from planner_ice import FREEZE, _frost, ice_season
    if memory is not None and getattr(memory, "climate_freezes", False):
        return "ice was seen here before"
    on, why = ice_season(s, memory, cfg)
    if on:
        return why
    f = _frost(s)
    if any(isinstance(x, dict) and x.get("water") == "ice" for x in _l(f.get("wells")) + _l(f.get("zones"))):
        return "a well or water zone is frozen"
    temp = f.get("surface_temp")
    if (_d(s.get("date")).get("season") == "autumn" and isinstance(temp, (int, float)) and not isinstance(temp, bool)
            and temp <= FREEZE + int(cfg.get("g3_winter_temp_margin", 40))):
        return f"the autumn surface is {int(temp - FREEZE)} degree(s) over freezing"
    return ""


def winter_water_need(s: dict, memory, cfg: dict) -> str:
    """Why the fort needs a water source that works in winter ("" when it
    has one, or its water doesn't freeze, or the bridge has no frost reading)."""
    ww = winter_wells(s)
    if ww is None:
        return ""
    winter, surface = ww
    if winter > 0 or _cistern_works(s):
        return ""
    from planner_ice import _frost
    if any(isinstance(z, dict) and z.get("outside") is not True and z.get("water") == "water"
           for z in _l(_frost(s).get("zones"))):
        return ""                 # a water zone at underground water: patients get water from it
    freezes = climate_freezes_now(s, memory, cfg)
    if not freezes:
        return ""
    what = (f"the fort's {surface} well(s) stand over surface water, which freezes" if surface
            else "the fort has no well")
    return f"{what} ({freezes}) and no water source works in winter"


WINTER_CISTERN_WORDS = ("dig a {side}x{side} chamber in solid rock one level under a floor inside the fort (under a "
                        "roof, where water doesn't freeze; closed all round), build a well over it and a pond zone "
                        "on the well: the dwarves fill it by bucket from the {source} while it is liquid (to 6/7 "
                        "at most; the well draws from 3/7), and it gives the injured water through the winter")


def filling_cisterns(s: dict) -> list:
    """(r2 h2) The winter cisterns (a well with a pond zone on it, over no
    sky) that don't give water yet: dry, or under 3/7 deep."""
    return [w for w in _frost_wells(s) if w.get("pond") and w.get("outside") is not True and w.get("water") != "water"]


def winter_cistern_action(cfg: dict, urgent: bool) -> dict:
    """(r2 h2) The winter cistern's place_well (lua/ai-builder-wells.lua find_filled_well_spot)."""
    act = {"type": "place_well", "filled": True}
    half = int(cfg.get("h2_winter_cistern_half", 1) or 1)
    if half != 1:
        act["half"] = half
    if urgent:
        act["urgent"] = True
    return act


def _winter_cistern_wait(s: dict, memory, cfg: dict) -> str:
    """(r2 h2) Why no winter cistern is asked for now ("" when it may be)."""
    if not cfg.get("h2_winter_cistern", True):
        return "the winter cistern is off (h2_winter_cistern)"
    failure = str(getattr(memory, "filled_well_failure", "") or "") if memory is not None else ""
    at = getattr(memory, "filled_well_failure_at", None) if memory is not None else None
    days = int(cfg.get("h2_winter_cistern_retry_days", 28) or 28)
    if failure and isinstance(at, int) and 0 <= abs_tick(s) - at < days * TICKS_PER_DAY:
        return f"the last winter cistern couldn't be placed ({failure[:100]}): tried again within {days} days"
    return ""


def _fill_source(s: dict) -> str:
    """(r2 h2) The water the dwarves fill the winter cistern from, in words."""
    bodies = [b for b in _l(_d(s.get("water")).get("bodies")) if isinstance(b, dict) and b.get("kind") != "cavern"
              and (b.get("salt_share") or 0) < 50]
    if bodies:
        b = min(bodies, key=lambda b: _d(b.get("nearest")).get("d") or 999)
        return WATER_WORDS.get(b.get("kind"), str(b.get("kind")))
    return "nearest water"


def _cistern_buckets(s: dict, proposals: list) -> None:
    """(r2 h2) A winter cistern is filled with empty buckets: two at least."""
    su, st = _d(s.get("supplies")), _d(s.get("stocks"))
    have = su.get("buckets")
    if not isinstance(have, int) or isinstance(have, bool) or have >= 2 or queued(s, {"wooden_bucket"}):
        return
    if not st.get("wood"):
        return
    proposals.append(Proposal("well_parts", {"type": "work_order", "recipe": "wooden_bucket", "amount": 2 - have},
                              f"the winter cistern is filled by bucket and the fort has {have} empty bucket(s): "
                              "make more", 3, True))


def _winter_water_rule(s: dict, memory, cfg: dict, proposals: list, notes: list, rules_: dict | None = None) -> None:
    """(r1 g3) A water source that works in winter, before the first winter
    ends (see winter_wells): a cavern well first, else the survey's cistern.
    (r2 h2) Else (and before a shaft that would open a cavern nobody has
    found) the winter cistern: a small chamber in solid rock under a floor
    inside the fort, a well over it, filled by bucket while the surface water
    is liquid (B: no drop inside the fort, Cavern1 unfound and no soldiers,
    no site for the survey's cistern; every winter patient died of thirst)."""
    need = winter_water_need(s, memory, cfg)
    if not need:
        return
    from planner_ice import _frost
    if (memory is not None and not getattr(memory, "climate_freezes", False)
            and any(isinstance(x, dict) and x.get("water") == "ice"
                    for x in _l(_frost(s).get("wells")) + _l(_frost(s).get("zones")))):
        memory.climate_freezes = True     # ice seen: the climate freezes (the cistern's prefs read it)
    pr = _d(s.get("projects"))
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    coming = [p for p in open_ if p.get("kind") == "well" and not _d(p.get("summary")).get("shore")]
    if coming:
        what = "the winter cistern" if _d(coming[0].get("summary")).get("filled") else "a well off the surface water"
        notes.append(f"{need}: {what} is being made (project {coming[0].get('id')})")
        return
    if _cistern_coming(s):
        notes.append(f"{need}: the cistern is being made")
        return
    from planner_ice import ice_season
    ice_on = ice_season(s, memory, cfg)[0]
    season = ice_on or _d(s.get("date")).get("season") == "winter"
    filling = filling_cisterns(s)
    if filling:
        c = filling[0]
        _cistern_buckets(s, proposals)
        depth = c.get("depth")
        notes.append(f"{need}: the winter cistern under the well at x{c.get('x')} y{c.get('y')} is being filled by "
                     f"bucket ({depth if isinstance(depth, int) else 0}/7; the well draws from {WELL_MIN_DEPTH}/7)"
                     + ("; the water it is filled from is frozen now" if season else ""))
        if not season:
            return
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    pressing = bool(patients or parched or jailed(s) or season)
    max_open = pr.get("max_open") or 2
    extra = int(cfg.get("g3_winter_well_slots", 2) if pressing else cfg.get("g3_extra_well_slots", 1))
    if len(open_) >= max_open + extra and not need_slots_free(s):      # (R2 h3) the needs' pool
        notes.append(f"{need}: a winter water source waits for a free building slot")
        return
    over_cap = len(open_) >= max_open
    pri = 2 if pressing else 3
    rules_ = rules_ or {}
    threat = bool(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"))
    # (r2 h2) the winter cistern may be asked for: switched on, water works
    # allowed, none filling already, no recent refusal, no threat abroad
    cistern_wait = ("one is being filled" if filling else _winter_cistern_wait(s, memory, cfg)
                    or ("" if rules_.get("water_works", True) else "water works are off in the Rules tab")
                    or ("enemies can reach the dwarves" if threat else ""))
    cavern_failure = cavern_failure_now(s, memory, cfg)
    # the cavern well: its own safety (one at a time, no danger near, the
    # Rules switch for an unfound cavern; the "ai" setting counts the winter
    # need as a shortage, soldiers still wanted); a small or young fort too
    safe = cavern_well_safe(s, cfg, urgent=True, winter=need) if not cavern_failure else None
    layer = unfound_cavern(s)
    if safe is True and layer and not cistern_wait:
        # (r2 h2) the first breach of a cavern brings its creatures and the
        # forgotten beasts: not while a cistern that opens nothing can be dug
        safe = (f"it would open {layer} for the first time, and a winter cistern that opens nothing is "
                "tried first")
    if safe is True:
        action = cavern_action(s, cfg, pressing or over_cap, winter=need)
        proposals[:] = [p for p in proposals if not (p.rule in ("well", "frost_well")
                                                     and _d(p.action).get("type") == "place_well"
                                                     and not _d(p.action).get("cavern"))]
        proposals.append(Proposal("winter_water", action,
                                  f"{need}: dig a one-tile shaft through solid rock to the cavern lake, from a stair "
                                  "beside it (out to it along a short tunnel if no fort floor is over it), and build "
                                  "the well over it, its hatch and lever shut while a danger is near"
                                  + (" (urgent: dug first)" if action.get("urgent") else "")
                                  + cavern_open_words(s, cfg, need), pri))
        return
    why_not = f"no cavern well: {cavern_failure[:120]}" if cavern_failure else f"no cavern well now: {safe}"
    # the cistern, filled while the water is liquid (the survey's plan); the
    # cistern rule's own gates (fort size, age) don't hold this one back
    w = _d(s.get("water"))
    plan = _d(w.get("cistern"))
    if (plan and not plan.get("none") and rules_.get("water_works", True) and not cfg.get("cistern_hold")
            and not isinstance(w.get("cistern_status"), dict) and not threat):
        dangers = [x for x in _l(_d(s.get("deep")).get("dangers")) if isinstance(x, dict) and not x.get("caged")]
        step = {"type": "cistern_step", "prefs": {"freezes": True, "cavern_danger": any(
            "cavern" in str(x.get("layer") or "").lower() for x in dangers)}}
        if cfg["cistern_tunnel_max"] != 30:
            step["tunnel"] = int(cfg["cistern_tunnel_max"])
        if "far_reach" in _far_args(cfg):
            step["far_reach"] = _far_args(cfg)["far_reach"]
        proposals[:] = [p for p in proposals if not (p.rule == "cistern" and _d(p.action).get("type") == "cistern_step"
                                                     and not any(k in p.action for k in ("shut", "retire", "relink")))]
        proposals.append(Proposal("winter_water", step,
                                  f"{need}, and {why_not}: dig a 5x5 cistern at elevation {plan.get('elevation')}, "
                                  f"filled from the {plan.get('source')} while it is liquid, through a "
                                  f"{plan.get('tunnel')}-tile tunnel and a floodgate, a well over it", pri))
        return
    cw = (f"no cistern site: {plan.get('why')}" if plan.get("none") else
          "no cistern plan yet (the water survey)" if not plan else "the cistern waits (water works off, a threat near, or one already planned)")
    if not cistern_wait:
        # (r2 h2) the winter cistern: dug now, filled while the water is liquid.
        # Beside it, not instead: the ordinary (shore) well of this cycle stays
        # (it is the water the cistern is filled from)
        action = winter_cistern_action(cfg, pressing or over_cap)
        side = 2 * int(action.get("half", 1)) + 1
        proposals.append(Proposal("winter_water", action,
                                  f"{need}, {why_not} and {cw}: "
                                  + WINTER_CISTERN_WORDS.format(side=side, source=_fill_source(s))
                                  + (" (urgent: dug first)" if action.get("urgent") else ""), pri))
        return
    notes.append(f"{need}; {why_not}; {cw}; no winter cistern now: {cistern_wait}. "
                 "The injured get water from a water zone at underground water, if any")
