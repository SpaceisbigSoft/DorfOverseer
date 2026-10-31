"""planner_military: part of the planner (split out of planner.py in 0.104.83; see planner.py)."""

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

__all__ = ["gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule", "GEAR_HELD", "_shelter_possible", "soldier_share", "_gate_rules", "_free_gate_lever", "_free_gate_levers", "_lever_far_enough", "_link_wanted", "_lever_rule", "_trap_rule", "_near_spot", "soldiers_wanted", "crossing_value", "_crossing_rule", "ALERT_DANGERS", "alert_ages", "_alerts_rule", "_war_animal_rule", "hazard_alert", "_hazard_rules", "_military_rules", "_training_rotation", "_ranged_squad_rule", "WEAPON_IDS", "_uniform_weapon_rule", "_anvil_rule", "idle_hands"]



GEAR_HELD = {"weapons": "armed", "body": "armored", "helms": "helmed", "shields": "shielded", "pants": "legged",
             "boots": "booted", "gloves": "gloved"}


def _shelter_possible(s: dict, memory) -> bool:
    return (s.get("civ_alert_ready") is False and player_rules(s)["alert_shelter"]
            and memory.shelter_attempts < 2)


def soldier_share(s: dict, cfg: dict) -> float:
    """The share of citizens in squads, from Militarism's effective value
    (Extreme doubles it, since 0.94): -200 none, -100 5%, 0 10%, +100 40%,
    +200 90%, straight lines between."""
    v = max(-200.0, min(200.0, float(_traits(s).get("militarism", 0))))
    lo, mid, hi = cfg["soldier_share_low"], cfg["soldier_share_mid"], cfg["soldier_share_high"]
    top = cfg["soldier_share_extreme_high"]
    if v > 100:
        return hi + (top - hi) * (v - 100) / 100
    if v < -100:
        return lo * (1 - (abs(v) - 100) / 100)
    if v < 0:
        return mid + (mid - lo) * v / 100
    return mid + (hi - mid) * v / 100


def _gate_rules(s: dict, memory, cfg: dict, rules_: dict, any_reach: bool,
                proposals: list, notes: list, traits: dict | None = None) -> None:
    ent = _d(s.get("entrances"))
    now = abs_tick(s)
    age = now - ent["scanned_tick"] if isinstance(ent.get("scanned_tick"), int) else None
    stale = (not ent.get("scanned") or age is None or not 0 <= age < cfg["entrance_scan_ticks"]
             or memory.rescan_entrances)
    if stale:
        proposals.append(Proposal("entrances", {"type": "scan_entrances"},
                                  "map the fort's entrances and what closes them", 0 if any_reach else 5))
        if not ent.get("scanned"):
            return
        # (0.100.1, review) an old map of the entrances still knows the gates:
        # they're watched and opened from it while the new scan waits
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    es = [e for e in _l(ent.get("entrances")) if isinstance(e, dict)]
    closable = [e for e in es if _l(e.get("equipment"))]
    if any_reach and closable and not ent.get("armed") and rules_["gate_lever"]:
        proposals.append(Proposal("gates", {"type": "arm_gates"},
                                  f"a threat can reach the dwarves: watch the {len(closable)} gate(s); each closes "
                                  "once everyone is inside or the danger is 12 tiles away", 0))
    elif not any_reach and ent.get("armed") and all_clear(s, memory, cfg)[0]:
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"no threat for {memory.quiet_cycles} cycles: open the gates", 1))
    werr = _d(ent.get("watch_error"))
    if ent.get("armed") and werr.get("error"):
        # (0.104.81, 13c) the gate watcher errors: it closes nothing
        notes.append(f"Needs you: the gate watcher failed {werr.get('n', 1)} time(s) and closes no gate "
                     f"({str(werr['error'])[:120]}); close the gates by hand while a threat is near")
    if stale:
        return                              # building gates waits for the new map
    _gate_parts_rule(s, ent, es, off, proposals, notes, memory)
    doors_proposed = fortify_proposed = False
    open_wide: list = []
    refused: list = []
    style = profile_from(traits or {}, memory.culture)["gate"]
    for e in es:
        if e.get("sealed") or e.get("closing"):
            continue                        # closed, or walls and doors planned there are being built
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if spot in memory.gate_failures:
            when = memory.gate_failure_ticks.get(spot)
            # refusals over a stockpile in the way are retried at once: the AI
            # moves stockpiles itself now
            if "move the stockpile" in memory.gate_failures[spot]:
                when = None
            # water refused before the AI could look at water itself (bridge
            # 0.34.2): tried again at once, so it investigates
            if "liquid" in memory.gate_failures[spot] and "the AI looked" not in memory.gate_failures[spot]:
                when = None
            if isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
                refused.append((where, memory.gate_failures[spot]))
                continue
            # refused long enough ago (or before refusals were dated): try again;
            # a new refusal is dated by record()

        lever = next((lv for lv in _free_gate_levers(s) if _lever_far_enough(lv, e)), None)
        if (lever and _l(e.get("bridges_unworked"))
                and not any(memory.gate_failures.get(f"lever:{lever['id']}>{bid}")
                            for bid in _l(e.get("bridges_unworked")))):
            continue                        # a drawbridge is there: the AI gate lever is linked to it instead
        for sp, v in list(memory.gates_fortified.items()):
            if str(v).startswith("water@"):
                try:
                    when = int(str(v)[6:])
                except ValueError:
                    when = None
                if when is None or not 0 <= now - when < cfg["water_gate_recheck_ticks"]:
                    del memory.gates_fortified[sp]    # a season on: look at the water again
        built_here = _near_spot(e, memory.gates_fortified, value=True)
        if built_here and not str(built_here).startswith("water"):
            # a gate the AI built, and the entrance still open with nothing
            # being built there: after a while the gate is gone (taken down,
            # destroyed) or never closed it. 0.40's hatch over the main stair
            # vanished and the fort stood open all of y51, the AI "waiting".
            sp_built = next((sp for sp in memory.gates_fortified if _near_spot(e, [sp])), None)
            since = memory.gates_fortified_ticks.get(sp_built)
            if not isinstance(since, int):
                memory.gates_fortified_ticks[sp_built] = now        # (a record from before 0.48: count from now)
            elif now - since >= cfg["gate_gone_ticks"]:
                memory.gates_fortified.pop(sp_built, None)
                memory.gates_fortified_ticks.pop(sp_built, None)
                if sp_built in memory.gate_doors_requested:
                    memory.gate_doors_requested.remove(sp_built)
                notes.append(f"the gate the AI built at {where} doesn't close it any more (gone?): building it again")
                built_here = False
        if built_here and not (e.get("door_spots") and "doors later" in str(built_here)):
            continue                        # walled: waiting on the dwarves, then the weekly rescan
                                            # (doors that had to wait for their walls go in once they stand)
        if e.get("door_spots"):
            if rules_["build_gate_doors"] and spot not in memory.gate_doors_requested and not doors_proposed:
                proposals.append(Proposal("gate_doors", {"type": "build_gate_doors", "entrance_id": e["id"]},
                                          f"{where} has nothing to close it: put {e['door_spots']} door(s) "
                                          "across it", 5))
                doors_proposed = True
        elif (rules_["fortify_entrances"] and (e.get("width") or 0) <= cfg["fortify_max_width"]):
            if not fortify_proposed:
                proposals.append(Proposal("fortify", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                      "style": style},
                                          f"{where} is {e.get('width')} wide: wall it down to a {style} gate", 5))
                fortify_proposed = True
        else:
            open_wide.append((e, where))
    if rules_["gate_lever"]:
        _lever_rule(s, memory, cfg, es, now, proposals)
    if not any_reach and rules_["fortify_entrances"]:
        _trap_rule(s, memory, cfg, es, now, traits or {}, proposals)
    if refused:
        def short_why(text: str, n: int = 140) -> str:
            text = str(text)
            return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."
        ask_player(notes, f"the game refused to build at {len(refused)} entrance(s), e.g. "
                          + "; ".join(f"{w}: {short_why(r)}" for w, r in refused[:2])
                          + ". Clear the spot or build there yourself; the AI tries again every 2 weeks")
    # Entrances doors can't close: one item for all of them (a big old fort
    # can have dozens), the widest named.
    if open_wide:
        open_wide.sort(key=lambda x: -(x[0].get("width") or 0))
        named = "; ".join(f"{w} ({e.get('width')} wide)" for e, w in open_wide[:3])
        surface = sum(1 for e, _ in open_wide if e.get("kind") == "surface")
        why = ("walling entrances down is off on the Rules tab" if not rules_["fortify_entrances"]
               else f"wider than {cfg['fortify_max_width']} tiles, too big for the AI to wall")
        ask_player(notes, f"{len(open_wide)} entrance(s) can't be closed with doors ({surface} to the surface, "
                          f"{len(open_wide) - surface} to the caverns or deeper; {why}), e.g. {named}: wall them "
                          "down to 3 tiles or less and the AI puts doors on them")


GATE_PART_RECIPES = {"hatch": ("hatch_covers", "stone_hatch_cover", "hatch cover"),
                     "door": ("doors", "stone_door", "door")}
GATE_PART_STUCK_DAYS = 7


def _gate_parts_rule(s: dict, ent: dict, es: list, off: int, proposals: list, notes: list, memory=None) -> None:
    """(0.104.105, overnight review) A hatch or door planned at an entrance is
    built only from one the fort has. The hatch over the main stair waited 15
    hours for a hatch cover nobody made; the entrance read "closing" all along,
    so nothing else was tried, and two titans walked in. Parts are ordered at
    the mason's when none is free; a gate still waiting a week with parts free
    is put to the player."""
    parts = _d(ent.get("parts"))
    want: dict = {}
    for e in es:
        if e.get("sealed") or not e.get("closing"):
            continue
        waiting = _d(e.get("waiting"))
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        for what, (field, recipe, word) in GATE_PART_RECIPES.items():
            n = waiting.get(what)
            if not isinstance(n, int) or n <= 0:
                continue
            free = parts.get(field)
            if not isinstance(free, int):
                continue                    # an older bridge: parts not counted
            if free == 0:
                w = want.setdefault(what, [0, where])
                w[0] += n
            elif isinstance(e.get("closing_days"), int) and e["closing_days"] >= GATE_PART_STUCK_DAYS:
                # (0.104.139) the "free" one may be one the game won't use (an
                # heirloom): one more is made all the same (once for each stuck
                # entrance: review), and you're told
                done_ = memory.gate_part_extra if isinstance(getattr(memory, "gate_part_extra", None), dict) else {}
                ek = f"{e.get('x')},{e.get('y')},{e.get('z')}|{what}"
                if ek not in done_:
                    w = want.setdefault(what, [0, where])
                    w[0] += n
                    w.append(ek)
                ask_player(notes, f"a {word} planned at {where} has waited {e['closing_days']} days though "
                                  f"{free} {word}(s) are free: one more is made; check its job isn't suspended "
                                  "or the spot blocked")
    for what, (n, where, *eks) in want.items():
        field, recipe, word = GATE_PART_RECIPES[what]
        held = parts.get(field + "_held") or 0
        need = min(4, n - held) if isinstance(held, int) else n
        need = max(need, 1) if (parts.get(field) or 0) > 0 else need    # (the stuck case above: one)
        if need > 0 and not queued(s, {recipe}):
            if eks and memory is not None:                 # (0.104.139) the extra one: remembered
                if not isinstance(getattr(memory, "gate_part_extra", None), dict):
                    memory.gate_part_extra = {}
                for ek in eks:
                    memory.gate_part_extra[ek] = abs_tick(s)
            proposals.append(Proposal("gate_parts", {"type": "work_order", "recipe": recipe, "amount": need},
                                      f"the {word} planned at {where} waits for a {word} the fort doesn't have: "
                                      f"a mason makes {need}", 3, is_order=True))


# (0.104.118, phase 11) Fight or hide. A great danger's strength: GREAT_BASE,
# and more for its size (a dwarf is about 60,000; a titan millions); by kind.
GREAT_BASE = 8.0
GREAT_KIND = {"Megabeast": 1.5, "Demon": 1.5, "Titan": 1.2, "ForgottenBeast": 1.3, "SemiMegabeast": 1.0,
              "Undead": 0.8}
# (0.104.139) what size doesn't say: a breath, deadly dust or webs (its
# caste's interactions) kills whole squads; a flier picks its fights
GREAT_ABILITY = 2.0
GREAT_FLIER = 1.5


def threat_power(t: dict) -> float:
    size = t.get("size") if isinstance(t.get("size"), (int, float)) and t.get("size") > 0 else 60000 * 25
    mult = max([GREAT_KIND.get(k, 1.0) for k in _l(t.get("kinds"))] or [1.0])
    if t.get("abilities"):
        mult *= GREAT_ABILITY
    if t.get("flier"):
        mult *= GREAT_FLIER
    return (GREAT_BASE + 2 * math.sqrt(size / 60000)) * mult


def fight_key(t: dict) -> str:
    kinds = [str(k) for k in _l(t.get("kinds"))]
    # (0.104.139) the kind that says most first (forgotten beasts were all "beast")
    for k in ("ForgottenBeast", "Titan", "Megabeast", "Demon", "SemiMegabeast", "Undead", "NightCreature"):
        if k in kinds:
            return k
    return kinds[0] if kinds else "beast"


def fight_or_hide(s: dict, memory, cfg: dict, great: list, able: list) -> tuple[bool, str]:
    """Squads' strength (the bridge's per-squad `power`) against the great
    dangers' (threat_power), times what the fort learned from its own fights
    of that kind (memory.fight_factor). Fight at fight_ratio or better."""
    army = sum(float(_d(q.get("power")).get("power") or 0) for q in able)
    if not army:
        return False, "the squads' strength isn't known (older bridge)" if able else "no squad to send"
    need = 0.0
    for t in great:
        f = float(_d(getattr(memory, "fight_factor", None)).get(fight_key(t)) or 1.0)
        need += threat_power(t) * f
    ratio = army / max(1.0, need)
    words = f"squads {army:.0f} against {need:.0f}"
    # (0.104.139) no flip-flop: a fight begun goes on unless the squads fall
    # well short (three quarters of the bar); hiding ends only clearly above it
    f = getattr(memory, "fight", None)
    on = (isinstance(f, dict) and f
          and 0 <= abs_tick(s) - int(f.get("tick") or 0) < cfg["fight_freeze_days"] * TICKS_PER_DAY)
    bar = cfg["fight_ratio"] * (0.75 if on else 1.0)
    return ratio >= bar, words


def _note_fight(s: dict, memory, great: list) -> None:
    """A fight against great dangers begins: what it was and how many soldiers went."""
    if isinstance(getattr(memory, "fight", None), dict) and memory.fight:
        return
    memory.fight = {"tick": abs_tick(s), "keys": sorted({fight_key(t) for t in great}),
                    "soldiers": int(_d(s.get("military")).get("soldiers") or 0)}


def _fight_outcome(s: dict, memory, cfg: dict) -> None:
    """The fight is over (no great danger in reach): lost a third of the
    soldiers or more -> that kind is taken as 50% stronger next time; fewer
    -> 10% weaker (between 0.5 and 4 times the estimate)."""
    f = getattr(memory, "fight", None)
    if not isinstance(f, dict) or not f or great_present(s):
        return
    now = int(_d(s.get("military")).get("soldiers") or 0)
    lost = max(0, int(f.get("soldiers") or 0) - now)
    bad = f.get("soldiers") and lost * 3 >= int(f["soldiers"])
    ff = memory.fight_factor if isinstance(getattr(memory, "fight_factor", None), dict) else {}
    for k in _l(f.get("keys")):
        ff[k] = round(min(4.0, max(0.5, float(ff.get(k) or 1.0) * (1.5 if bad else 0.9))), 2)
    memory.fight_factor = ff
    memory.fights = (list(getattr(memory, "fights", None) or []) +
                     [{"tick": abs_tick(s), "keys": f.get("keys"), "lost": lost, "of": f.get("soldiers")}])[-20:]
    memory.fight = {}


def _free_gate_lever(s: dict):
    """A lever the AI may link, while it's linked to nothing and has no job:
    one the AI placed for a drawbridge ("AI gate lever"), or the player's
    "AI gate" (bridge 0.35+ lists both; older ones: the player's only)."""
    free = _free_gate_levers(s)
    return free[0] if free else None


def _free_gate_levers(s: dict) -> list:
    free = [g for g in _l(_d(s.get("entrances")).get("free_levers")) if isinstance(g, dict) and "id" in g]
    if free:
        return free
    return [g for g in _l(_d(s.get("military")).get("gates"))
            if isinstance(g, dict) and not g.get("linked") and not g.get("pending") and "id" in g]


def _lever_far_enough(lever: dict, e: dict) -> bool:
    """Is the lever away from the entrance (20+ tiles or 4+ levels)? Unknown
    position (an older bridge): taken as yes."""
    lx, ly, lz = lever.get("x"), lever.get("y"), lever.get("z")
    if not all(isinstance(v, int) for v in (lx, ly, lz)):
        return True
    ex, ey, ez = e.get("x") or 0, e.get("y") or 0, e.get("z") or 0
    return abs(lz - ez) > 3 or max(abs(lx - ex), abs(ly - ey)) >= 20


def _link_wanted(s: dict, e: dict, lever_id=None) -> list:
    """Drawbridges at this entrance the AI gate lever should be linked to:
    ones no lever inside the fort works, and watched ones whose levers are
    all at the gate. [] with an older bridge (no lever details)."""
    out = [bid for bid in _l(e.get("bridges_unworked")) if isinstance(bid, int)]
    for b in _l(e.get("equipment")):
        if (isinstance(b, dict) and b.get("kind") == "bridge" and "lever_away" in b and not b["lever_away"]
                and not (lever_id is not None and lever_id in _l(b.get("levers")))):
            out.append(b.get("id"))
    return out


def _lever_rule(s: dict, memory, cfg: dict, es: list, now: int, proposals: list) -> None:
    """A drawbridge in an entrance that no lever inside works, or only levers
    at the gate: the lever named "AI gate", while it's linked to nothing (and
    is itself away from that gate), is linked to it, so a dwarf can close it
    from inside, away from the danger. Two free mechanisms are needed; if
    there aren't, they're ordered."""
    levers = _free_gate_levers(s)
    if not levers:
        return
    for e in es:
        # the first free lever away from this gate (another may suit another gate)
        lever = next((lv for lv in levers if _lever_far_enough(lv, e)), None)
        if not lever:
            continue
        for bid in _link_wanted(s, e, lever["id"]):
            key = f"lever:{lever['id']}>{bid}"
            why = memory.gate_failures.get(key)
            when = memory.gate_failure_ticks.get(key)
            short = why and "free mechanisms" in why
            wait = cfg["link_mechanisms_retry_ticks"] if short else cfg["gate_retry_ticks"]
            if why and "traceback" in why:
                wait = TICKS_PER_DAY            # a fault in the bridge, not the fort: try again tomorrow
            if why and isinstance(when, int) and 0 <= now - when < wait:
                if short:
                    proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                             "amount": 2},
                                              "2 mechanisms to link the AI gate lever to a drawbridge", 4,
                                              is_order=True))
                continue
            off = _d(s.get("map")).get("elevation_offset")
            elev = (e.get("z") or 0) + (off if isinstance(off, int) else 0)
            proposals.append(Proposal("gate_lever", {"type": "link_lever", "lever_id": lever["id"],
                                                     "target_id": bid},
                                      f"the drawbridge at the {e.get('kind')} entrance at elevation {elev} "
                                      f"(x{e.get('x')} y{e.get('y')}) has no lever a dwarf can pull from "
                                      "inside, away from the gate: link the AI gate lever to it", 4))
            return


def _trap_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list) -> None:
    """Traps behind each gate that has none, in the fort's trap style (the
    Traps area: none, cage, stone-fall or weapon traps), as many as
    Fortification, Engineering and Caution call for. One gate a cycle, never
    while a threat can reach the dwarves; mechanisms ordered if too few."""
    import defence
    kind = profile_from(traits, memory.culture)["traps"]
    if kind == "none":
        return
    reg = _d(_d(memory.atlas).get("registry"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    for e in es:
        if not e.get("sealed") or not any(isinstance(b, dict) and b.get("kind") in ("door", "bridge")
                                          for b in _l(e.get("equipment"))):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        # (records are filed under the tile the scan named then, which moves a
        # little as walls go up: near, 3 tiles on the same level, counts)
        traps_near = {k[6:]: v for k, v in reg.items() if k.startswith("traps:")}
        gates_near = {k[5:]: v for k, v in reg.items() if k.startswith("gate:")}
        if _near_spot(e, traps_near) or str(_d(_near_spot(e, gates_near, value=True)).get("variant")) == "gatehouse":
            continue                            # (a gatehouse has its cage traps already)
        why, when = memory.gate_failures.get("traps:" + spot), memory.gate_failure_ticks.get("traps:" + spot)
        if why and isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
            continue
        n = defence.trap_count(traits)
        from quirks import has_rule
        if has_rule(memory.culture, "more_traps"):
            n = min(10, n + 2)                     # (Trapsmiths)
        if has_rule(memory.culture, "harden_after_siege"):
            # (0.103.1, Grudge-keepers: the rule had no effect) a trap more for each siege survived
            n = min(12, n + min(4, int(_d(memory.culture).get("sieges") or 0)))
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        proposals.append(Proposal("traps", {"type": "place_traps", "entrance_id": e["id"], "kind": kind, "count": n},
                                  f"{where} has a gate but no traps: {n} {kind} trap(s) just inside it", 6))
        free = _d(s.get("entrances")).get("free_mechanisms")
        if isinstance(free, int) and free < n:
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": n - free},
                                      f"{n - free} mechanisms for the traps at {where}", 6, is_order=True))
        return


def _near_spot(e: dict, spots, value: bool = False):
    """Is this entrance where the AI already built? Walls move an entrance's
    first tile to its gap, so near (3 tiles, same level) counts. value: give
    back what's stored there (spots is a dict) instead of True."""
    for sp in spots:
        try:
            x, y, z = (int(v) for v in str(sp).split(","))
        except ValueError:
            continue
        exact = x == e.get("x") and y == e.get("y") and z == e.get("z")
        if isinstance(spots, dict) and str(spots[sp]).startswith("water"):
            # nothing was built for a water gate, so the map didn't move: that
            # spot only (a real opening 3 tiles away is another entrance)
            if not exact:
                continue
        if z == e.get("z") and abs(x - (e.get("x") or 0)) <= 3 and abs(y - (e.get("y") or 0)) <= 3:
            return (spots[sp] if isinstance(spots, dict) and spots[sp] else True) if value else True
    return False


def soldiers_wanted(s: dict, citizens: int, cfg: dict, idle: bool = False) -> int:
    """From the Militarism trait; more when many dwarves long to fight or
    train (the Fight / MartialTraining needs: soldiering meets them), unless
    Militarism is at its lowest."""
    base = round(citizens * soldier_share(s, cfg))
    # (0.100.1, review) a handful of dwarves keep to their work: no soldiers
    # below SQUAD_MIN_CITIZENS unless a threat can reach them (the alert and
    # the soldiers rule raise one then); on day one of an embark a militia
    # commander took the woodcutter's axe
    if citizens < cfg["squad_min_citizens"] and not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return 0
    fighters = max(unmet(s, "Fight"), unmet(s, "MartialTraining"))
    traits = _d(_d(s.get("settings")).get("traits"))
    # (0.103.9) a small fort too, by its share: Enxah's 28 had 23 distracted
    # for want of training (the line was 15 of 30+ citizens) and 10 miserable
    need_at = min(cfg["fight_needs_at"], max(4, math.ceil(citizens * cfg["fight_needs_share"])))
    if fighters >= need_at and traits.get("militarism", 0) > -100 and citizens >= cfg["fight_min_citizens"]:
        # (0.104.61) a quarter of the fort badly wanting to train or fight: the
        # wider idle-hands caps (Enxah, winter y74: MartialTraining 30 of 93
        # badly with 25 soldiers, all on constant training; the 30% cap held)
        nd = _d(_d(s.get("needs")).get("needs"))
        badly = max(int(_d(nd.get("MartialTraining")).get("badly") or 0), int(_d(nd.get("Fight")).get("badly") or 0))
        if badly >= citizens * cfg["fight_badly_share"]:
            idle = True
        if idle:
            # (0.83) many idle hands: training costs no work, and it meets
            # Fight, MartialTraining and LearnSomething (a skill rank) at once
            idle = int(_d(s.get("dwarves")).get("idle_adults") or 0)
            extra = min(fighters // 2, max(cfg["fight_soldiers_max"], idle), cfg["idle_fight_soldiers_max"])
            return min(base + extra, max(base, round(citizens * cfg["idle_fight_share_max"])))
        extra = min(fighters // 2, cfg["fight_soldiers_max"])
        return min(base + extra, max(base, round(citizens * cfg["fight_share_max"])))
    return base


def crossing_value(side: dict) -> float:
    """(0.101) What land is worth to the fort, from the crossings survey:
    trees (wood), shrubs and saplings (food, drink, seeds, future trees),
    grass (pasture), and the map's edge (where caravans and migrants come in)."""
    side = _d(side)
    return (2 * (side.get("trees") or 0) + (side.get("shrubs") or 0) + 0.5 * (side.get("saplings") or 0)
            + (side.get("grass") or 0) / 20 + (40 if side.get("edge") else 0))


def _crossing_rule(s: dict, cfg: dict, citizens: int, traits: dict, proposals: list, notes: list,
                   memory=None) -> None:
    """(0.101) Water on the surface cutting the fort off from land it would
    use (the second overnight embark lay in a river's bend). The AI weighs
    each side from the survey and decides: a cheap one-tile bridge early when
    the far side is worth the walk; a wider one once the fort is established
    (Grandeur widens it; at -50 or lower the cheap one stays); the cheap one
    taken down once the new one stands. Only the AI's own bridges."""
    c = _d(s.get("crossings"))
    if c.get("none") or c.get("error"):
        return
    cands = [x for x in _l(c.get("crossings")) if isinstance(x, dict) and x.get("len")]
    mine = [m for m in _l(c.get("mine")) if isinstance(m, dict)]
    near_v = crossing_value(c.get("near"))
    st = _d(s.get("stocks"))
    material = int(st.get("wood") or 0) + int(st.get("blocks") or 0) + int(st.get("boulders") or 0)
    def score(x):
        return crossing_value(x.get("far_side")) - 2 * x["len"] - (x.get("dist") or 0) / 20
    # the old cheap bridge comes down once a refined one stands
    refined_up = [m for m in mine if m.get("kind") == "refined" and m.get("built")]
    if refined_up:
        for m in mine:
            if m.get("kind") == "cheap" and m.get("index"):
                proposals.append(Proposal("crossing", {"type": "remove_crossing", "index": m["index"]},
                                          "the new, wider bridge stands: take down the old narrow one", 7))
                return
    if not cands:
        return
    # the nearest crossing whose far side is worth it (each side's count is
    # capped, so on open land the far sides look alike: the walk decides);
    # with none worth it, the best one is weighed below and found wanting
    worthy = [x for x in cands if crossing_value(x.get("far_side")) >= cfg["crossing_min_value"]]
    best = (min(worthy, key=lambda x: 2 * x["len"] + (x.get("dist") or 0) / 5) if worthy
            else max(cands, key=score))
    far = _d(best.get("far_side"))
    far_v = crossing_value(far)
    where = f"x{best.get('x')} y{best.get('y')}"
    what = (f"{far.get('trees', 0)} trees, {far.get('shrubs', 0)} shrubs, {far.get('grass', 0)} grass"
            + (", the map's edge" if far.get("edge") else ""))
    if not mine:
        near = _d(c.get("near"))
        worth = far_v >= cfg["crossing_min_value"] and (
            far_v >= near_v * cfg["crossing_far_share"]
            or (near.get("trees") or 0) < citizens
            or (far.get("edge") and not near.get("edge")))
        if not worth:
            return
        if material < best["len"]:
            notes.append(f"a bridge over the water at {where} waits for {best['len']} logs, blocks or boulders")
            return
        proposals.append(Proposal("crossing", {"type": "build_crossing", "x": best["x"], "y": best["y"],
                                               "z": best.get("z"), "dir": best.get("dir"), "len": best["len"],
                                               "width": 1, "kind": "cheap"},
                                  f"water cuts the fort off from land worth reaching ({what} over there, "
                                  f"{best['len']} tiles across at {where}): a narrow bridge for now", 6))
        return
    if any(m.get("kind") == "refined" for m in mine) or traits.get("grandeur", 0) <= -50:
        return
    wealth = s.get("wealth") if isinstance(s.get("wealth"), (int, float)) else 0
    # (0.103) Riverfolk bridge their river properly at half the size and wealth
    river = 0.5 if memory is not None and has_rule(memory.culture, "river_bridges") else 1.0
    if (citizens < cfg["crossing_refine_citizens"] * river or wealth < cfg["crossing_refine_wealth"] * river
            or (young_fort(s, cfg) and river == 1.0)):
        return
    want = 3 if traits.get("grandeur", 0) >= 50 else 2
    wide = [x for x in cands if (x.get("width") or 1) >= 2]
    if not wide:
        return
    pick = min(wide, key=lambda x: 2 * x["len"] + (x.get("dist") or 0) / 5)
    width = min(want, pick.get("width") or 1)
    if material < pick["len"] * width:
        return
    proposals.append(Proposal("crossing", {"type": "build_crossing", "x": pick["x"], "y": pick["y"],
                                           "z": pick.get("z"), "dir": pick.get("dir"), "len": pick["len"],
                                           "width": width, "kind": "refined"},
                              f"the fort has grown ({citizens} dwarves): a {width}-wide bridge over the water at "
                              f"x{pick.get('x')} y{pick.get('y')} in place of the narrow one", 7))


# (0.88) The alert icons: kept for the player while new, the dangers longer
ALERT_DANGERS = ("AMBUSH", "MONSTER", "UNDEAD_ATTACK", "BERSERK", "GHOST", "DEITY_CURSE", "DEATH", "MARTIAL_TRANCE")


def alert_ages(s: dict, cfg: dict, policy: str) -> dict | None:
    """The age (ticks) at which each kind of alert icon is cleared, or None to
    leave them all. 'all': every kind once a day old; 'quiet' (the default):
    the dangers kept a week, and while a threat can reach the dwarves; 'none'."""
    if policy == "none":
        return None
    day = TICKS_PER_DAY
    ages = {"default": int(cfg["alert_keep_days"] * day)}
    if policy == "all":
        return ages
    danger_age = int(cfg["alert_danger_days"] * day)
    for t in ALERT_DANGERS:
        ages[t] = danger_age
    if reachable_threats(s, _traits(s), cfg):
        for t in ("AMBUSH", "MONSTER", "UNDEAD_ATTACK", "BERSERK", "COMBAT"):
            ages[t] = False
    return ages


def _alerts_rule(s: dict, memory, cfg: dict, proposals: list, rules_: dict) -> None:
    """(0.88) The alert icons down the left of the screen pile up (you, Oct
    23: mining, weather, death, combat, nobles...): the AI reads every
    announcement itself, so it clears the old ones, the way right-clicking an
    icon does. The first time only one, as a probe."""
    al = _d(s.get("alerts"))
    by = _d(al.get("by_type"))
    if not by or al.get("open"):
        return
    ages = alert_ages(s, cfg, rules_.get("clear_alerts", "quiet"))
    if not ages:
        return
    due = []
    for t, e in by.items():
        need = ages.get(t, ages.get("default"))
        age = _d(e).get("age")
        if need is not False and need is not None and (age is None or int(age) >= int(need)):
            due.append(t)
    if not due:
        return
    # the first one alone: a probe that the game takes it (nothing done yet)
    done = any(str(k).startswith("alerts:") and v for k, v in (getattr(memory, "action_log", None) or {}).items())
    proposals.append(Proposal("alerts", {"type": "dismiss_alerts", "ages": ages,
                                         "max": cfg["alerts_per_cycle"] if done else 1},
                              f"{len(due)} old alert icon(s) on the screen ({', '.join(sorted(due)[:5]).lower()}"
                              f"{'...' if len(due) > 5 else ''}): the AI has read them; clear them", 8))


def _war_animal_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(0.104.81) War animals: the tame dogs and the like trained for war
    (DF's trainers do it once an animal has a training assignment), up to
    `war_animals_max`; a dwarf given the animal-training labour first when
    nobody has it."""
    if young_fort(s, cfg):
        return
    an = _d(_d(s.get("society")).get("animals"))
    if an.get("error") or not an:
        return
    have = int(an.get("war_trained") or 0) + int(an.get("in_training") or 0)
    cands = int(an.get("war_candidates") or 0)
    if cands <= 0 or have >= cfg["war_animals_max"]:
        return
    if int(an.get("trainers") or 0) == 0:
        proposals.append(Proposal("animal_trainer", {"type": "assign_labor", "job": "ANIMALTRAIN", "count": 1},
                                  f"{cands} tame animals could be trained for war and nobody may train animals: "
                                  "give one dwarf the labour", 6))
        return
    n = min(3, cfg["war_animals_max"] - have, cands)
    proposals.append(Proposal("war_animals", {"type": "train_war", "max": n},
                              f"{have} war animals (trained or in training) of {cfg['war_animals_max']} wanted, "
                              f"{cands} could be trained: put {n} to war training (they fight beside the dwarves)", 6))


def hazard_alert(s: dict, cfg: dict) -> str:
    """Why the civilian alert should stay up for a hazard ("" if none): fire
    or a cloud close to the dwarves, a citizen gone berserk."""
    h = _d(s.get("hazards"))
    if h.get("fire_near") is not None and h["fire_near"] <= cfg["hazard_near"]:
        return f"fire {h['fire_near']} tiles from the dwarves"
    if h.get("cloud_near") is not None and h["cloud_near"] <= cfg["hazard_near"]:
        return f"a cloud (gas or vapour) {h['cloud_near']} tiles from the dwarves"
    if _l(h.get("berserk")):
        b0 = _l(h['berserk'])[0]
        return f"{b0.get('name') or 'a dwarf'} " + ("has changed into a beast" if b0.get("changed") else "has gone berserk")
    return ""


def _hazard_rules(s: dict, memory, cfg: dict, proposals: list, notes: list, rules_: dict) -> None:
    """Phase 11, reflexes for hazards that aren't enemies (lua/ai-bridge.lua
    get_hazards): the civilian alert for fire, clouds and a berserk citizen,
    the squads sent at the berserk one; dwarves in deep water or magma
    (flooding: the cistern's floodgate shut); vampires sent away (Rules tab);
    caught invaders noted."""
    h = _d(s.get("hazards"))
    why = hazard_alert(s, cfg)
    if why and not s.get("civ_alert"):
        if s.get("civ_alert_ready") is True:
            proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                      f"{why}: sound the alarm (the civilians go to the shelter)", 0))
        else:
            ask_player(notes, f"{why}, and no civilian-alert burrow is set up to keep the others safe")
    berserk = [b for b in _l(h.get("berserk")) if isinstance(b, dict) and b.get("id") is not None]
    mil = _d(s.get("military"))
    if berserk:
        able = [q for q in _l(mil.get("squads")) if isinstance(q, dict)
                and (q.get("members") or 0) >= cfg["min_squad_to_fight"] and not q.get("ai_orders")]
        names = ", ".join(str(b.get("name")) + (" (changed into a beast)" if b.get("changed") else "")
                          for b in berserk[:3])
        if able:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": able[0]["id"],
                                                       "kill": [b["id"] for b in berserk][:10]},
                                      f"{names} gone berserk and attacking others: send {able[0].get('name') or 'the squad'}", 0))
        else:
            ask_player(notes, f"{names} gone berserk, and no squad to stop them: keep the others away")
    wet, burning = _l(h.get("wet")), _l(h.get("burning"))
    if burning:
        ask_player(notes, f"{len(burning)} dwarf(s) in magma: " + ", ".join(str(b.get("name")) for b in burning[:3]))
    if len(wet) >= cfg["flood_wet_dwarves"]:
        cs = _d(_d(s.get("water")).get("cistern_status"))
        if cs.get("gate") == "open":
            proposals.append(Proposal("flood", {"type": "cistern_step", "shut": True},
                                      f"{len(wet)} dwarves stand in deep water: shut the cistern's floodgate", 0))
        ask_player(notes, f"{len(wet)} dwarves stand in deep water (a flood?): "
                   + ", ".join(str(b.get("name")) for b in wet[:3]))
    for c in [c for c in _l(_d(s.get("deep")).get("cursed")) if isinstance(c, dict)]:
        if c.get("kind") == "vampire" and rules_.get("expel_vampires", True) and c.get("id") is not None:
            proposals.append(Proposal("cursed", {"type": "expel_dwarf", "unit_id": c["id"]},
                                      f"{c.get('name')} is a vampire (drinks sleeping dwarves' blood): send them away", 1))
    if (h.get("caged") or 0) > 0:
        notes.append(f"{h['caged']} invader(s) caught in cages: they stay caged (what to do with prisoners "
                     "is a decision for the AI agent; for now they are kept)")
    # cage traps re-armed: full cages need an animal stockpile to go to, and
    # empty cages to take their place
    full = int(h.get("cage_traps_full") or 0)
    if full:
        if not h.get("animal_piles") and not _d(_d(s.get("buildings")).get("clearing")).get("cages"):
            proposals.append(Proposal("cages", {"type": "place_surface", "kind": "cages"},
                                      f"{full} cage trap(s) hold a catch and there's no stockpile for full cages: "
                                      "make one, so the traps can be loaded again", 4))
        if int(h.get("free_cages") or 0) < full and not queued(s, {"wooden_cage"}):
            proposals.append(Proposal("cages", {"type": "work_order", "recipe": "wooden_cage", "amount": full},
                                      f"{full} cage trap(s) to load again and {h.get('free_cages') or 0} empty "
                                      "cages: make more", 4, True))
    if (h.get("miasma") or 0) >= cfg["miasma_note"]:
        notes.append(f"miasma in {h['miasma']} places: rot lying indoors (a refuse pile outside takes it)")


def _military_rules(s: dict, memory, cfg: dict, traits: dict, citizens: int,
                    proposals: list, notes: list) -> None:
    mil, rules_ = s["military"], player_rules(s)
    squads = [q for q in _l(mil.get("squads")) if isinstance(q, dict)]
    threats = {t.get("id"): t for t in _l(s["others_on_map"].get("threats")) if isinstance(t, dict)}
    reach = [i for i in reachable_threats(s, traits, cfg) if i in threats]
    any_reach = bool(reachable_threats(s, traits, cfg))

    # The gate: a lever the player named "AI gate". Pulled when a threat can
    # reach the dwarves, pulled back once it has been quiet for a while.
    # The fort's own entrances: found, closed and opened by the AI itself.
    # (0.97) mapping, walls, doors and traps run whatever gate_lever says (each
    # has its own switch); gate_lever is only closing gates and their levers
    if "entrances" in s and "entrances" not in s["_errors"]:
        _gate_rules(s, memory, cfg, rules_, any_reach, proposals, notes, traits)
    # A lever the player named "AI gate" and linked to something: pulled too.
    gates = [g for g in _l(mil.get("gates")) if isinstance(g, dict) and not g.get("pending") and g.get("linked")]
    # (one linked to an entrance's drawbridge is the gate watcher's to pull)
    watched = {lid for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)
               for b in _l(e.get("equipment")) if isinstance(b, dict) for lid in _l(b.get("levers"))}
    gates = [g for g in gates if g.get("id") not in watched]
    if rules_["gate_lever"] and gates:
        if any_reach and not memory.gate_closed_by_ai:
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      "a threat can reach the dwarves: pull the AI gate lever", 0))
        elif (not any_reach and memory.gate_closed_by_ai and gates
              and all_clear(s, memory, cfg)[0]):
            proposals.append(Proposal("gate", {"type": "pull_gate", "lever_id": gates[0]["id"]},
                                      f"no threat for {memory.quiet_cycles} cycles: pull the AI gate "
                                      "lever back", 1))

    # Squads at threats: kill orders the AI gives, and clears again.
    able = [q for q in squads if (q.get("members") or 0) >= cfg["min_squad_to_fight"]]
    policy = rules_["attack_policy"]
    great = [i for i in reach if threats[i].get("great_danger")]
    # (0.104.118, phase 11) a great danger is fought when the squads are
    # strong enough for it (judged), else the dwarves hide behind shut gates
    fight, verdict = fight_or_hide(s, memory, cfg, [threats[i] for i in great], able) if great else (False, "")
    targets = [i for i in reach if policy == "all" or (policy == "ordinary" and (not threats[i].get("great_danger")
                                                                                 or fight))]
    held_back = [i for i in reach if i not in targets]
    if great and fight and policy == "ordinary":
        # (0.104.139) recorded even when the squads were already out at others
        _note_fight(s, memory, [threats[i] for i in great])
    if targets:
        for q in able:
            names = ", ".join(sorted({str(threats[i].get("name") or "?") for i in targets}))[:80]
            if not q.get("ai_orders"):
                proposals.append(Proposal(
                    "squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": targets[:50]},
                    f"{len(targets)} enemies can reach the dwarves ({names}): send {q.get('name') or 'the squad'}", 0))
            elif not q.get("guarding") and isinstance(q.get("kill_ids"), list):
                # (0.104.140) a second wave: enemies in reach the squad's kill
                # order doesn't name (the order was a list made when it went out)
                known = {int(x) for x in q["kill_ids"] if isinstance(x, int)}
                new = [i for i in targets if isinstance(i, int) and i not in known]
                if new:
                    proposals.append(Proposal(
                        "squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": targets[:50]},
                        f"{len(new)} more enemies can reach the dwarves ({names}): "
                        f"{q.get('name') or 'the squad'} goes after them too", 0))
        if not able:
            ask_player(notes, f"{len(targets)} enemies can reach the dwarves and no squad has "
                         f"{cfg['min_squad_to_fight']}+ soldiers to send")
    if held_back and policy != "never":
        notes.append(f"{len(held_back)} great danger(s) (beast, titan...) can reach the dwarves: the dwarves hide "
                     f"behind the gates ({verdict}; Rules tab: attack everything)")
    elif great and fight:
        notes.append(f"{len(great)} great danger(s) can reach the dwarves: the squads go ({verdict})")
    _fight_outcome(s, memory, cfg)
    # (0.104.140) after an attack, once all is clear: the enemies' corpses at
    # the gate rot away now (miasma, a necromancer's fuel), not at the year's end
    lt = int(getattr(memory, "last_threat_tick", 0) or 0)
    if (lt and not any_reach and getattr(memory, "pruned_after", 0) != lt
            and all_clear(s, memory, cfg)[0]):
        proposals.append(Proposal("siege_cleanup", {"type": "prune_remains"},
                                  "the attack is over: the enemies' corpses and remains lying about rot away "
                                  "(entombed dead are kept)", 5))
    # (0.100.1, review) a dwarf gone berserk isn't a threat that "can reach",
    # but the squad sent at them stays on them until they're stopped
    berserk_now = bool(_l(_d(s.get("hazards")).get("berserk")))
    if not any_reach and not berserk_now:
        invaders_near = bool(gate_invaders(s))
        for q in squads:
            if q.get("guarding") and invaders_near:
                continue                     # (0.104.83) holding the gate while invaders are about
            if q.get("ai_orders"):
                proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                          f"no more threats: call {q.get('name') or 'the squad'} back", 1))

    # Training: a squad with soldiers sitting off duty.
    routines = [r for r in _l(mil.get("routines")) if isinstance(r, str)]
    train_to = next((r for r in routines if "staggered" in r.lower()), None) or \
        next((r for r in routines if "training" in r.lower()), None)
    small = citizens < cfg["train_min_citizens"]
    off = next((r for r in routines if "off duty" in r.lower()), None)
    if rules_["train_squads"] and not any_reach and small and off:
        # A small fort needs every pair of hands: a squad the AI put on
        # training goes back to work until the fort has grown (yours stay)
        for q in squads:
            if (q["id"] in memory.squads_trained and q["id"] not in memory.squads_rested
                    and not q.get("ai_orders") and "off duty" not in str(q.get("routine") or "").lower()):
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": off},
                                          f"{q.get('name') or 'a squad'}: only {citizens} dwarves, every pair of "
                                          f"hands is needed: off duty until the fort has {cfg['train_min_citizens']}", 4))
    rotating = set()
    # (0.83) with many idle hands every squad trains: the rotation exists to
    # keep hands at work, and they would sit idle anyway
    many_idle = idle_hands(s, memory, cfg)
    if (rules_["train_squads"] and not any_reach and train_to and off and not small and not many_idle
            and traits.get("militarism", 0) < cfg["train_rotate_below_militarism"]):
        # (0.100) the rotation trains on "Constant training": "Staggered" has
        # DF's own 3-month blocks, which fought the monthly turns (uniforms off and on)
        rotate_to = next((r for r in routines if "constant" in r.lower() and "training" in r.lower()), None)
        rotating = _training_rotation(s, memory, squads, rotate_to or train_to, off, cfg, proposals)
    # (0.104.59) while many badly want to train, "Staggered training" (DF's own
    # months off) isn't enough: the AI's squads go on constant training
    # (Enxah, summer y74: MartialTraining 31 badly, Fight 24, squads 26 and 46
    # staggered while the idle-hands path skipped the rotation)
    constant = next((r for r in routines if "constant" in r.lower() and "training" in r.lower()), None)
    cit_n = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    mt_badly = int(_d(_d(_d(s.get("needs")).get("needs")).get("MartialTraining")).get("badly") or 0)
    train_all = mt_badly >= max(5, cit_n * cfg["train_all_share"])
    if train_all and constant:
        train_to = constant
    staggered = next((r for r in routines if "staggered" in r.lower()), None)
    keen_n = int(_d(s.get("needs")).get("keen_civilians") or 0)
    starved = [x for x in _l(_d(s.get("needs")).get("starved_soldiers")) if isinstance(x, dict)]
    if rules_["train_squads"] and not any_reach and train_to and traits.get("militarism", 0) > -50 and not small:
        # the AI's squads: trained or made by it, or wearing a uniform it set
        # (Enxah's 26 and 46 wear the AI's uniform; its memory of training
        # them was lost on a reload)
        ai_squads = (set(memory.squads_trained) | set(getattr(memory, "squads_made", None) or [])
                     | {q.get("id") for q in squads if q.get("ai_uniform")})
        for q in squads:
            if q.get("id") in rotating:
                continue
            if (q.get("members") or 0) > 0 and "off duty" in str(q.get("routine") or "").lower():
                if q["id"] in memory.squads_trained and q["id"] not in memory.squads_rested:
                    continue          # the AI trained it before and you sent it off duty: your call
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": train_to},
                                          f"{q.get('name') or 'a squad'} sits off duty: put it on {train_to.lower()}", 4))
            elif (train_all and constant and (q.get("members") or 0) > 0 and q.get("id") in ai_squads
                  and not q.get("ai_orders") and "staggered" in str(q.get("routine") or "").lower()):
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": constant},
                                          f"{mt_badly} dwarves badly want to train: {q.get('name') or 'a squad'} "
                                          f"goes from staggered to {constant.lower()}", 4))
            elif (not train_all and staggered and (q.get("members") or 0) > 0 and q.get("id") in ai_squads
                  and not q.get("ai_orders") and "constant" in str(q.get("routine") or "").lower()
                  and keen_n < cfg["soldier_swap_keen_min"] and len(starved) >= cfg["staggered_starved_min"]
                  and traits.get("militarism", 0) < cfg["train_rotate_below_militarism"]):
                # (0.104.72) the training wanted is met, the civilians' too, and
                # the soldiers miss everything else: DF's staggered months off
                proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": q["id"], "routine": staggered},
                                          f"training is met and {len(starved)} soldiers badly miss other things: "
                                          f"{q.get('name') or 'a squad'} goes to {staggered.lower()} (months off by turns)", 5))

    # Gear: weapons, body armour, helms for every soldier, made at a forge in
    # the best metal there are bars for. Only with a uniform set: without one
    # the game doesn't hand the gear out.
    gear = _d(mil.get("gear"))
    # judged on soldiers on duty (off duty they put weapons away); an older
    # bridge without the on-duty count: all soldiers
    soldiers = gear.get("on_duty") if "on_duty" in gear else (gear.get("soldiers") or 0)
    soldiers = soldiers or 0
    just_trained = (memory.last_train_tick is not None
                    and 0 <= abs_tick(s) - memory.last_train_tick < cfg["gear_wait_ticks"])
    if rules_["make_gear"] and soldiers and "error" not in gear and not just_trained:
        spare, bars = _d(gear.get("spare")), _d(gear.get("bars"))
        wants = [("weapons", "armed", GEAR_WEAPONS[rules_["gear_weapon"]], "weapons"),
                 ("body", "armored", "metal_mail_shirt", "body armour"),
                 ("helms", "helmed", "metal_helm", "helms")]
        # the rest of a kit, once a squad wears the metal uniform (a leather one
        # takes none of it) and the bridge counts it (0.61)
        if "legged" in gear and any("metal" in str(q.get("ai_uniform") or "").lower() for q in squads):
            wants += [("shields", "shielded", "metal_shield", "shields"),
                      ("pants", "legged", "metal_greaves", "greaves"),
                      ("boots", "booted", "metal_high_boots", "metal boots"),
                      ("gloves", "gloved", "metal_gauntlets", "gauntlets")]
        # a soldier holding a miner's pick isn't armed for this: the pick goes
        # back once the uniform asks for the AI's weapon (_uniform_weapon_rule)
        picks = int(_d(s.get("labor")).get("soldier_picks") or 0)
        held = {"armed": max(0, (gear.get("armed") or 0) - picks - int(gear.get("ranged_armed") or 0))}
        # (0.104.60) a melee weapon given to a soldier's place counts, fetched or
        # not (the AI hands them out itself; more aren't made meanwhile)
        if isinstance(gear.get("melee_given"), int):
            held["armed"] = max(held["armed"], int(gear["melee_given"]))
        # crossbow soldiers aren't counted for melee weapons (_ranged_squad_rule arms them)
        ranged_n = sum(int(q.get("members") or 0) for q in squads if is_ranged(q))
        if isinstance(gear.get("spare_weapons"), dict):
            # only the AI's own weapon counts as spare (others may not suit the uniform)
            spare = dict(spare, weapons=int(gear["spare_weapons"].get(WEAPON_IDS.get(rules_["gear_weapon"])) or 0))
        # boots and gauntlets come and are worn in pairs: two spares a soldier
        pairs = {"boots", "gloves"}
        short = [(k, r, w, (soldiers - ranged_n if k == "weapons" else soldiers) - held.get(h, gear.get(h) or 0)
                  - ((spare.get(k) or 0) // (2 if k in pairs else 1)) - queued(s, {r}))
                 for k, h, r, w in wants]
        short = [x for x in short if x[3] > 0]
        # Spares lying unused: soldiers aren't picking them up (often a uniform
        # that asks for something else), so more would only be wasted metal.
        waiting = [x for x in short
                   if (spare.get(x[0]) or 0) // (2 if x[0] in pairs else 1) >= cfg["gear_spare_stop"]]
        # (0.104.138) twice with nothing changed: it doesn't help here (456 runs
        # in two days, every result "0 replaced", the spares the same)
        seen = memory.unstick_seen if isinstance(memory.unstick_seen, dict) else {}
        same = seen.get("sig") == spare_sig(gear) and int(seen.get("n") or 0) >= 2
        if waiting and same:
            notes.append("untangling the uniforms twice changed nothing: left until the spare gear changes")
        if waiting and not same and int(gear.get("on_duty") or 0) > 0:
            # (0.99.7) region2: each soldier had 17-19 items assigned for a
            # 9-item uniform, 31 of them in other dwarves' hands, and nobody
            # picked anything up. DFHack's uniform-unstick frees them.
            proposals.append(Proposal("unstick_uniforms", {"type": "unstick_uniforms"},
                                      f"{len(waiting)} kind(s) of gear lie spare while the soldiers on duty go "
                                      "without: untangle the uniforms' assignments (DFHack uniform-unstick)", 4))
        # (0.104.58) gear the game lost track of (assigned to a dead soldier's
        # place, or on no list): never handed out until it's put back (Enxah:
        # a battle axe on the ground assigned to no one, 7 of 26 armed)
        stray = _d(gear.get("stray"))
        # what the bridge moves: anything assigned to no one, weapons on no list
        movable = {k: v for k, v in _d(stray.get("orphan")).items()}
        if _d(stray.get("unlisted")).get("WEAPON"):
            movable["WEAPON"] = int(movable.get("WEAPON") or 0) + int(stray["unlisted"]["WEAPON"])
        if movable and int(gear.get("on_duty") or 0) > 0:
            kinds = sorted(movable)
            proposals.append(Proposal("stray_gear", {"type": "free_stray_gear", "limit": 100},
                                      f"{sum(int(v or 0) for v in movable.values())} piece(s) of gear "
                                      f"({', '.join(k.lower() for k in kinds)}) "
                                      "the game assigns to no soldier and never hands out: put them back "
                                      "on its list so the soldiers get them", 3))
        # (0.104.60) DF leaves the weapon entry of a uniform empty while free
        # weapons of its kind lie about (Enxah: 19 melee places "given 0", 19
        # spare battle axes, the armour handed out): after a week of that, the
        # AI puts them on the soldiers' places itself
        since = memory.gear_spare_since.get("weapon_gaps")
        if (_weapon_gaps(gear) and isinstance(since, int)
                and abs_tick(s) - since >= cfg["assign_weapons_wait_ticks"]):
            proposals.append(Proposal("assign_weapons", {"type": "assign_weapons", "limit": 10},
                                      f"{int(gear['weapon_gaps'])} soldier place(s) the game gives no weapon "
                                      "though free ones lie about: hand them out to the soldiers", 3))
        released = []
        for k, _r, what, _n in waiting:
            since = memory.gear_spare_since.get(k)
            # (0.104.57) weapons that lie unused a month aren't the uniform's
            # (Enxah: 3 battle axes reachable, none ever assigned, 7 of 26
            # soldiers armed): new ones are made all the same
            # (0.104.138) armour and helms too: Teacheroar's 5 body armour and 4
            # helms lay unused 6,600 days (loose on floors, never handed out)
            # while ~20 soldiers went without, and none was made again
            if (k in ("weapons", "body", "helms") and isinstance(since, int)
                    and abs_tick(s) - since >= cfg["gear_weapons_anyway_ticks"]):
                released.append(k)
                notes.append(f"{spare.get(k)} spare {what} lie unused for a month: making new ones anyway")
                continue
            if isinstance(since, int) and abs_tick(s) - since >= cfg["gear_unused_ticks"]:
                ask_player(notes, f"{spare.get(k)} {what} lie unused while soldiers go without: check the squads' "
                           f"uniforms (they may ask for something other than what the AI makes: "
                           f"{rules_['gear_weapon']}s for weapons, set on the Rules tab)")
            else:
                notes.append(f"{spare.get(k)} spare {what} not picked up yet: waiting before making more")
        short = [x for x in short if x not in waiting or x[0] in released]
        if short and not gear.get("forges"):
            ask_player(notes, f"soldiers lack {short[0][2]} and the fort has no forge to make them")
        elif (short and not gear.get("squads_with_uniform")
              and not [t for t in _l(mil.get("uniform_templates")) if isinstance(t, str)]):
            # (with the fort's uniform templates the AI gives the squad one itself)
            ask_player(notes, f"soldiers lack {', '.join(x[2] for x in short)}, but no squad has a uniform, so "
                         "gear wouldn't be handed out: set one in the military screen (Equip)")
        elif short:
            key, recipe, what, n = short[0]
            n = min(n, cfg["max_gear_order"])
            need = n * cfg["gear_bars"][key]
            metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= need), None)
            if metal:
                proposals.append(Proposal(
                    "arms", {"type": "work_order", "recipe": recipe, "amount": n, "material": f"INORGANIC:{metal}"},
                    f"{soldiers} soldiers, {gear.get(GEAR_HELD[key]) or 0} "
                    f"have {what}: make {n} in {metal.lower().replace('_', ' ')}", 3, True))
            elif (_has_shop(s["buildings"], "Smelter") and _d(_d(s.get("industry")).get("ores"))
                  and ("smelting" in (memory.libraries_imported or []) or not rules_["import_smelting"]
                       or "ore_stock_by" in _d(s.get("industry")))):
                # the AI is on it: ore mined, a smelter, DFHack's smelting orders in
                notes.append(f"soldiers lack {what}: waiting for {need} bars of weapon-grade metal "
                             "(the ore is being mined and smelted)")
            else:
                ask_player(notes, f"soldiers lack {what} and there aren't {need} bars of a weapon-grade metal "
                             "(steel, iron, bronze, copper): smelt some ore")

    # Barracks: each squad trains (and keeps its gear) in one, as the zone's
    # squad screen does; one squad a cycle
    # a crossbow squad also trains at an archery range
    rngs = [b for b in _l(mil.get("ranges")) if isinstance(b, dict) and b.get("id") is not None]
    if rngs:
        at_range = {sid for b in rngs for sid in _l(b.get("squads"))}
        for q in squads:
            if is_ranged(q) and q.get("id") is not None and q["id"] not in at_range and (q.get("members") or 0) > 0:
                proposals.append(Proposal("barracks_assign", {"type": "squad_barracks", "squad_id": q["id"],
                                                              "zone_id": rngs[0]["id"]},
                                          f"{q.get('name') or 'a squad'} shoots crossbows: train at the archery range", 4))
                break
    bks = [b for b in _l(mil.get("barracks")) if isinstance(b, dict) and b.get("id") is not None]
    if bks and squads:
        using = {sid for b in bks for sid in _l(b.get("squads"))}
        for q in squads:
            if q.get("id") is not None and q["id"] not in using and (q.get("members") or 0) > 0:
                b = min(bks, key=lambda b: len(_l(b.get("squads"))))
                proposals.append(Proposal("barracks_assign", {"type": "squad_barracks", "squad_id": q["id"],
                                                              "zone_id": b["id"]},
                                          f"{q.get('name') or 'a squad'} has no barracks: train there and keep its "
                                          "gear on the armour stands and racks", 4))
                break

    # Filling: soldiers wanted from the Militarism trait, into open places.
    want, have = soldiers_wanted(s, citizens, cfg, many_idle), mil.get("soldiers") or 0
    from quirks import has_rule
    if memory is not None and has_rule(memory.culture, "more_soldiers"):
        want = min(citizens, round(want * 1.25))   # (Oathbound)
    # (0.102) an army bigger than the fort wants (Militarism lowered, the fort
    # shrank) gives soldiers back to work a few at a time, while all is quiet.
    # Monastery kept 49 soldiers at Militarism -60 (it wanted ~10).
    over = have - want
    # (0.104.66) while civilians badly want to train, the swap turns the squads
    # over instead: the wanted number falls as the keen are drafted (the cap
    # for the keen lifts and drops), and a trim then sent 2 of 38 home (16:03)
    # just as the fill drafted more
    keen = int(_d(s.get("needs")).get("keen_civilians") or 0)
    if (rules_["fill_squads"] and not any_reach and not berserk_now and keen < cfg["soldier_swap_keen_min"]
            and over > max(cfg["trim_margin_min"], round(want * cfg["trim_margin_share"]))):
        count = min(over, cfg["max_trim_per_cycle"])
        proposals.append(Proposal("squad_trim", {"type": "squad_trim", "count": count},
                                  f"{have} soldiers, the fort wants {want} (Militarism "
                                  f"{int(traits.get('militarism', 0) or 0):+d}): {count} go back to work", 5))
    if have < want and not rules_["fill_squads"]:
        notes.append(f"{have} soldiers, the fort wants {want}: raising and filling squads is off on the Rules tab "
                     "(yours to do)")
    elif (have < want and isinstance(getattr(memory, "fight", None), dict) and memory.fight
          and 0 <= abs_tick(s) - int(memory.fight.get("tick") or 0) < cfg["fight_freeze_days"] * TICKS_PER_DAY):
        # (0.104.139) no new soldiers mid-fight: the losses are read from the
        # soldier count after it (refills hid them, and the beast was learned as weaker)
        notes.append(f"{have} soldiers, the fort wants {want}: the squads are filled once the fight is over")
    elif have < want:
        open_ = [(q, min(9, (q.get("size") or 0) - 1) - max(0, (q.get("members") or 0) - (1 if q.get("leader") else 0)))
                 for q in squads]
        open_ = [(q, n) for q, n in open_ if n > 0]
        if open_:
            q, n = open_[0]
            count = min(n, want - have, cfg["max_fill_per_cycle"])
            act = {"type": "squad_fill", "squad_id": q["id"], "count": count}
            home = recently_home(s, memory)              # (0.104.138) not those just sent home
            if home:
                act["avoid"] = home
            proposals.append(Proposal("squad_fill", act,
                                      f"{have} soldiers, the fort wants {want}: add {count} to "
                                      f"{q.get('name') or 'a squad'}", 3))
        else:
            # (0.97: "Raise and fill squads" governs new squads too; it was
            # appoint_nobles, which said nothing about squads)
            # a new squad: a militia commander's (or captain's) post, its leader
            # appointed, the uniform copied from a squad that has one. When the
            # game has no free post for it, that's yours to add (Oct 23: refused
            # quietly over and over while the fort wanted more soldiers)
            ref = _d((getattr(memory, "refusals", None) or {}).get(
                refusal_key(Proposal("squad_make", {"type": "make_squad"}, "", 3))))
            if "no military office" in str(ref.get("why") or ""):
                ask_player(notes, f"{have} soldiers, the fort wants {want}, every squad is full and no military "
                                  "office is free to lead another: add a captain's post (nobles screen) or create "
                                  "a squad in the military screen; the AI fills and trains it")
            proposals.append(Proposal("squad_make", {"type": "make_squad"},
                                      (f"the fort wants {want} soldiers and has no squad" if not squads else
                                       f"{have} soldiers, the fort wants {want}, and every squad is full")
                                      + ": make a squad and appoint its leader", 3))
    g = _d(mil.get("gear"))
    templates = [t for t in _l(mil.get("uniform_templates")) if isinstance(t, str)]
    if rules_["make_gear"] and templates and proposals is not None:
        # a uniform from the fort's templates: leather until the forge has made
        # metal armour and helms for every soldier, then metal
        spare = _d(g.get("spare"))
        bars_total = sum(v for v in _d(g.get("bars")).values() if isinstance(v, (int, float)))
        for q in squads:
            n = int(q.get("members") or 0)
            # metal once the armour is there, or once there are bars enough to
            # make it: a leather uniform takes only leather helms and armour, so
            # iron helms made for it lay unused (region2, y52)
            metal = n > 0 and (((spare.get("body") or 0) >= n and (spare.get("helms") or 0) >= n)
                               or bars_total >= cfg["metal_kit_bars"] * n)
            kind = "metal" if metal else "leather"
            ranged = is_ranged(q)
            if q.get("uniform") is False:
                proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": q["id"], "kind": kind},
                                          f"{q.get('name') or 'a squad'} has no uniform (they'd fight in their "
                                          f"clothes): give it the fort's {kind} uniform", 3))
            elif metal and q.get("ai_uniform") and "metal" not in str(q["ai_uniform"]).lower():
                proposals.append(Proposal("uniform", dict({"type": "set_uniform", "squad_id": q["id"], "kind": "metal"},
                                                          **({"ranged": True} if ranged else {})),
                                          f"metal armour and helms for all {n} of {q.get('name') or 'a squad'}, "
                                          f"or {round(bars_total)} bars to make them: change its uniform from "
                                          "leather to metal", 5))
                # the leather armour they wear counts as armour: order the mail
                short = n - int(spare.get("body") or 0) - queued(s, {"metal_mail_shirt"})
                metal_tok = _best_metal(s, max(1, short))
                if short > 0 and metal_tok:
                    proposals.append(Proposal("kit", {"type": "work_order", "recipe": "metal_mail_shirt",
                                                      "amount": short, "material": metal_tok},
                                              f"{q.get('name') or 'a squad'} goes from leather to metal: make "
                                              f"{short} mail shirt(s) in {metal_tok.split(':')[-1].lower()}", 5, True))
        # squads the AI made before 0.82 copied the AI's uniform without saying
        # it was the AI's: mark it so, so the AI may change it later
        for q in squads:
            if (q.get("id") in (getattr(memory, "squads_made", None) or []) and q.get("uniform")
                    and not q.get("ai_uniform")):
                proposals.append(Proposal("uniform_adopt", {"type": "adopt_uniform", "squad_id": q["id"]},
                                          f"{q.get('name') or 'a squad the AI made'} wears a copy of the AI's "
                                          "uniform: the AI takes charge of it", 3))
                break
        _ranged_squad_rule(s, g, squads, templates, cfg, proposals, getattr(memory, "squads_made", None))
        _uniform_weapon_rule(s, g, squads, rules_, proposals)
    elif isinstance(g.get("squads"), int) and g["squads"] > (g.get("squads_with_uniform") or 0):
        ask_player(notes, f"{g['squads'] - (g.get('squads_with_uniform') or 0)} squad(s) have no uniform, so "
                   "they'd fight in their clothes: set one in the military screen (Equip); the AI copies it to "
                   "the squads it makes later")


def _training_rotation(s: dict, memory, squads: list, train_to: str, off: str, cfg: dict,
                       proposals: list) -> set:
    """Two or more squads the AI trains: they take turns, half of them
    training and the rest back at work, the turn passing each month, so the
    fort isn't short of hands and every squad keeps its edge. Only squads
    the AI put on training (or rested itself); one you set is left alone.
    A militant fort (Militarism 50+) trains them all. Returns the squads in
    the rotation."""
    mine = sorted(q["id"] for q in squads
                  if q.get("id") is not None and (q.get("members") or 0) > 0 and not q.get("ai_orders")
                  and q["id"] in memory.squads_trained
                  and ("off duty" not in str(q.get("routine") or "").lower() or q["id"] in memory.squads_rested))
    if len(mine) < 2:
        return set()
    n, k = len(mine), -(-len(mine) // 2)
    # (0.104.53) while many soldiers badly want to train, all of them do
    # (Enxah: MartialTraining 16 badly, 52 distracted, a squad off duty by turns)
    cit = max(1, int(_d(s.get("dwarves")).get("total") or 0))
    mt = int(_d(_d(_d(s.get("needs")).get("needs")).get("MartialTraining")).get("badly") or 0)
    if mt >= max(5, cit * cfg["train_all_share"]):
        k = n
    turn = abs_tick(s) // (cfg["train_rotate_days"] * TICKS_PER_DAY)
    on = {mine[(turn * k + j) % n] for j in range(k)}
    by_id = {q["id"]: q for q in squads if q.get("id") is not None}
    for sid in mine:
        q = by_id[sid]
        resting = "off duty" in str(q.get("routine") or "").lower()
        # (0.100) a squad on its turn still on staggered training (the AI's
        # older choice) moves to the rotation's routine, constant training
        staggered = "staggered" in str(q.get("routine") or "").lower() and "staggered" not in train_to.lower()
        if sid in on and (resting or staggered):
            proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": sid, "routine": train_to},
                                      f"{q.get('name') or 'a squad'}'s turn to train this month "
                                      f"({k} of {n} squads train at a time)", 4))
        elif sid not in on and not resting:
            proposals.append(Proposal("train", {"type": "squad_routine", "squad_id": sid, "routine": off},
                                      f"{q.get('name') or 'a squad'} has trained its month: back to work while "
                                      f"another squad trains ({k} of {n} at a time)", 4))
    return set(mine)


def _ranged_squad_rule(s: dict, g: dict, squads: list, templates: list, cfg: dict, proposals: list,
                       squads_made: list | None = None) -> None:
    """Crossbows: with two squads or more, one (the newest the AI dresses)
    becomes a crossbow squad, in the fort's crossbow uniform with bolts for
    combat and training; then crossbows and bolts for it, wooden at the
    bowyer's (metal bolts at the forge when bars are plenty)."""
    manned = [q for q in squads if (q.get("members") or 0) > 0 and q.get("id") is not None]
    if not any("crossbow" in t.lower() for t in templates):
        return
    ranged = [q for q in manned if is_ranged(q)]
    # which squad shoots: the newest the AI made itself, never the fort's
    # first squad while there are others (Oct 23: the first squad, with the
    # militia commander and the Axe Lord, was given crossbows because it was
    # the only one whose uniform the AI had recorded)
    mine = [q for q in manned if q.get("ai_uniform")]       # (one without a uniform gets one first)
    first = min((q["id"] for q in manned), default=None)
    made = [q for q in mine if q["id"] in (squads_made or [])]
    pool = made or [q for q in mine if q["id"] != first or len(manned) < 2]
    best = max(pool, key=lambda q: q["id"]) if pool else None

    def kind_of(q):
        return "metal" if "metal" in str(q.get("ai_uniform") or "").lower() else "leather"
    if len(manned) >= cfg["ranged_from_squads"] and best is not None and not is_ranged(best) and (
            not ranged or all(q["id"] not in [b["id"] for b in pool] for q in ranged)):
        proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": best["id"], "kind": kind_of(best),
                                              "ranged": True},
                                  (f"{len(manned)} squads and none shoots" if not ranged else
                                   f"{ranged[0].get('name') or 'an older squad'} shoots but its fighters "
                                   "are the fort's best at close quarters")
                                  + f": make {best.get('name') or 'a newer squad'} a crossbow squad (they shoot from "
                                  "behind the gates)", 4))
        return
    if len(ranged) > 1:
        # one crossbow squad is enough: the others back to their melee uniform
        keep = best if best is not None and is_ranged(best) else max(ranged, key=lambda q: q["id"])
        q = min((q for q in ranged if q["id"] != keep["id"]), key=lambda q: q["id"])
        proposals.append(Proposal("uniform", {"type": "set_uniform", "squad_id": q["id"], "kind": kind_of(q)},
                                  f"{len(ranged)} crossbow squads: {q.get('name') or 'an older squad'} goes back "
                                  "to close combat", 4))
        return
    if not ranged:
        return
    if not ranged or "ranged_armed" not in g:
        return
    members = sum(int(q.get("members") or 0) for q in ranged)
    wood = int(_d(s.get("stocks")).get("wood") or 0)
    shop = _has_shop(s["buildings"], "Bowyers")
    short = members - int(g.get("ranged_armed") or 0) - int(g.get("spare_crossbows") or 0) - queued(s, {"wooden_crossbow"})
    if short > 0:
        if shop and wood >= short:
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "wooden_crossbow", "amount": min(short, 5)},
                                      f"{members} crossbow soldiers and {g.get('ranged_armed') or 0} with a "
                                      f"crossbow: make {min(short, 5)} at the bowyer's", 3, True))
            return
    want = members * cfg["bolts_per_soldier"]
    bshort = want - int(g.get("bolts") or 0) - 25 * (queued(s, {"wooden_bolts"}) + queued(s, {"metal_bolts"}))
    if bshort > 0:
        jobs = min(5, max(1, -(-bshort // 25)))
        bars = _d(g.get("bars"))
        metal = next((m for m in GEAR_METALS if (bars.get(m) or 0) >= jobs + cfg["bolt_bars_keep"]), None)
        if metal and g.get("forges"):
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "metal_bolts", "amount": jobs,
                                               "material": f"INORGANIC:{metal}"},
                                      f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                      f"make {jobs} lot(s) in {metal.lower()}", 4, True))
        elif shop and wood >= jobs:
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "wooden_bolts", "amount": jobs},
                                      f"{g.get('bolts') or 0} bolts for {members} crossbow soldiers ({want} wanted): "
                                      f"make {jobs} lot(s) of wooden bolts", 4, True))
    # (0.100) a crossbow soldier carries bolts in a quiver and picks a spare
    # one up himself: leather quivers until there is one for each
    sup = _d(s.get("supplies"))
    if isinstance(sup.get("quivers"), int):
        qshort = (members - sup["quivers"] - int(sup.get("quivers_worn") or 0)
                  - queued(s, {"leather_quiver"}))
        leather = int(_d(s.get("stocks")).get("leather") or 0)
        if qshort > 0 and leather > 0 and _has_shop(s["buildings"], "Leatherworks"):
            n = min(qshort, leather, cfg["max_quiver_order"])
            proposals.append(Proposal("arms", {"type": "work_order", "recipe": "leather_quiver", "amount": n},
                                      f"{members} crossbow soldiers, {sup['quivers']} spare quiver(s) and "
                                      f"{int(sup.get('quivers_worn') or 0)} worn: make {n} of leather", 4, True))
    if (short > 0 or bshort > 0) and not shop:
        open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
        if not _workshops_busy(open_):
            proposals.append(Proposal("industry", {"type": "start_project", "kind": "workshops", "shops": ["Bowyers"]},
                                      "a crossbow squad and no bowyer's workshop: build one (crossbows and bolts)", 4))


WEAPON_IDS = {"axe": "ITEM_WEAPON_AXE_BATTLE", "spear": "ITEM_WEAPON_SPEAR", "mace": "ITEM_WEAPON_MACE"}


def _uniform_weapon_rule(s: dict, g: dict, squads: list, rules_: dict, proposals: list) -> None:
    """The fort's templates arm a squad with "any melee weapon", and a mining
    pick is one: region2's soldiers took a miner's pick. Once there are
    enough of the AI's weapon (battle axes by default, the Rules tab's
    choice) for a squad the AI dressed, its uniform asks for that weapon
    and nothing else; the pick goes back to the miners."""
    wid = WEAPON_IDS.get(rules_["gear_weapon"])
    spare = int(_d(g.get("spare_weapons")).get(wid) or 0)
    for q in squads:
        ai = str(q.get("ai_uniform") or "")
        n = int(q.get("members") or 0)
        if is_ranged(q):
            # (0.99.11) a crossbow squad keeps its crossbows: region2's squad 56
            # had its weapon turned to battle axes; it gets the crossbow back
            if "|weapon:" in ai and "|weapon:ITEM_WEAPON_CROSSBOW" not in ai:
                proposals.append(Proposal("uniform", {"type": "set_uniform_weapon", "squad_id": q["id"],
                                                      "weapon": "ITEM_WEAPON_CROSSBOW"},
                                          f"{q.get('name') or 'squad ' + str(q.get('id'))} is a crossbow squad "
                                          "whose uniform asks for another weapon: crossbows again", 3))
                return
            continue
        if not ai or not n or f"|weapon:{wid}" in ai or spare < n:
            continue
        proposals.append(Proposal("uniform", {"type": "set_uniform_weapon", "squad_id": q["id"], "weapon": wid},
                                  f"{spare} {rules_['gear_weapon']}s for the {n} soldiers of "
                                  f"{q.get('name') or 'squad ' + str(q.get('id'))}: their uniform asks for "
                                  f"{rules_['gear_weapon']}s, not any weapon (a soldier may take a miner's pick)", 4))
        return


def _anvil_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.86) A project whose forge has waited STALE_PROJECT_DAYS to be
    built: a forge needs an anvil, and the AI never made one. One anvil at
    the forge the fort has, in the best metal with bars to spare (3 bars)."""
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    stuck = [p for p in open_ if (_d(p.get("furnish")).get("days") or 0) >= STALE_PROJECT_DAYS
             and _d(_d(p.get("furnish")).get("waiting")).get("Workshop")
             and any(k in _d(p.get("furniture")) for k in ("MetalsmithsForge", "MagmaForge"))]
    sup = _d(s.get("supplies"))
    if not stuck or "anvils" not in sup or (sup.get("anvils") or 0) > 0 or queued(s, {"metal_anvil"}):
        return
    if not _has_shop(s["buildings"], "MetalsmithsForge"):
        notes.append("a new forge waits for an anvil and there is no forge to make one: buy one from a caravan")
        return
    metal = _best_metal(s, 2)
    if not metal:
        notes.append("a new forge waits for an anvil: no weapon-grade metal bars to make one")
        return
    days = max((_d(p.get("furnish")).get("days") or 0) for p in stuck)
    proposals.append(Proposal("anvil", {"type": "work_order", "recipe": "metal_anvil", "amount": 1, "material": metal},
                              f"a new forge has waited {days} days to be built: it needs an anvil: make one in "
                              f"{metal.split(':')[-1].lower()}", 4, True))


def idle_hands(s: dict, memory, cfg: dict) -> bool:
    """Many idle hands (see update_idle); without memory, today's share alone."""
    if memory is not None and isinstance(getattr(memory, "idle_avg", None), (int, float)):
        return bool(memory.idle_hands)
    return _idle_share(s) >= cfg["idle_train_share"]


# --- (0.104.83) the fort defends itself: the gate held, war dogs posted ----------------

def gate_invaders(s: dict) -> list:
    """Invaders on the map that can't reach the dwarves yet (outside the gates,
    on the surface): the squads wait for them inside the main gate."""
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)
            and t.get("invader") and not t.get("can_reach_dwarves") and t.get("layer") in (None, "surface")]


def main_gate(s: dict, memory) -> dict | None:
    """The fort's main gate: the entrance nearest the plan's main stair (else
    the first surface one)."""
    es = [e for e in _l(_d(s.get("entrances")).get("entrances"))
          if isinstance(e, dict) and all(isinstance(e.get(k), int) for k in ("x", "y", "z"))]
    if not es:
        return None
    spine = _d(_d(_d(getattr(memory, "atlas", None)).get("plan")).get("spine"))
    if isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
        return min(es, key=lambda e: abs(e["x"] - spine["x"]) + abs(e["y"] - spine["y"]))
    return next((e for e in es if e.get("kind") == "surface"), es[0])


def _gate_guard_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.83) Invaders on the map who can't reach the dwarves yet: every
    squad able to fight holds the main gate (a defend order on the gate guard
    burrow, inside it); once they can reach the dwarves the kill orders take
    over, and when they are gone the squads are called back."""
    if not player_rules(s).get("train_squads", True):
        return
    if int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return
    inv = gate_invaders(s)
    gate = main_gate(s, memory)
    if not inv or not gate:
        return
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    able = [q for q in squads if (q.get("members") or 0) >= cfg["min_squad_to_fight"]
            and not q.get("ai_orders") and not (q.get("orders") or 0)]
    if not able:
        return
    proposals.append(Proposal("gate_guard", {"type": "guard_gate", "x": gate["x"], "y": gate["y"], "z": gate["z"],
                                             "squads": [q["id"] for q in able]},
                              f"{len(inv)} invader(s) on the map, none in reach of the dwarves yet: "
                              f"{len(able)} squad(s) hold the main gate (x{gate['x']} y{gate['y']})", 0))


def _gate_dogs_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.83) War-trained animals with no post: penned just inside the
    main gate (a pen made there the first time), a few a call."""
    an = _d(_d(s.get("society")).get("animals"))
    free = int(_d(an.get("gate")).get("free") or 0)
    if free <= 0 or int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return
    gate = main_gate(s, memory)
    if not gate:
        return
    proposals.append(Proposal("gate_dogs", {"type": "gate_dogs", "x": gate["x"], "y": gate["y"], "z": gate["z"],
                                            "max": min(4, free)},
                              f"{free} war-trained animal(s) with no post: pen them inside the main gate "
                              "(they meet what comes in)", 5))
