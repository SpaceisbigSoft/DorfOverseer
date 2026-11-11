"""planner_wells: wells, cisterns and the water near the fort (split out of
planner_building in 0.105.25, 13c): the well and its lid, cavern wells and
their danger, the well's and the cistern's parts, water zones and traffic,
the water summary. planner_building re-exports every name here."""

from __future__ import annotations

import math
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_well_rule", "_well_lid_rule", "SHAFT_LINK_LOST_MAX", "SHAFT_DANGER_TILES", "SHAFT_DANGER_OPEN", "cavern_danger", "_water_zone_rule", "cavern_points", "cavern_action", "cavern_well_need", "unfound_cavern", "cavern_well_safe", "WELL_PARTS_SHOPS", "CHAIN_SKIP", "chain_metal", "well_parts_plan", "_well_parts", "_water_traffic_rule", "cistern_pop", "WATER_WORDS", "magma_access", "water_summary", "_water_rules", "CISTERN_WORDS", "_cistern_parts", "_cistern_rule", "WELLS_CONFIG", "shut_wells", "usable_wells", "ai_opens_cavern", "cavern_open_words", "CISTERN_RETRY_SEALS", "CISTERN_RELINK_ROUNDS"]

# (0.105.33 B4) the wells' own settings (merged into PLANNER_CONFIG, as planner_threats does)
WELLS_CONFIG = {
    "well_retry_days": 28,      # a well the game refused (given up): another spot tried this long after
    # (0.105.35) a cavern well into a cavern no dwarf has found, the Rules switch off:
    # the AI opens it itself when the fort is short of water and has this many
    # soldiers for what comes out (+2 at Caution 50+, -1 at Militarism 50+)
    "unfound_cavern_soldiers": 3,
}
PLANNER_CONFIG.update({k: v for k, v in WELLS_CONFIG.items() if k not in PLANNER_CONFIG})


def shut_wells(s: dict, states: tuple = ("closed", "pulling")) -> int:
    """(0.105.33 B4) Built cavern wells whose shaft gate is shut (or being
    pulled): the bucket can't reach the water through a shut hatch. Wells
    still being dug or furnished (in the open list) and given-up shafts are
    not built wells and are not counted."""
    pr = _d(s.get("projects"))
    open_ids = {p.get("id") for p in _l(pr.get("open")) if isinstance(p, dict)}
    return sum(1 for x in _l(pr.get("well_lids")) if isinstance(x, dict)
               and x.get("gate") in states and not x.get("cancelled")
               and (x.get("project_id") is None or x.get("project_id") not in open_ids))


def usable_wells(s: dict, states: tuple = ("closed", "pulling")) -> int:
    """(0.105.33 B4) The wells a bucket can draw from: the built ones less the
    cavern wells whose shaft gate is shut."""
    wells = int(_d(_d(s.get("buildings")).get("other")).get("Well", 0) or 0)
    return max(0, wells - shut_wells(s, states))


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
    if lids:
        shaft_danger = cavern_danger(s, lids, SHAFT_DANGER_OPEN)
        if not shaft_danger:
            near = next((_d(x.get("watch_near")) for x in lids if _d(x.get("watch_near"))), None)
            if near:
                shaft_danger = str(near.get("name") or "a wild beast")
    if shaft_danger:
        wells = int(_d(_d(s.get("buildings")).get("other")).get("Well", 0) or 0)
        if shut_wells(s, ("closed",)):
            notes.append(f"the cavern well's shaft is shut while {shaft_danger} is near: still counted as a well")
    else:
        wells = usable_wells(s, ("closed",))
    open_ = [p for p in _l(pr.get("open")) if isinstance(p, dict)]
    building = [p for p in open_ if p.get("kind") == "well"]
    if building:
        _well_parts(s, memory, cfg, building, proposals, notes)
    if building:
        return
    # (0.105.3) Hammerstirred (2 Nov): the cavern well was refused once for
    # "no floor over cavern water" and never tried again, while the lake lay
    # beside the fort. Now it may dig a gallery out to it: tried once more.
    # (0.105.4 review) once, by a flag (record sets it when a cavern well with a
    # gallery comes back): the refusal's text is cut to 300 characters, so
    # "gallery" in it was no sure sign. plan() itself only reads it.
    cavern_failure = memory.cavern_well_failure if memory is not None else ""
    if (memory is not None and cfg["cavern_well_gallery"] > 0 and not memory.cavern_gallery_retried
            and cavern_failure.startswith("no floor inside the fort over cavern water")):
        cavern_failure = ""
    if wells:
        # (0.104.141, 12k) wells by the dwarves per well: Teacheroar's 209
        # dwarves (124 patients at the worst) shared one well
        cit = int(_d(s.get("dwarves")).get("total") or 0)
        per = cfg["dwarves_per_well"]
        if not per or wells >= math.ceil(cit / per) or len(open_) >= (pr.get("max_open") or 2):
            return
        last = memory.last_fired.get("extra_well") if memory is not None else None
        # (0.104.148) no ordinary spot because the only water below is a
        # cavern (Teacheroar, 1 Nov: 163 dwarves on one well, 4 dead of
        # thirst overnight, "another couldn't be placed ... in a cavern" every
        # season): the cavern well, as for a fort with none, when it's needed
        # and safe and none has failed before
        if (memory is not None and "cavern" in memory.extra_well_failure
                and not cavern_failure):
            patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
            need = cavern_well_need(s, cfg, patients) or f"{cit} dwarves share {wells} well(s)"
            safe = cavern_well_safe(s, cfg)
            if safe is True and shaft_danger:
                safe = f"{shaft_danger} is near the cavern well"
            if safe is True:
                urgent = bool(patients or int(_d(s.get("society")).get("parched") or 0))
                action = cavern_action(s, cfg, urgent)       # (0.105.3)
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
            return
        if memory is not None and cavern_failure and "cavern" in memory.extra_well_failure:
            notes.append(f"{cit} dwarves share {wells} well(s); no cavern well either: "
                         f"{cavern_failure[:120]}")
            return
        if (memory is not None and memory.extra_well_failure and isinstance(last, int)
                and 0 <= abs_tick(s) - last < cfg["extra_well_retry_days"] * TICKS_PER_DAY):
            notes.append(f"{cit} dwarves share {wells} well(s); another couldn't be placed "
                         f"({memory.extra_well_failure[:100]}): tried again next season")
            return
        action = {"type": "place_well", "extra": True}
        if memory is not None and memory.climate_freezes and _d(s.get("date")).get("season") == "winter":
            action["inside_only"] = True
        proposals.append(Proposal("well", action,
                                  f"{cit} dwarves share {wells} well(s) (one for every {per} wanted): "
                                  "channel a hole over clean water inside the fort and build another", 5))
        return
    patients = _d(s.get("dwarves")).get("needs_medical_care", 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
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
    urgent = bool(patients or parched)
    limit = (pr.get("max_open") or 2) + (2 if urgent else 0)
    who = " and ".join(x for x in (f"{patients} injured" if patients else "",
                                    f"{parched} parched" if parched else "") if x)
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
        safe = cavern_well_safe(s, cfg)
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
    if memory.climate_freezes and _d(s.get("date")).get("season") == "winter":
        # a well right over surface water is dismantled into its parts when
        # the water freezes (the DF wiki; region2's shore well went in winter
        # y51): in winter only inside the fort. From spring a shore well is
        # built again from the same parts; it serves three seasons of four.
        action["inside_only"] = True
    proposals.append(Proposal("well", action,
                              (f"{who} dwarves need water and there is no well" if urgent else "no well yet")
                              + ": channel a hole over clean water inside the fort and build one",
                              2 if urgent else 4))


def _well_lid_rule(s: dict, proposals: list, notes: list) -> None:
    """(0.104.151-152) A cavern well's ways in from the cavern. The shaft gate:
    a hatch on the shaft's lowest tile (the one opening into the cavern) on a
    lever near the well, opened so the bucket passes, shut while a danger is
    near; the lever first, the hatch once 2 mechanisms are free for the link.
    Only where the game won't build that hatch, the stair column's top step
    gets a locked hatch instead. Mechanisms and hatch covers ordered."""
    lids = [x for x in _l(_d(s.get("projects")).get("well_lids")) if isinstance(x, dict)]
    if not lids:
        return
    where = lambda x: f"x{x.get('x')} y{x.get('y')} elevation {x.get('elevation')}"
    # the stair lid, where the gate can't be built
    todo = [x for x in lids if x.get("gate") == "none_possible" and x.get("state") in ("none", "open")
            and not x.get("gate_hatch_standing")]
    if todo:
        proposals.append(Proposal("well_lid", {"type": "seal_well_stairs"},
                                  f"the game won't build a hatch at the bottom of {len(todo)} cavern well shaft(s): "
                                  "a locked hatch over the stair column's top step instead (at "
                                  + ", ".join(where(x) for x in todo[:3]) + ")", 3))
    covers = sum(1 for x in lids if x.get("gate") == "none_possible" and x.get("state") in ("none", "planned"))
    covers += sum(1 for x in lids if x.get("gate") == "no_hatch"
                  or (x.get("gate") == "building" and x.get("gate_hatch_built") is False))
    # (0.105.4 review) a held shaft waits for its hatch cover before it breaks into the cavern:
    # ordered while its lever is still being built, too
    covers += sum(1 for x in lids if x.get("held") and x.get("gate") in ("none", "stray", "no_lever", "building")
                  and not (x.get("hatch_covers") or 0))
    for x in lids:
        if x.get("held"):
            notes.append(f"the cavern well at {where(x)}: its last level waits undug until the gate's lever stands "
                         f"and a hatch cover ({x.get('hatch_covers', 0)} free) and 2 mechanisms are in store")
    free = _d(_d(s.get("entrances")).get("parts")).get("hatch_covers")
    if covers and isinstance(free, int) and free == 0 and queued(s, {"stone_hatch_cover"}) == 0:
        proposals.append(Proposal("well_lid", {"type": "work_order", "recipe": "stone_hatch_cover", "amount": covers},
                                  f"the cavern wells' gates need {covers} hatch cover(s) and none is free: make them",
                                  3, True))
    blocked = [x for x in lids if x.get("state") == "blocked" and x.get("gate") == "none_possible"]
    if blocked:
        notes.append("a cavern well's stair column has something else built on its top step ("
                     + ", ".join(where(x) for x in blocked[:2]) + "): left alone")
    # the shaft gate
    gates = [x for x in lids if x.get("gate")]
    shut = [x for x in gates if x.get("gate") == "closed"]
    danger = cavern_danger(s, gates, SHAFT_DANGER_OPEN if shut else SHAFT_DANGER_TILES)
    if not danger:
        # (0.104.165) the in-game watcher's own test: it would shut the gate for this
        # one now, so it isn't opened (Teacheroar: opened, shut again for unit 6300)
        near = next((_d(x.get("watch_near")) for x in gates if _d(x.get("watch_near"))), None)
        if near:
            danger = str(near.get("name") or "a wild beast")
    # (review) never while a danger is near: no dwarf is sent down beside the opening
    # (0.104.156) one pool of mechanisms for every gate: a link takes 2 of them,
    # and only ones the lever can reach (Teacheroar, 1 Nov: well 218's link took
    # 2 of the 3 each cycle and DF cancelled it, "Item inaccessible", while well
    # 224 waited for the 2 its hatch needs, 25 times in 2 hours)
    pool = max([x.get("gate_mechanisms") or 0 for x in gates] or [0])
    ok_gates = []
    for x in sorted(gates, key=lambda x: 0 if x.get("gate") == "unlinked" else 1):
        g = x.get("gate")
        if g in ("none", "stray", "no_lever"):
            ok_gates.append(x)
        elif g == "unlinked":
            if (x.get("gate_link_lost") or 0) >= SHAFT_LINK_LOST_MAX:
                notes.append(f"the cavern well's shaft gate at {where(x)}: DF cancelled its lever link "
                             f"{x['gate_link_lost']} times (the mechanisms out of reach?): it waits for others")
                pool -= 2
                continue
            reach = x.get("gate_mechanisms_reachable")
            if pool >= 2 and (reach is None or reach >= 2):
                ok_gates.append(x)
            elif reach is not None and reach < 2 and pool >= 2:
                notes.append(f"the cavern well's shaft gate at {where(x)}: {x.get('gate_mechanisms_far') or pool - reach}"
                             " free mechanism(s) lie out of reach of its lever"
                             + (f" ({x['gate_mechanisms_far_at']})" if x.get("gate_mechanisms_far_at") else "")
                             + ": the link waits")
            pool -= 2
        elif g == "no_hatch":
            if x.get("breaking"):
                continue                     # (0.105.4 review) the last level being dug: the hatch after
            if x.get("held") and not (x.get("hatch_covers") or 0):
                pool -= 2                    # (0.105.4 review) waits for a hatch cover (ordered above)
                continue
            if pool >= 2:
                ok_gates.append(x)
                pool -= 2
    build = [] if danger else ok_gates
    # (0.104.164) a pull a dwarf never made ("pulling" for good) is turned too: the bridge sets the gate at once
    # (0.105.33 L5) a given-up well's shaft (no well over it) is kept shut, never opened
    turn = [x for x in gates if (x.get("gate") in ("open", "pulling") and (danger or x.get("cancelled")))
            or (x.get("gate") in ("closed", "pulling") and not danger and not x.get("cancelled"))]
    if danger and turn:
        proposals.append(Proposal("well_shaft", {"type": "well_shaft", "close": True},
                                  f"{danger} near the cavern well: shut its shaft (its hatch, at once)", 2))
    elif turn or build or any(x.get("watching") is False for x in gates):
        if build and any(x.get("gate") in ("none", "stray", "no_lever") for x in build):
            why = ("the cavern well's shaft stands open to the cavern: a lever near the well first, then a hatch "
                   "at the shaft's bottom on it (opened so the bucket passes, shut while a danger is near)")
        elif build:
            steps = []
            if any(x.get("gate") == "unlinked" for x in build):
                steps.append("the cavern well's shaft hatch and lever are built: link them")
            if any(x.get("gate") == "no_hatch" and x.get("held") for x in build):
                steps.append("the cavern well's lever stands, a hatch cover and 2 mechanisms are in store: dig the "
                             "shaft's last level into the cavern, then the hatch on it at once")
            if any(x.get("gate") == "no_hatch" and not x.get("held") for x in build):
                steps.append("the cavern well's lever stands and 2 mechanisms are free: the hatch at the shaft's bottom")
            why = "; ".join(steps)
        elif not turn:
            why = "the cavern well's shaft watcher isn't running (the game was loaded): start it"
        elif all(x.get("cancelled") for x in turn):
            why = "a given-up cavern well's shaft stands open to the cavern: shut its hatch"
        else:
            why = "no danger near the cavern well now: open its shaft again"
        proposals.append(Proposal("well_shaft", {"type": "well_shaft", "close": bool(danger)}, why, 3))
    mech = free_stock(s, "mechanisms")
    far_at = _d(s.get("stocks")).get("mechanisms_unwalkable_at")
    if far_at:                                                    # (0.104.156)
        notes.append(f"mechanisms lie where no dwarf can walk ({far_at}): not counted as free")
    need = sum(3 if x.get("gate") in ("none", "stray", "no_lever") else
               2 if x.get("gate") in ("no_hatch", "unlinked") else 0 for x in gates)   # (0.104.156) every gate's
    if need and mech < need and queued(s, {"mechanisms"}) == 0:
        proposals.append(Proposal("well_shaft", {"type": "work_order", "recipe": "mechanisms", "amount": need - mech},
                                  f"the cavern wells' shaft gates need {need} mechanism(s) (their levers and links; "
                                  f"{mech} in store): make {need - mech}", 3, True))
    for x in gates:
        if x.get("gate_error"):
            notes.append(f"the cavern well's shaft gate: {x['gate_error']}")


SHAFT_LINK_LOST_MAX = 3         # (0.104.156) lever links DF cancelled before the gate waits for other mechanisms


SHAFT_DANGER_TILES = 60          # (0.104.152) a danger this close to a cavern well: its shaft shut


SHAFT_DANGER_OPEN = 80           # ...and opened again only once it's this far (no flapping)


def cavern_danger(s: dict, wells: list | None = None, radius: int = SHAFT_DANGER_TILES) -> str:
    """(0.104.152) What should shut a cavern well's shaft: an enemy free in the
    caverns, or in the rock between the layers (the shaft itself, its
    stairs), within `radius` tiles of a well and below it. Not only fliers:
    a climber can come up a cavern wall next to the opening. Its name, else
    ""."""
    spots = [(w.get("x"), w.get("y"), w.get("z")) for w in (wells or []) if isinstance(w, dict)
             and all(isinstance(w.get(k), int) for k in ("x", "y", "z"))]
    for th in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(th, dict) or th.get("caged"):
            continue
        layer = str(th.get("layer") or "").lower()
        pos = _d(th.get("pos"))
        has_pos = all(isinstance(pos.get(k), int) for k in ("x", "y", "z"))
        if layer.startswith("cavern"):
            if spots and has_pos and not any(max(abs(pos["x"] - x), abs(pos["y"] - y)) <= radius and pos["z"] <= z
                                             for x, y, z in spots):
                continue
        elif layer in ("between_layers", "upper_levels"):
            # in the shaft or its stairs (the rock above the caverns reads as the fort's)
            if not (spots and has_pos and any(max(abs(pos["x"] - x), abs(pos["y"] - y)) <= 2 and pos["z"] < z
                                              for x, y, z in spots)):
                continue
        else:
            continue
        return str(th.get("name") or "an enemy")
    # (0.104.153) hostile wild animals in the caverns (predators, agitated
    # ones): a flier within `radius`, anything within a third of it
    for an in _l(_d(s.get("others_on_map")).get("wild_hostile")):
        pos = _d(an.get("pos")) if isinstance(an, dict) else {}
        if not (spots and all(isinstance(pos.get(k), int) for k in ("x", "y", "z"))):
            continue
        reach = radius if an.get("flier") else radius // 3
        if any(max(abs(pos["x"] - x), abs(pos["y"] - y)) <= reach and pos["z"] <= z for x, y, z in spots):
            return str(an.get("name") or "a wild beast")
    return ""


def _water_zone_rule(s: dict, proposals: list, notes: list, cfg: dict | None = None) -> None:
    """(0.104.2) No well, and the injured or the parched wait for water
    (Enxah, winter y56: 10 patients, 16 parched, 17 GiveWater jobs going
    nowhere while the well's mechanism was held as a stuck order): a Water
    Source zone over open water the dwarves can walk to, where buckets are
    filled at once. Water near the fort first, fresh before stagnant, cavern
    water last (the dwarves walk into the cavern for it). (0.105.33 B4) A
    cavern well whose shaft gate is shut is no well; `cfg` the plan's own
    (PLANNER_CONFIG when not given)."""
    cfg = PLANNER_CONFIG if cfg is None else cfg
    if usable_wells(s):
        return
    if _d(_d(s.get("buildings")).get("zones")).get("WaterSource"):
        # (0.104.13) the zone is there but the game says it holds no water
        # (Enxah, winter y61: its pond frozen, "Give water: No water source"
        # while 10 patients died of thirst): said, and the cavern well dug
        dry = sum(1 for a in _l(s.get("recent_announcements")) if isinstance(a, dict)
                  and "no water source" in str(a.get("text") or "").lower())
        if dry:
            notes.append(f"the water source zone gives no water ({dry} job(s) cancelled: \"No water source\"; "
                         "its water is frozen or gone): the injured get water only from a well")
        return
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    # (0.105.5) Hammerstirred (2 Nov): drink 0-11 for 7 dwarves and no well,
    # and nobody yet parched or injured: the zone waited until they were (a
    # dwarf died of thirst in another fort). Drink under the urgent line is
    # reason enough: dwarves drink from a water source when there's no booze.
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = _d(s.get("stocks")).get("drink")
    dry = isinstance(drink, (int, float)) and drink < citizens * cfg["urgent_drink_per_dwarf"]
    if not patients and not parched and not dry:
        return
    # (0.105.7 review) not while a threat can reach the dwarves (they walk
    # out to the water), nor to cavern water with a cavern danger known
    if int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        notes.append("the dwarves need a water source but a threat can reach them: no walk to open water now")
        return
    danger = cavern_danger(s)
    far = cfg["water_zone_max_d"]
    bodies = [b for b in _l(_d(s.get("water")).get("bodies"))
              if isinstance(b, dict) and isinstance(b.get("nearest"), dict)
              and (b.get("salt_share") or 0) < 50
              and not (danger and b.get("kind") == "cavern")
              and (b["nearest"].get("d") or 999) <= far]
    # (0.105.7 review) the nearest first (the survey's distance, levels
    # counted double), fresh before stagnant; not surface-always-first
    bodies.sort(key=lambda b: ((b.get("stagnant_share") or 0) >= 50, b["nearest"].get("d") or 999))
    points = [{k: b["nearest"].get(k) for k in ("x", "y", "z")} for b in bodies[:6]
              if all(isinstance(b["nearest"].get(k), int) for k in ("x", "y", "z"))]
    who = " and ".join(x for x in (f"{patients} injured" if patients else "",
                                    f"{parched} parched" if parched else "") if x)
    if not who:
        who = f"drink is short ({drink} for {citizens}): the"     # (0.105.5)
    if not points:
        notes.append(f"{who} dwarves wait for water and there is no well, and no open water near the fort "
                     "is known for a water source")
        return
    proposals.append(Proposal("water_zone", {"type": "water_zone", "points": points},
                              f"{who} dwarves wait for water and there is no well"
                              + (" whose shaft is open" if shut_wells(s) else "") + ": a water source zone at the "
                              "nearest open water, where buckets are filled until the well stands", 1))


def cavern_points(s: dict) -> list:
    """(0.105.3) The survey's nearest cavern water, for a gallery out to it."""
    out = []
    for b in _l(_d(s.get("water")).get("bodies")):
        n = _d(_d(b).get("nearest"))
        if _d(b).get("kind") == "cavern" and all(isinstance(n.get(k), int) for k in ("x", "y", "z")):
            out.append({k: n[k] for k in ("x", "y", "z")})
    return out[:3]


def cavern_action(s: dict, cfg: dict, urgent: bool) -> dict:
    """(0.105.3) The cavern well's action: a gallery out to the lake allowed
    (Hammerstirred, 2 Nov: the lake lay beside the fort, under no fort floor)."""
    action = {"type": "place_well", "cavern": True}
    if urgent:
        action["urgent"] = True
    action["gallery"] = int(cfg["cavern_well_gallery"])
    # (0.105.4 review) the bridge's own check follows the Rules tab; (0.105.35)
    # with the switch off the AI decides itself (ai_opens_cavern)
    mode = player_rules(s)["open_caverns"]
    if mode == "always" or (mode == "ai" and unfound_cavern(s) and ai_opens_cavern(s, cfg)[0]):
        action["open_caverns"] = True
    pts = cavern_points(s)
    if pts and action["gallery"] > 0:
        action["toward"] = pts
    return action


def cavern_well_need(s: dict, cfg: dict, patients: int) -> str:
    """Why the fort needs a well badly enough to open a shaft into a cavern
    ("" when it doesn't): the injured need water, drink is running out, or a
    big fort with a hospital or soldiers has nothing to wash wounds with."""
    pop = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = (_d(s.get("stocks")).get("drink") or 0) / pop
    if patients:
        return f"{patients} injured dwarf(s) need water"
    if drink < cfg["cavern_well_drink_pd"]:
        return f"drink is down to {drink:.1f} a dwarf"
    hospital = _d(_d(s.get("buildings")).get("zones")).get("Hospital") or _d(s.get("locations")).get("HOSPITAL")
    if pop >= cfg["cavern_well_hospital_pop"] and hospital:
        return f"a fort of {pop} with a hospital and no water for it"
    if pop >= cfg["cavern_well_hospital_pop"] and (_d(s.get("military")).get("soldiers") or 0) > 0:
        # wounds come with fighting; the shaft takes weeks to dig, so before them
        return f"a fort of {pop} with soldiers will have wounded to wash and give water"
    return ""


def unfound_cavern(s: dict) -> str | None:
    """(0.105.4 review) The cavern layer a cavern well would open, when no
    dwarf has found it yet (its name), else None. Hammerstirred's Cavern1 was
    undiscovered: the first breach is what brings forgotten beasts. The layer
    holding the survey's nearest cavern water, else the first one under the fort."""
    m = _d(s.get("map"))
    layers = [l for l in _l(m.get("layers")) if isinstance(l, dict) and str(l.get("name", "")).startswith("Cavern")]
    if not layers:
        return None
    z = None
    for b in _l(_d(s.get("water")).get("bodies")):
        n = _d(_d(b).get("nearest"))
        if _d(b).get("kind") == "cavern" and isinstance(n.get("z"), int):
            z = n["z"]
    pick = None
    if z is not None:
        pick = next((l for l in layers if isinstance(l.get("z_bottom"), int) and isinstance(l.get("z_top"), int)
                     and l["z_bottom"] - 1 <= z <= l["z_top"] + 1), None)
    if pick is None:
        bottom = _d(m.get("dwarves")).get("z_bottom")
        below = [l for l in layers if isinstance(l.get("z_top"), int)
                 and (not isinstance(bottom, int) or l["z_top"] < bottom)]
        pick = max(below, key=lambda l: l["z_top"]) if below else None
    if pick is not None and pick.get("discovered") is False:
        return str(pick.get("name"))
    return None


def ai_opens_cavern(s: dict, cfg: dict) -> tuple[bool, str]:
    """(0.105.35) The player (11 Nov): nothing waits for the player. With the
    Rules switch "Cavern well into an unfound cavern" at "ai" (its default;
    the switch is three-state: never / ai / always), the AI decides itself
    whether a cavern well may open a cavern no dwarf has found: only when the
    fort is short of water (the injured, the parched, or drink under
    `cavern_well_drink_pd` a dwarf; (0.105.36) unknown drink, a missing
    stocks section, is not short) and has armed soldiers (v35
    fix: armed, not only drafted) for what comes out (`unfound_cavern_soldiers`, +2 at Caution 50+, -1 at Militarism
    50+); at Caution +100 only for the injured or the parched. (ok, why)."""
    tr = _traits(s) if isinstance(s.get("settings"), dict) else {}
    caution = tr.get("caution", 0) or 0
    militarism = tr.get("militarism", 0) or 0
    pop = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    raw_drink = _d(s.get("stocks")).get("drink")
    known = (isinstance(raw_drink, (int, float)) and not isinstance(raw_drink, bool)
             and "stocks" not in _d(s.get("_errors")))
    drink = (raw_drink if known else 0) / pop
    if patients or parched:
        short = " and ".join(x for x in (f"{patients} injured" if patients else "",
                                          f"{parched} parched" if parched else "") if x)
    elif not known:
        return False, "the fort's drink is not known (no stocks report): not counted as short"
    elif drink < cfg["cavern_well_drink_pd"] and caution < 100:
        short = f"drink is down to {drink:.1f} a dwarf"
    elif drink < cfg["cavern_well_drink_pd"]:
        return False, "Caution is at its highest: only for the injured or the parched"
    else:
        return False, "the fort isn't short of water"
    need = int(cfg.get("unfound_cavern_soldiers", WELLS_CONFIG["unfound_cavern_soldiers"]))
    need += 2 if caution >= 50 else 0
    need -= 1 if militarism >= 50 else 0
    need = max(1, need)
    # (v35 fix) armed soldiers only (the squads' `power.armed`; a bridge
    # without the count: their members, as can_fight reads it)
    def armed_of(q):
        a = _d(q.get("power")).get("armed")
        return a if isinstance(a, int) and not isinstance(a, bool) else int(q.get("members") or 0)
    soldiers = sum(armed_of(q) for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict))
    if soldiers < need:
        return False, f"{short}, but only {soldiers} armed soldier(s) to meet what comes out ({need} wanted)"
    return True, f"{short}, and {soldiers} armed soldiers to meet what comes out"


def cavern_open_words(s: dict, cfg: dict) -> str:
    """(0.105.35) The proposal's words when the AI itself opens an unfound cavern ("" otherwise)."""
    layer = unfound_cavern(s)
    if not layer or player_rules(s)["open_caverns"] != "ai":
        return ""
    ok, why = ai_opens_cavern(s, cfg)
    return (f" (it opens {layer} for the first time: the AI's call, {why}; the shaft's hatch shuts while a "
            "danger is near)") if ok else ""


def cavern_well_safe(s: dict, cfg: dict):
    """True, or why a shaft into the caverns shouldn't be dug now."""
    if young_fort(s, cfg) or int(_d(s.get("dwarves")).get("total") or 0) < cfg["cavern_well_min_pop"]:
        return "the fort is too young or small"
    # (0.105.4 review) a cavern nobody has found: the Rules switch on allows it;
    # (0.105.35) off (the default), the AI decides by the fort's state and sliders
    layer = unfound_cavern(s)
    mode = player_rules(s)["open_caverns"]
    if layer and mode == "never":
        return (f"a cavern well would open {layer} for the first time, and the Rules tab says never "
                "(\"Cavern well into an unfound cavern\": Never)")
    if layer and mode == "ai":
        ok, why = ai_opens_cavern(s, cfg)
        if not ok:
            return (f"a cavern well would open {layer} for the first time (cavern creatures and forgotten "
                    f"beasts follow), and the AI does that only when the fort is short of water and has "
                    f"soldiers: {why}")
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return "enemies can reach the dwarves"
    d = _d(s.get("deep"))
    great = [x for x in _l(d.get("dangers")) if isinstance(x, dict) and not x.get("caged")]
    if great:
        return f"{great[0].get('name') or 'a great danger'} is on the map"
    return True


WELL_PARTS_SHOPS = {"stone_blocks": "Masons", "wooden_bucket": "Carpenters", "mechanisms": "Mechanics",
                    "cloth_rope": "Clothiers", "weave_plant_cloth": "Loom", "weave_yarn_cloth": "Loom",
                    "weave_silk_cloth": "Loom", "yarn_rope": "Clothiers", "silk_rope": "Clothiers",
                    "process_plants": "Farmers", "shear_creature": "Farmers", "spin_thread": "Farmers"}


# (0.105.18) a well's chain: one bar of any metal but pig iron, the metals
# the military doesn't want first (A, 3 Nov: silver 12, copper 47)
CHAIN_SKIP = {"PIG_IRON"}


def chain_metal(s: dict) -> str | None:
    """The metal for one chain at a forge with fuel, or None: a non-gear
    metal first, else the commonest gear metal."""
    g = _d(_d(s.get("military")).get("gear"))
    if not g.get("forges") or int(_d(s.get("supplies")).get("fuel") or 0) < 3:
        return None
    bars = {k: int(v) for k, v in _d(g.get("all_bars") or g.get("bars")).items()
            if isinstance(v, (int, float)) and v >= 1 and k not in CHAIN_SKIP}
    if not bars:
        return None
    from planner_core import GEAR_METALS
    other = [k for k in bars if k not in GEAR_METALS]
    pool = other or list(bars)
    return max(pool, key=lambda k: (bars[k], k))


def well_parts_plan(s: dict) -> tuple[list, list, list]:
    """What a well still needs, from the fort's real stocks: (orders to give
    [(recipe, why)], workshops to build first, parts the AI can't make).
    A well takes a block, a bucket, a mechanism and a rope or chain."""
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
        metal = chain_metal(s)
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
    orders, need_shops, stuck = well_parts_plan(s)
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


def _water_traffic_rule(s: dict, proposals: list) -> None:
    """(0.104.45) Rivers and ponds near the surface freeze in winter; dwarves
    cross the ice and drown when it thaws under them (Enxah: the drowned lie in
    the river channel past the main stair). The tiles over that water get the
    game's restricted traffic, so the dwarves' paths go round it. While a
    drowning is in the year's deaths, or once for a fort with surface water."""
    w = _d(s.get("water"))
    mid = _d(w.get("middle"))
    if not mid or not isinstance(mid.get("x"), int) or not isinstance(mid.get("z_high"), int):
        return
    # (0.104.139) every level the water spans (z1..z2), not its top only: the
    # pond by Teacheroar's main stair is z168-170, and 32 drowned at z168
    # (review) the top three of each body, so a body higher up never pushes the low pond out
    levels = sorted({z for b in _l(w.get("bodies")) if isinstance(b, dict)
                     and isinstance(b.get("z2"), int) and b["z2"] >= mid["z_high"] - 4
                     for z in range(max(int(b["z1"] if isinstance(b.get("z1"), int) else b["z2"]), int(b["z2"]) - 2),
                                    int(b["z2"]) + 1)},
                    reverse=True)[:9]
    if not levels:
        return
    deaths = _d(_d(_d(s.get("dead")).get("deaths")).get("by_cause"))
    # (0.104.139) drowning only: SUFFOCATE is strangling (356 of Teacheroar's were)
    drowned = int(deaths.get("DROWN") or 0)
    proposals.append(Proposal("water_traffic", {"type": "restrict_water", "levels": levels, "x": mid["x"],
                                                "y": mid["y"], "radius": 60},
                              ("dwarves drowned this year or last (" + str(drowned) + "): " if drowned else "")
                              + "water near the surface freezes and thaws under the dwarves: restrict traffic "
                              "over it so paths go round", 2 if drowned else 6))


def cistern_pop(traits: dict, cfg: dict) -> int | None:
    """Engineering (simple - mechanical): the cistern at 30 / factor dwarves
    (60 at -100, 15 at +100); None at -150 or lower (no cistern)."""
    e = traits.get("engineering", 0) or 0
    if e <= -150:
        return None
    return max(10, round(cfg["cistern_min_pop"] / factor(traits, "engineering")))


WATER_WORDS = {"river": "flowing river or brook", "surface": "open water on the surface",
               "cavern": "cavern water", "pool": "underground water"}


def magma_access(w: dict, map_: dict | None) -> str | None:
    """(0.104.96) Can magma be reached from the fort without breaking into a
    cavern? 'open' (no cavern between the fort's lowest level and the magma's
    top), 'cavern:<name>' (one lies between: opening it is a big risk, left
    to the AI agent), or None (no magma found, or the map's layers unknown)."""
    mg = _d(w.get("magma"))
    m = _d(map_)
    bottom = _d(m.get("dwarves")).get("z_bottom")
    if not mg or mg.get("z2") is None or not isinstance(bottom, int):
        return None
    for layer in _l(m.get("layers")):
        if not isinstance(layer, dict) or not str(layer.get("name", "")).startswith("Cavern"):
            continue
        top, low = layer.get("z_top"), layer.get("z_bottom")
        # (0.104.98) any cavern reaching from the magma's top up toward the fort:
        # Teacheroar's magma top (z 135) is Cavern1's bottom level, a magma pool
        # inside the cavern ("no cavern between" was said)
        if isinstance(top, int) and isinstance(low, int) and top >= mg["z2"] and low < bottom:
            return f"cavern:{layer['name']}"
    return "open"


def water_summary(w: dict, elev: int = 0, map_: dict | None = None) -> str:
    """The water survey in a line (elev: the map's elevation offset)."""
    parts = []
    for b in _l(w.get("bodies")):
        if not isinstance(b, dict):
            continue
        bits = [f"{b.get('tiles')} tiles"]
        if b.get("salt_share"):
            bits.append(f"{b['salt_share']}% salt")
        if b.get("stagnant_share"):
            bits.append(f"{b['stagnant_share']}% stagnant")
        if b.get("seen_share") is not None and b["seen_share"] < 100:
            bits.append(f"{b['seen_share']}% seen")
        n = _d(b.get("nearest"))
        if n:
            bits.append(f"nearest {n.get('d')} tiles away at elevation {(n.get('z') or 0) + elev}")
        parts.append(f"{WATER_WORDS.get(b.get('kind'), b.get('kind'))} ({', '.join(bits)})")
    aq, mg = _d(w.get("aquifer")), _d(w.get("magma"))
    if aq:
        parts.append(f"an aquifer at elevations {aq.get('z1', 0) + elev}-{aq.get('z2', 0) + elev}")
    if mg:
        line = f"magma from elevation {mg.get('z2', 0) + elev} down"
        acc = magma_access(w, map_)
        if acc and acc.startswith("cavern:"):
            line += (f" (beneath {acc.split(':', 1)[1].lower().replace('cavern', 'cavern ')}: reaching it opens the cavern, "
                     "a risk left to the AI agent)")
        elif acc == "open":
            line += " (no cavern between it and the fort)"
        parts.append(line)
    return "; ".join(parts) if parts else "no water near the fort"


def _water_rules(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """The water survey (lua/ai-water.lua): once a season, and its summary.
    It is what later water work (cisterns, channels, moats, pumps) reads."""
    w = s.get("water")
    if not isinstance(w, dict) or "error" in w:
        return
    now = abs_tick(s)
    tick = w.get("tick")
    def survey() -> dict:
        act = {"type": "survey_water"}
        if cfg["cistern_tunnel_max"] != 30:          # (0.105.3) the cistern's tunnel may reach further
            act["tunnel"] = int(cfg["cistern_tunnel_max"])
        return act
    if w.get("scanning"):
        proposals.append(Proposal("water", survey(),
                                  "the water survey goes on (a slice a cycle, so the game doesn't stall)", 7))
    elif w.get("none") or not isinstance(tick, int) or not 0 <= now - tick < cfg["water_survey_ticks"]:
        proposals.append(Proposal("water", survey(),
                                  "survey the water near the fort (rivers, pools, caverns, aquifer, magma)", 7))
    if not w.get("none"):
        elev = int(_d(s.get("map")).get("elevation_offset") or 0)
        notes.append("water near the fort: " + water_summary(w, elev, s.get("map")))
        c = _d(w.get("cistern"))
        if isinstance(w.get("cistern_status"), dict):
            c = {}                    # (0.99.8) built or being built: the survey's plan for a new one says nothing
        if c and not c.get("none"):
            cw, cs = _d(c.get("well")), _d(c.get("cistern"))
            notes.append(f"cistern plan (not built yet): a 5x5 cistern at elevation {c.get('elevation')} filled from "
                         f"the {c.get('source')}{' (stagnant)' if c.get('stagnant') else ''} through a "
                         f"{c.get('tunnel')}-tile tunnel with a floodgate, the well at x{cw.get('x')} y{cw.get('y')}")
        elif c:
            notes.append(f"no cistern site: {c.get('why')}")


CISTERN_RETRY_SEALS = 3         # (0.105.35) the game refused a wall/floor closing the cistern this often: retired
CISTERN_RELINK_ROUNDS = 2       # (0.105.35) rounds of 3 lost lever links asked afresh before the cistern is retired


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
        if st.get("gate") == "open" and st.get("sealed_now") is False:
            proposals.append(Proposal("cistern", {"type": "cistern_step", "shut": True},
                                      f"the cistern's floodgate is open and it isn't closed where the water goes "
                                      f"({st.get('unsealed')}): shut it now", 0))
        # (0.104.145) the leak guard shut it, or it isn't closed where the water goes
        # (0.105.35) nothing waits for the player: a cistern that leaked twice
        # (the bridge lets water in again once after the first, when dry and
        # closed all round) is retired by the AI, its floodgate shut, and the
        # next one planned elsewhere
        if st.get("leak"):
            if int(st.get("leaks") or 1) >= 2:
                proposals.append(Proposal("cistern", {"type": "cistern_step", "retire": True,
                                                      "why": f"leaked twice (at {st['leak']})"},
                                          f"water got out of the cistern again (over it at {st['leak']}): retire it, "
                                          "its floodgate shut for good; another cistern is planned elsewhere", 2))
            else:
                # (v35 fix) the step the bridge clears the leak in (the water
                # gone and closed all round) and carries on from: asked for,
                # every 2 days while the water still stands over it
                notes.append(f"water got out of the cistern (over it at {st['leak']}): its floodgate was shut. The AI "
                             "lets water in again once the water over it is gone and it is closed all round; "
                             "a second leak retires it")
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
