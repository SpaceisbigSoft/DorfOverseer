"""planner_wells_water: the well's lid, the water zones, water traffic, the
cistern's size, magma access and the water summary (split out of
planner_wells in r7 d4, moved unchanged). planner_wells keeps the well
rule, the well's parts (chain_metal is patched there by a test), the
cistern and winter water, and re-exports every name here."""

from __future__ import annotations

import math
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_slots import need_slots_free  # noqa: E402  (R2 h3) the small needs' pool
from planner_wells_caverns import *  # noqa: F401,F403  (r7 d4: split out by theme)

__all__ = ["_well_lid_rule", "_water_zone_rule", "_water_traffic_rule", "cistern_pop", "WATER_WORDS", "magma_access", "water_summary", "_water_rules"]


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
    # (K48-K4b, A4 12) an open lid over a shaft still being dug is left unlocked (the miners' way)
    todo = [x for x in lids if x.get("gate") == "none_possible" and x.get("state") in ("none", "open")
            and not x.get("gate_hatch_standing") and not (x.get("state") == "open" and x.get("digging"))]
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
    judged = shaft_judged(gates)
    shut = [x for x in gates if x.get("gate") == "closed"]
    if judged:
        # (group 2) the bridge's own verdict (shaft_judge in ai-builder-wells.lua),
        # the one its watcher shuts by and well_shaft opens by: the brain no
        # longer second-guesses it with the report's threat list
        near = [x for x in gates if _d(x.get("watch_near"))]
        danger = shaft_danger_words(_d(near[0].get("watch_near"))) if near else ""
    else:
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
    if judged:
        # (K48-K4b, A4 11) the bridge tests each well's own shaft before it sends
        # a dwarf down beside the opening (the break, the hatch, the link): a
        # danger at another well's shaft no longer holds this one's gate back
        # for ever; one at its own still does
        build = [x for x in ok_gates if not _d(x.get("watch_near"))]
        _shaft_turn(s, gates, build, proposals, notes)
    else:
        # (0.104.164) a pull a dwarf never made ("pulling" for good) is turned too: the bridge sets the gate at once
        # (0.105.33 L5) a given-up well's shaft (no well over it) is kept shut, never opened
        turn = [x for x in gates if (x.get("gate") in ("open", "pulling") and (danger or x.get("cancelled")))
                or (x.get("gate") in ("closed", "pulling") and not danger and not x.get("cancelled"))]
        if danger and turn:
            proposals.append(Proposal("well_shaft", {"type": "well_shaft", "close": True},
                                      f"{danger} near the cavern well: shut its shaft (its hatch, at once)", 2))
        elif turn or build or any(x.get("watching") is False for x in gates):
            why = _shaft_build_words(build)
            if not why:
                if not turn:
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


def _water_zone_rule(s: dict, proposals: list, notes: list, cfg: dict | None = None) -> None:
    """(0.104.2) No well, and the injured or the parched wait for water
    (Enxah, winter y56: 10 patients, 16 parched, 17 GiveWater jobs going
    nowhere while the well's mechanism was held as a stuck order): a Water
    Source zone over open water the dwarves can walk to, where buckets are
    filled at once. Water outside the caverns first, then near before far,
    fresh before stagnant; cavern water last (the dwarves walk into the
    cavern for it; War-hold: six drowned in the lake). (0.105.33 B4) A
    cavern well whose shaft gate is shut is no well; `cfg` the plan's own
    (PLANNER_CONFIG when not given)."""
    cfg = PLANNER_CONFIG if cfg is None else cfg
    if usable_wells(s):
        return
    if _d(_d(s.get("buildings")).get("zones")).get("WaterSource") and water_zones_usable(s):
        # (an older bridge, no frost reading: the zone taken at its word, said as before)
        dry = no_water_cancels(s)
        if dry:
            notes.append(f"the water source zone gives no water ({dry} job(s) cancelled: \"No water source\"; "
                         "its water is frozen or gone): the injured get water only from a well")
        return
    if _d(_d(s.get("buildings")).get("zones")).get("WaterSource"):
        # (0.104.13) the zone is there but the game says it holds no water
        # (Enxah, winter y61: its pond frozen, "Give water: No water source"
        # while 10 patients died of thirst). (K48-K4) No longer the end of it
        # (War-hold: 0 usable wells and only that note): such a zone counts
        # as none and the next one is placed below (the frost rule's own
        # case, frozen zones, is left to it)
        dry = no_water_cancels(s)
        if dry:
            notes.append(f"the water source zone gives no water ({dry} job(s) cancelled: \"No water source\"; "
                         "its water is frozen or gone): another water source is looked for")
    if frost_zone_case(s):
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
    # (0.105.47, I7d 2f) no water zone on surface water from the last
    # half-month of autumn (planner_ice retires the ones there): underground
    # or cavern water only
    if _ice_now(s, None, cfg):
        bodies = [b for b in bodies if b.get("underground") or b.get("kind") == "cavern"]
    # (0.105.7 review) the nearest first (the survey's distance, levels
    # counted double), fresh before stagnant; not surface-always-first
    # (K48-K4b, A4 15) cavern water after any other (the docstring's order; it
    # was sorted by distance alone and the cavern lake came first)
    bodies.sort(key=lambda b: (b.get("kind") == "cavern", (b.get("stagnant_share") or 0) >= 50,
                               b["nearest"].get("d") or 999))
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
        if "far_reach" in _far_args(cfg):   # (0.105.38; review: 0 sent too, far sources off)
            act["far_reach"] = _far_args(cfg)["far_reach"]
        return act
    if w.get("scanning"):
        act = survey()
        # (r2h1, A4 B3) a longer slice while the survey runs: a 288x288x194
        # map needs ~90 slices of 0.15 s, a season gave A ~40 cycles
        sl = cfg.get("h1_water_slice_seconds")
        if isinstance(sl, (int, float)) and not isinstance(sl, bool) and sl > 0:
            act["seconds"] = float(sl)
        proposals.append(Proposal("water", act,
                                  "the water survey goes on (a slice a cycle, so the game doesn't stall)", 7))
    elif w.get("none") or not isinstance(tick, int) or not 0 <= now - tick < cfg["water_survey_ticks"]:
        proposals.append(Proposal("water", survey(),
                                  "survey the water near the fort (rivers, pools, caverns, aquifer, magma)", 7))
    elif w.get("waters_pending") is True and (not isinstance(w.get("near_tick"), int)
                                              or now - w["near_tick"] > cfg.get("water_pending_retry_ticks", 1200)):
        # (0.105.38 review) the near box saved but the whole-map pass cut off
        # (a save, a quit, the map unloaded): begun again now, not a season on;
        # (third review) a day after the near save at the soonest (a survey
        # that fails to start is not asked for every cycle)
        proposals.append(Proposal("water", survey(),
                                  "the water survey of the whole map was cut off: begun again", 7))
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
