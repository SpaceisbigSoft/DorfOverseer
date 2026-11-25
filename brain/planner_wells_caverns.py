"""planner_wells_caverns: the wells' settings and status (shut, frozen, bad,
usable), the cavern well's shaft and its danger, opening an unfound cavern
(split out of planner_wells in r7 d4, moved unchanged). planner_wells
re-exports every name here."""

from __future__ import annotations

import math
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_slots import need_slots_free  # noqa: E402  (R2 h3) the small needs' pool

__all__ = ["_far_args", "WELLS_CONFIG", "_shut_rows", "shut_wells", "_frost_wells", "WELL_MIN_DEPTH", "bad_wells", "usable_wells", "NO_WATER_WORDS", "water_zones_usable", "shut_columns", "drinkable_frost_wells", "frost_zone_case", "no_water_cancels", "jailed", "cavern_failure_now", "SHAFT_LINK_LOST_MAX", "SHAFT_DANGER_TILES", "SHAFT_DANGER_OPEN", "SHAFT_DRY_REACH", "_shaft_build_words", "shaft_judged", "shaft_danger_words", "shaft_far_walker", "shaft_water_short", "_shaft_turn", "cavern_danger", "_ice_now", "cavern_points", "cavern_action", "cavern_well_need", "unfound_cavern", "ai_opens_cavern", "cavern_soldiers_ready", "cavern_open_words", "cavern_open_danger", "cavern_well_safe"]


def _far_args(cfg: dict) -> dict:
    """(0.105.38 review) planner_water.far_args (imported late: no import loop),
    its far_reach 0 too when far sources are off by water_job_max 0 (the
    cistern's far tunnel and the far-bank well take only the reach)."""
    from planner_water import far_args, far_on
    out = far_args(cfg)
    if not far_on(cfg):
        out["far_reach"] = 0
    return out

# (0.105.33 B4) the wells' own settings (merged into PLANNER_CONFIG, as planner_threats does)
WELLS_CONFIG = {
    "well_retry_days": 28,      # a well the game refused (given up): another spot tried this long after
    # (0.105.35) a cavern well into a cavern no dwarf has found, the Rules switch off:
    # the AI opens it itself when the fort is short of water and has this many
    # soldiers for what comes out (+2 at Caution 50+, -1 at Militarism 50+)
    "unfound_cavern_soldiers": 3,
}
PLANNER_CONFIG.update({k: v for k, v in WELLS_CONFIG.items() if k not in PLANNER_CONFIG})


def _shut_rows(s: dict, states: tuple = ("closed", "pulling")) -> list:
    pr = _d(s.get("projects"))
    open_ids = {p.get("id") for p in _l(pr.get("open")) if isinstance(p, dict)}
    return [x for x in _l(pr.get("well_lids")) if isinstance(x, dict)
            and (x.get("gate") in states or x.get("door_locked")) and not x.get("cancelled")
            and (x.get("project_id") is None or x.get("project_id") not in open_ids)]


def shut_wells(s: dict, states: tuple = ("closed", "pulling")) -> int:
    """(0.105.33 B4) Built cavern wells whose shaft gate is shut (or being
    pulled): the bucket can't reach the water through a shut hatch. Wells
    still being dug or furnished (in the open list) and given-up shafts are
    not built wells and are not counted. (K48-K4) A gallery well whose door
    the cavern seal locked is cut off from the fort too: counted shut."""
    return len(_shut_rows(s, states))


def _frost_wells(s: dict) -> list:
    """The env_hazards frost part's wells ({id, x, y, z, water}: water,
    ice or dry, what DF has under each well); [] when the part isn't read."""
    from planner_ice import _frost
    out = []
    for w in _l(_frost(s).get("wells")):
        if not isinstance(w, dict):
            continue
        # (r2 h2) a winter cistern (a pond zone on the well) with under 3/7 of
        # water: the bucket comes up empty (a well needs 3/7), so it is dry yet
        d = w.get("depth")
        if (w.get("pond") and w.get("water") == "water" and isinstance(d, int) and not isinstance(d, bool)
                and d < WELL_MIN_DEPTH):
            w = dict(w, water="dry", shallow=True)
        out.append(w)
    return out


WELL_MIN_DEPTH = 3              # (r2 h2) sevenths of water a well's bucket needs (the DF wiki: 3/7)


def bad_wells(s: dict, kinds: tuple = ("dry",), states: tuple = ("closed", "pulling")) -> int:
    """(K48-K4) Built wells that give no water now by the frost reading (dry:
    nothing under them; ice: frozen), less the ones already counted as shut
    cavern wells (the same column: not counted twice)."""
    shut_at = shut_columns(s, states)
    return sum(1 for w in _frost_wells(s) if w.get("water") in kinds and (w.get("x"), w.get("y")) not in shut_at)


def usable_wells(s: dict, states: tuple = ("closed", "pulling"), drinkable: bool = True) -> int:
    """(0.105.33 B4) The wells a bucket can draw from: the built ones less the
    cavern wells whose shaft gate is shut. (K48-K4) And less the wells DF
    has nothing under (dry), and with `drinkable` the frozen ones too: only
    water a dwarf can drink now (the frost rule places a well for frozen ones)."""
    wells = int(_d(_d(s.get("buildings")).get("other")).get("Well", 0) or 0)
    kinds = ("dry", "ice") if drinkable else ("dry",)
    return max(0, wells - shut_wells(s, states) - bad_wells(s, kinds, states))


NO_WATER_WORDS = "no water source"


def water_zones_usable(s: dict) -> int:
    """(K48-K4) The Water Source zones that give water now: the zones less
    the AI's own ones the frost reading finds frozen, dry or gone; none at all
    when a job was cancelled for "No water source" and none of the AI's zones
    reads as water (War-hold: one zone DF called empty, 0 usable wells, and
    the zone rule stopped at "a zone exists")."""
    n = _d(_d(s.get("buildings")).get("zones")).get("WaterSource") or 0
    n = n if isinstance(n, int) and not isinstance(n, bool) else (1 if n else 0)
    from planner_ice import _frost
    rows = [z for z in _l(_frost(s).get("zones")) if isinstance(z, dict)]
    n = max(0, n - sum(1 for z in rows if z.get("water") != "water"))
    # (an older bridge, no frost reading: the zones taken at their word as before)
    if n and _frost(s) and not any(z.get("water") == "water" for z in rows) and no_water_cancels(s):
        return 0
    return n


def shut_columns(s: dict, states: tuple = ("closed", "pulling")) -> set:
    """(K48-K4) The (x, y) columns of the cavern wells shut off (shaft gate
    shut, or their door locked): the well over each stands there."""
    out = set()
    for x in _shut_rows(s, states):
        h = _d(x.get("shaft_hatch"))
        if isinstance(h.get("x"), int) and isinstance(h.get("y"), int):
            out.add((h["x"], h["y"]))
    return out


def drinkable_frost_wells(s: dict) -> list:
    """(K48-K4) The frost reading's wells with water under them, less the
    cavern wells shut off: the frost rule's "a well still draws water" (it
    looked past a shut hatch)."""
    shut = shut_columns(s)
    return [w for w in _frost_wells(s) if w.get("water") == "water" and (w.get("x"), w.get("y")) not in shut]


def frost_zone_case(s: dict) -> bool:
    """(K48-K4) The frost rule's own case (planner_hazards frost_water_zone):
    the AI's zones read, none gives water, one is ice, and no well draws."""
    from planner_ice import _frost
    rows = [z for z in _l(_frost(s).get("zones")) if isinstance(z, dict)]
    return bool(rows and all(z.get("water") != "water" for z in rows) and any(z.get("water") == "ice" for z in rows)
                and not drinkable_frost_wells(s))


def no_water_cancels(s: dict) -> int:
    """Jobs cancelled for "No water source" in the recent announcements."""
    return sum(1 for a in _l(s.get("recent_announcements")) if isinstance(a, dict)
               and NO_WATER_WORDS in str(a.get("text") or "").lower())


def jailed(s: dict) -> int:
    """(item5) Citizens serving time in the jail: they drink only water
    carried from a well or a water zone (the bridge's justice.prisoners, else
    its count of punishments with time in jail)."""
    j = _d(s.get("justice"))
    pr = j.get("prisoners")
    if isinstance(pr, list):
        return sum(1 for p in pr if isinstance(p, dict))
    return int(_d(j.get("punish")).get("prison") or 0)


def cavern_failure_now(s: dict, memory, cfg: dict) -> str:
    """(K48-K4) The cavern well's refusal, while it stands: well_retry_days
    after it (stamped when it came; an older memory's is stamped now) it is
    forgotten and a cavern well is tried again. Before, one refusal (a search
    cut short, a cached "no spot", a stalled shaft) held for the fort's life."""
    if memory is None or not memory.cavern_well_failure:
        return ""
    now = abs_tick(s)
    at = getattr(memory, "cavern_well_failure_at", None)
    if not isinstance(at, int) or at > now:
        memory.cavern_well_failure_at = now
        return memory.cavern_well_failure
    days = cfg.get("well_retry_days", WELLS_CONFIG["well_retry_days"])
    if now - at >= days * TICKS_PER_DAY:
        memory.cavern_well_failure = ""
        memory.cavern_well_failure_at = None
        return ""
    return memory.cavern_well_failure


SHAFT_LINK_LOST_MAX = 3         # (0.104.156) lever links DF cancelled before the gate waits for other mechanisms


SHAFT_DANGER_TILES = 60          # (0.104.152) a danger this close to a cavern well: its shaft shut


SHAFT_DANGER_OPEN = 80           # ...and opened again only once it's this far (no flapping)


SHAFT_DRY_REACH = 25             # (group 2) the bridge's SHAFT_CLOSE + SHAFT_DRY_MARGIN: a walker this near a shut
                                 # shaft keeps it shut even while the fort is short of water


def _shaft_build_words(build: list) -> str:
    """The well_shaft step's words for the gates still being built ("" when none)."""
    if build and any(x.get("gate") in ("none", "stray", "no_lever") for x in build):
        return ("the cavern well's shaft stands open to the cavern: a lever near the well first, then a hatch "
                "at the shaft's bottom on it (opened so the bucket passes, shut while a danger is near)")
    steps = []
    if any(x.get("gate") == "unlinked" for x in build):
        steps.append("the cavern well's shaft hatch and lever are built: link them")
    if any(x.get("gate") == "no_hatch" and x.get("held") for x in build):
        steps.append("the cavern well's lever stands, a hatch cover and 2 mechanisms are in store: dig the "
                     "shaft's last level into the cavern, then the hatch on it at once")
    if any(x.get("gate") == "no_hatch" and not x.get("held") for x in build):
        steps.append("the cavern well's lever stands and 2 mechanisms are free: the hatch at the shaft's bottom")
    return "; ".join(steps)


def shaft_judged(gates: list) -> bool:
    """(group 2) The bridge judges the shaft's dangers itself (watch_rule 2 on a
    linked gate): the brain goes by its verdict, watch_near, and its hold."""
    return any(isinstance(x, dict) and (x.get("watch_rule") or 0) >= 2 for x in gates)


def shaft_danger_words(near: dict) -> str:
    """'<name> (flies, 34 tiles from the shaft)' for a watch_near verdict."""
    name = str(near.get("name") or "a wild beast")
    if near.get("in_shaft"):
        return f"{name} (in the shaft)"
    how = ("flies" if near.get("flier") else "climbs" if near.get("climber") else
           "may climb" if near.get("mobile") else "walks or swims")
    d = near.get("d")
    return f"{name} ({how}, {d} tiles from the shaft)" if isinstance(d, int) else f"{name} ({how})"


def shaft_far_walker(near: dict) -> bool:
    """(group 2) A danger that can't fly or climb, not in the shaft and
    further than a walker's reach: kept out by the drop under the opening.
    While the fort is short of water it doesn't keep the shaft shut."""
    d = near.get("d")
    return (not near.get("in_shaft") and near.get("mobile") is False and not near.get("flier")
            and isinstance(d, int) and d > SHAFT_DRY_REACH)


def shaft_water_short(s: dict, gates: list, cfg: dict | None = None) -> str:
    """(group 2) Why the fort would be short of water with its cavern wells'
    shafts shut ("" when it isn't): no well but the cavern wells, no water
    source zone, and someone needs water (injured, parched) or the drink is
    under the urgent line. Whether a shaft is open now doesn't count (an
    open one would read as water, and the `dry` mode would flap with it)."""
    cfg = PLANNER_CONFIG if cfg is None else cfg
    cavern = [x for x in gates if not x.get("cancelled")]     # a gate being linked: its hatch shut too
    # (K48-K4b, A4 20) a cavern well still being dug has no Well building yet
    built = [x for x in cavern if not (x.get("held") or x.get("breaking") or x.get("digging"))]
    wells = int(_d(_d(s.get("buildings")).get("other")).get("Well", 0) or 0)
    # (K48-K4) only wells and zones that give water now: a dry or frozen
    # ordinary well, or a zone DF calls empty, is no water
    cols = {(_d(x.get("shaft_hatch")).get("x"), _d(x.get("shaft_hatch")).get("y")) for x in cavern}
    bad = sum(1 for w in _frost_wells(s) if w.get("water") in ("dry", "ice") and (w.get("x"), w.get("y")) not in cols)
    if wells - bad > len(built):
        return ""
    if water_zones_usable(s):
        return ""
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = _d(s.get("stocks")).get("drink")
    low = isinstance(drink, (int, float)) and drink < citizens * cfg.get("urgent_drink_per_dwarf", 2)
    why = [w for w in (f"{patients} injured need water" if patients else "",
                       f"{parched} parched" if parched else "",
                       f"drink {int(drink)} for {citizens} dwarves" if low else "") if w]
    return ", ".join(why)


def _shaft_turn(s: dict, gates: list, build: list, proposals: list, notes: list) -> None:
    """(group 2) The shaft gates by the bridge's verdict: shut where it finds a
    danger (its watcher has most likely done it already), opened where it
    finds none and the gate's hold (shut a day at least, the danger away
    half a day) has run out. Short of water with every cavern well shut: a
    danger that can't fly or climb, far off, doesn't keep it shut (the
    bridge's `dry`); one that can keeps it shut, said in a note (the water
    zone rule gives open water meanwhile)."""
    where = lambda x: f"x{x.get('x')} y{x.get('y')} elevation {x.get('elevation')}"
    live = [x for x in gates if not x.get("cancelled")]
    shut_now = [x for x in live if x.get("gate") in ("closed", "pulling")]
    short = shaft_water_short(s, gates)
    dry_on = any(x.get("watch_dry") for x in gates)
    # (item2) a great beast in the cavern layer a shaft opens into (a flier
    # near any shaft into it, or one unseen there) keeps the shaft shut, short
    # of water or not, whatever the watcher's per-shaft distance; only a dwarf
    # dying of thirst with no other water opens one: the farthest from it
    from planner_shaft_guard import guard_distance, shaft_layer_guard, shaft_thirst_lethal
    guard = shaft_layer_guard(s, gates)
    linked = [x for x in live if x.get("gate") in ("open", "closed", "pulling")]
    lethal = shaft_thirst_lethal(s) if (short and guard) else ""
    spare = None
    if lethal:
        def water_from(x: dict) -> bool:
            if x.get("project_id") in guard:
                return False
            wn = _d(x.get("watch_near"))
            return x.get("gate") == "open" or (x in shut_now and (not wn or shaft_far_walker(wn)))
        if not any(water_from(x) for x in linked):
            cands = [x for x in linked if x.get("project_id") in guard and not _d(x.get("watch_near"))]
            pool = [x for x in cands if x.get("gate") == "open"] or cands
            if pool:
                spare = max(pool, key=lambda x: guard_distance(x, guard[x["project_id"]]))
    keep = sorted(x["project_id"] for x in linked if x.get("project_id") in guard and x is not spare)
    to_shut = [x for x in gates if x.get("gate") in ("open", "pulling")
               and (_d(x.get("watch_near")) or x.get("cancelled") or x.get("project_id") in keep)]
    if to_shut:
        near = next((_d(x.get("watch_near")) for x in to_shut if _d(x.get("watch_near"))), None)
        kept = [x for x in to_shut if x.get("project_id") in keep and not _d(x.get("watch_near"))]
        if near:
            why = f"{shaft_danger_words(near)} near the cavern well: shut its shaft (its hatch, at once)"
        elif kept:
            info = guard[kept[0]["project_id"]]
            why = (f"{info['why']}, the cavern layer the cavern well's shaft opens into: shut the shaft "
                   "(its hatch, at once; a flier crosses the layer between two looks)")
        else:
            why = "a given-up cavern well's shaft stands open to the cavern: shut its hatch"
        # (K48-K4b, A4 14) a given-up shaft alone: close false (the bridge shuts a
        # cancelled one on any call); close true with no danger shut every
        # working well too, each for a day
        act = {"type": "well_shaft", "close": bool(near)}
        if keep:
            act["keep_shut"] = keep
        if dry_on and not short:
            act["dry"] = False
        proposals.append(Proposal("well_shaft", act, why, 2))
        return
    opens, far, held, guarded = [], [], [], []
    for x in shut_now:
        near = _d(x.get("watch_near"))
        hold = x.get("shut_hold") or 0
        if x.get("project_id") in keep:
            guarded.append(x)
        elif near and short and shaft_far_walker(near):
            far.append(x)
        elif near:
            held.append(x)
        elif hold > 0 and not short:
            notes.append(f"the cavern well's shaft at {where(x)} stays shut a while yet ({hold} ticks): "
                         "opened once the danger has been away long enough (no flapping)")
        else:
            opens.append(x)
    for x in guarded:
        info = guard[x["project_id"]]
        words = (f"the cavern well's shaft at {where(x)} is kept shut: {info['why']}, the cavern layer it opens "
                 "into, could reach it across the layer")
        if short:
            words += (f"; the fort is short of water ({short}): open water outside the caverns is made a water "
                      "source meanwhile")
            if lethal and spare is None:
                words += f" ({lethal}, but every shaft has a danger at it)"
        notes.append(words + "; opened once it is dead, caged or out of that layer")
    for x in held:
        near = _d(x.get("watch_near"))
        words = shaft_danger_words(near)
        if short:
            # (group 2) said, not asked (the standing rule: what the AI can do, it
            # does): the water zone rule marks open water outside the caverns
            # meanwhile, the well rule places another well when it can
            notes.append(f"the cavern well's shaft at {where(x)} is shut against {words} and the fort is short "
                         f"of water ({short}): kept shut, since it could come up the shaft; while no well draws, open "
                         "water outside the caverns is made a water source, and the shaft opens once it has been "
                         "away a while")
        else:
            notes.append(f"the cavern well's shaft is shut while {words} is near: still counted as a well, "
                         "opened again once it has been away a while")
    act = {"type": "well_shaft", "close": False}
    want_dry = bool(short) and bool(far or (opens and any((x.get("shut_hold") or 0) > 0 for x in opens)))
    if want_dry != dry_on and (want_dry or not short):
        act["dry"] = want_dry
    if keep:
        act["keep_shut"] = keep
    words = _shaft_build_words(build)
    unmarked = [x for x in guarded if not x.get("layer_guard")]
    if far:
        near = _d(far[0].get("watch_near"))
        why = (f"the fort is short of water ({short}) and every cavern well is shut, but "
               f"{shaft_danger_words(near)} can't fly or climb up to the opening: open the shaft")
    elif opens:
        why = "no danger near the cavern well now: open its shaft again"
        if short and any((x.get("shut_hold") or 0) > 0 for x in opens):
            why = f"the fort is short of water ({short}): open the cavern well's shaft again at once"
        if spare is not None and spare in opens:
            info = guard[spare["project_id"]]
            d = guard_distance(spare, info)
            how = f"{d} tiles from it" if d >= 0 else "its place unknown"
            why = (f"{lethal} and no other water: open the one cavern well's shaft farthest from {info['name']} "
                   f"(at {where(spare)}, {how}) though {info['why']} is in its layer; the others kept shut")
        elif guarded:
            why += f"; the shaft(s) into a layer with {guard[guarded[0]['project_id']]['why']} kept shut"
    elif words:
        why = words
    elif unmarked:
        # (item2) the bridge told which gates it keeps shut (its watcher no longer opens them)
        why = (f"{guard[unmarked[0]['project_id']]['why']}, the cavern layer the cavern well's shaft opens into: "
               "keep the shaft shut (the watcher doesn't open it while the beast is in that layer)")
    elif "dry" in act:
        why = "the fort has water again: the cavern well's shaft watched as usual"
    elif any(x.get("watching") is False for x in gates):
        why = "the cavern well's shaft watcher isn't running (the game was loaded): start it"
    else:
        return
    if words and why != words:
        why += "; " + words
    pri = 2 if (far or short or (unmarked and not opens)) else 3
    proposals.append(Proposal("well_shaft", act, why, pri))


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


def _ice_now(s: dict, memory, cfg: dict | None = None) -> bool:
    """(0.105.47) Surface water counts as freezing now (brain/planner_ice.py),
    or (as before) it is winter at a fort where ice was seen."""
    from planner_ice import ice_season
    if ice_season(s, memory, cfg)[0]:
        return True
    return bool(memory is not None and getattr(memory, "climate_freezes", False)
                and _d(s.get("date")).get("season") == "winter")


def cavern_points(s: dict) -> list:
    """(0.105.3) The survey's nearest cavern water, for a gallery out to it."""
    out = []
    for b in _l(_d(s.get("water")).get("bodies")):
        n = _d(_d(b).get("nearest"))
        if _d(b).get("kind") == "cavern" and all(isinstance(n.get(k), int) for k in ("x", "y", "z")):
            out.append({k: n[k] for k in ("x", "y", "z")})
    return out[:3]


def cavern_action(s: dict, cfg: dict, urgent: bool, winter: str = "") -> dict:
    """(0.105.3) The cavern well's action: a gallery out to the lake allowed
    (Hammerstirred, 2 Nov: the lake lay beside the fort, under no fort floor)."""
    action = {"type": "place_well", "cavern": True}
    if urgent:
        action["urgent"] = True
    action["gallery"] = int(cfg["cavern_well_gallery"])
    # (0.105.4 review) the bridge's own check follows the Rules tab; (0.105.35)
    # with the switch off the AI decides itself (ai_opens_cavern)
    mode = player_rules(s)["open_caverns"]
    if mode == "always" or (mode == "ai" and unfound_cavern(s) and ai_opens_cavern(s, cfg, winter)[0]):
        action["open_caverns"] = True
    pts = cavern_points(s)
    if pts and action["gallery"] > 0:
        action["toward"] = pts
    # (0.105.47) the bridge holds to the same cooldown and site cap (ai-well-safety
    # place_gate; its own defaults are 84 and 2: sent only when set otherwise)
    cd = int(cfg.get("cavern_well_cooldown_days", PLANNER_CONFIG.get("cavern_well_cooldown_days", 84)))
    tries = int(cfg.get("cavern_well_site_tries", PLANNER_CONFIG.get("cavern_well_site_tries", 2)))
    if cd != 84:
        action["cooldown_days"] = cd
    if tries != 2:
        action["site_tries"] = tries
    return action


def cavern_well_need(s: dict, cfg: dict, patients: int) -> str:
    """Why the fort needs a well badly enough to open a shaft into a cavern
    ("" when it doesn't): the injured need water, drink is running out, or a
    big fort with a hospital or soldiers has nothing to wash wounds with."""
    pop = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = (_d(s.get("stocks")).get("drink") or 0) / pop
    if patients:
        return f"{patients} injured dwarf(s) need water"
    if jailed(s):
        return f"{jailed(s)} dwarf(s) in the jail need water (prisoners get no booze)"
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


def ai_opens_cavern(s: dict, cfg: dict, winter: str = "") -> tuple[bool, str]:
    """(0.105.35) The player (11 Nov): nothing waits for the player. With the
    Rules switch "Cavern well into an unfound cavern" at "ai" (its default;
    the switch is three-state: never / ai / always), the AI decides itself
    whether a cavern well may open a cavern no dwarf has found: only when the
    fort is short of water (the injured, the parched, or drink under
    `cavern_well_drink_pd` a dwarf; (0.105.36) unknown drink, a missing
    stocks section, is not short) and has armed soldiers (v35
    fix: armed, not only drafted) for what comes out (`unfound_cavern_soldiers`, +2 at Caution 50+, -1 at Militarism
    50+); at Caution +100 only for the injured or the parched. (ok, why).
    (r1 g3) `winter`: the fort has no water that works in winter (its wells
    and water freeze, winter_water_need's why): short of water too, below
    Caution +100, as drink running out is (B: every patient of every winter
    died of thirst); the soldiers are still wanted."""
    tr = _traits(s) if isinstance(s.get("settings"), dict) else {}
    caution = tr.get("caution", 0) or 0
    militarism = tr.get("militarism", 0) or 0
    pop = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    prisoners = jailed(s)                 # (item5) they drink only from a well
    raw_drink = _d(s.get("stocks")).get("drink")
    known = (isinstance(raw_drink, (int, float)) and not isinstance(raw_drink, bool)
             and "stocks" not in _d(s.get("_errors")))
    drink = (raw_drink if known else 0) / pop
    if patients or parched or prisoners:
        short = " and ".join(x for x in (f"{patients} injured" if patients else "",
                                          f"{parched} parched" if parched else "",
                                          f"{prisoners} jailed" if prisoners else "") if x)
    elif winter and caution < 100:
        short = winter
    elif not known:
        return False, "the fort's drink is not known (no stocks report): not counted as short"
    elif drink < cfg["cavern_well_drink_pd"] and caution < 100:
        short = f"drink is down to {drink:.1f} a dwarf"
    elif drink < cfg["cavern_well_drink_pd"]:
        return False, "Caution is at its highest: only for the injured or the parched"
    else:
        return False, "the fort isn't short of water"
    ok, soldiers, need = cavern_soldiers_ready(s, cfg)
    if not ok:
        return False, f"{short}, but only {soldiers} armed soldier(s) to meet what comes out ({need} wanted)"
    return True, f"{short}, and {soldiers} armed soldiers to meet what comes out"


def cavern_soldiers_ready(s: dict, cfg: dict) -> tuple[bool, int, int]:
    """(0.105.38 review) The soldier half of ai_opens_cavern: armed soldiers
    enough for what comes out of an opened cavern (`unfound_cavern_soldiers`,
    +2 at Caution 50+, -1 at Militarism 50+). (ok, soldiers, wanted)."""
    tr = _traits(s) if isinstance(s.get("settings"), dict) else {}
    caution = tr.get("caution", 0) or 0
    militarism = tr.get("militarism", 0) or 0
    need = int(cfg.get("unfound_cavern_soldiers", WELLS_CONFIG["unfound_cavern_soldiers"]))
    need += 2 if caution >= 50 else 0
    need -= 1 if militarism >= 50 else 0
    need = max(1, need)
    # (item5) a small fort can't field the squad a big one keeps: a soldier for
    # every 5 dwarves at most (Hammerstirred, 15 dwarves and Caution +60, was
    # asked for 5 and had 3, while its dwarves died of thirst)
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    if pop > 0:
        need = max(1, min(need, pop // 5))
    # (v35 fix) armed soldiers only (the squads' `power.armed`; a bridge
    # without the count: their members, as can_fight reads it)
    def armed_of(q):
        a = _d(q.get("power")).get("armed")
        return a if isinstance(a, int) and not isinstance(a, bool) else int(q.get("members") or 0)
    soldiers = sum(armed_of(q) for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict))
    return soldiers >= need, soldiers, need


def cavern_open_words(s: dict, cfg: dict, winter: str = "") -> str:
    """(0.105.35) The proposal's words when the AI itself opens an unfound cavern ("" otherwise)."""
    layer = unfound_cavern(s)
    if not layer or player_rules(s)["open_caverns"] != "ai":
        return ""
    ok, why = ai_opens_cavern(s, cfg, winter)
    return (f" (it opens {layer} for the first time: the AI's call, {why}; the shaft's hatch shuts while a "
            "danger is near)") if ok else ""


def cavern_open_danger(s: dict) -> str:
    """(K48-K4) Why a dig that opens a cavern shouldn't start now ("" when
    it may): the cavern well's own danger tests (enemies that reach the
    dwarves, a great danger on the map, an enemy free in the caverns, a
    danger at a cavern well's shaft). The magma workshop's way through a
    cavern was opened with none of them."""
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return "enemies can reach the dwarves"
    great = [x for x in _l(_d(s.get("deep")).get("dangers")) if isinstance(x, dict) and not x.get("caged")]
    if great:
        return f"{great[0].get('name') or 'a great danger'} is on the map"
    for x in _l(_d(s.get("projects")).get("well_lids")):
        near = _d(_d(x).get("watch_near"))
        if near:
            return f"{shaft_danger_words(near)} is at a cavern well's shaft"
    danger = cavern_danger(s)
    if danger:
        return f"{danger} is in the caverns"
    return ""


def cavern_well_safe(s: dict, cfg: dict, urgent: bool = False, winter: str = ""):
    """True, or why a shaft into the caverns shouldn't be dug now.
    (item5) urgent: the fort has no well and the injured, the parched or the
    jailed wait for water: then a small or young fort digs one too (the
    Hermit hold, 15 dwarves and no other water, was told "too young or small"
    while 10 of them died of thirst)."""
    if not urgent and (young_fort(s, cfg) or int(_d(s.get("dwarves")).get("total") or 0) < cfg["cavern_well_min_pop"]):
        return "the fort is too young or small"
    # (0.105.4 review) a cavern nobody has found: the Rules switch on allows it;
    # (0.105.35) off (the default), the AI decides by the fort's state and sliders
    layer = unfound_cavern(s)
    mode = player_rules(s)["open_caverns"]
    if layer and mode == "never":
        return (f"a cavern well would open {layer} for the first time, and the Rules tab says never "
                "(\"Cavern well into an unfound cavern\": Never)")
    if layer and mode == "ai":
        ok, why = ai_opens_cavern(s, cfg, winter)
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
    # (0.105.47) one cavern well at a time, and none for a season after one
    # was given up (E: 13 in 6 hours; brain/planner_wellsafe.py)
    from planner_wellsafe import cavern_well_wait
    wait = cavern_well_wait(s, cfg)
    if wait:
        return wait
    return True
