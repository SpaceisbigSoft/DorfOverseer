"""planner_gates: the gates and lockdowns (split out of planner_military in
0.105.25, 13c): entrances closed and opened, the gate's parts, levers and
their links, traps and the gatehouse; a lone intruder or a few ordinary
enemies, the lockdown released, the quick all-clear; pastures held while
the gates are shut; the gate guard and its dogs. planner_military re-exports
every name here."""

from __future__ import annotations

from dataclasses import field
from culture import profile_from
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["_gate_rules", "GATE_PART_RECIPES", "GATE_PART_STUCK_DAYS", "_gate_parts_rule", "_free_gate_levers", "_lever_far_enough", "machinery_wanted", "_lever_hatches_ok", "_link_wanted", "_lever_rule", "_trap_rule", "_gatehouse_rule", "_near_spot", "lone_intruders", "few_ordinary", "few_alert_over", "hunted_outside", "ai_gates_shut", "_Rec", "_lockdown", "lockdown_released", "lone_alert_over", "_lockdown_ids", "_lockdown_cap_why", "note_lockdown", "quick_clear", "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule"]


def _gate_rules(s: dict, memory, cfg: dict, rules_: dict, any_reach: bool,
                proposals: list, notes: list, traits: dict | None = None) -> None:
    ent = _d(s.get("entrances"))
    now = abs_tick(s)
    age = now - ent["scanned_tick"] if isinstance(ent.get("scanned_tick"), int) else None
    stale = (not ent.get("scanned") or age is None or not 0 <= age < cfg["entrance_scan_ticks"]
             or memory.rescan_entrances
             or ent.get("rescan"))           # (0.105.23) a lever linked since the scan (the bridge saw it)
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
    # (0.105.3) B (2 Nov): a lone thief inside kept the only hatch shut 2.5
    # hours at 1-3 FPS. Enemies already inside aren't kept out by a gate, and
    # a lockdown the AI held days with no new enemy (the game slow, dwarves
    # shut out) is opened: the watcher stands down until a new enemy comes
    lone = lone_intruders(s, cfg, traits, memory) if any_reach else []
    hunted = [] if lone or not any_reach else hunted_outside(s, cfg, traits, memory)    # (0.105.8)
    released = lockdown_released(memory)
    if any_reach and closable and not ent.get("armed") and rules_["gate_lever"] and (lone or released or hunted):
        notes.append(f"{len(lone)} enemy/enemies inside the fort and none outside: the gates stay open "
                     "(shut, they keep only the others out)" if lone else
                     f"only {len(hunted)} ordinary enemy/enemies outside, and a squad on them or citizens out: "
                     "the gates stay open (shut, they keep the squads in and the citizens out)" if hunted else
                     "the AI's lockdown was lifted (no new enemy for days): the gates stay open until a new one comes")
    elif any_reach and closable and not ent.get("armed") and rules_["gate_lever"]:
        proposals.append(Proposal("gates", {"type": "arm_gates"},
                                  f"a threat can reach the dwarves: watch the {len(closable)} gate(s); each closes "
                                  "once everyone is inside or the danger is 12 tiles away", 0))
    elif ent.get("armed") and (lone or released or hunted):
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"only {len(lone)} enemy/enemies left, inside the fort: open the gates (shut, they "
                                  "keep only the others out)" if lone else
                                  f"only {len(hunted)} ordinary enemy/enemies outside and "
                                  + (f"{int(ent.get('citizens_outside') or 0)} citizen(s) shut out"
                                     if int(ent.get("citizens_outside") or 0) else "a squad sent at them")
                                  + ": open the gates (the squads go out, the citizens come in)" if hunted else
                                  "the fort has been shut for days with no new enemy: open the gates", 0))
    elif not any_reach and ent.get("armed") and all_clear(s, memory, cfg)[0]:
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"no threat for {memory.quiet_cycles} cycles: open the gates", 1))
    elif not any_reach and ent.get("armed") and quick_clear(s, memory, cfg):
        # (0.105.3) A (2 Nov): shut on 9 citizens for a sneaker who hid again
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"{quick_clear(s, memory, cfg)}: open the gates", 0))
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
        elif not (isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0):
            open_wide.append((e, where))        # (0.105.0) one a cut closes is _gate_cut_rule's (planner_army)
    if rules_["gate_lever"]:
        _lever_rule(s, memory, cfg, es, now, proposals, traits or {})
    if not any_reach and rules_["fortify_entrances"]:
        _trap_rule(s, memory, cfg, es, now, traits or {}, proposals)
        _gatehouse_rule(s, memory, cfg, es, now, traits or {}, proposals)     # (0.105.23)
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


def _free_gate_levers(s: dict) -> list:
    """The levers the AI may link, while linked to nothing and with no job:
    ones the AI placed for a drawbridge ("AI gate lever"), or the player's
    "AI gate" (bridge 0.35+ lists both; older ones: the player's only)."""
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


def machinery_wanted(traits: dict) -> bool:
    """(0.105.12, 14.1 step 4) A fort that cares for its machinery or its
    walls works its gates by lever: Engineering 40+ or Fortification 60+."""
    return ((traits or {}).get("engineering", 0) or 0) >= 40 or ((traits or {}).get("fortification", 0) or 0) >= 60


def _lever_hatches_ok(e: dict, cfg: dict) -> bool:
    """(0.105.23) An entrance whose hatches get levers: not a cut (its many
    hatches, a lever each), at most hatch_lever_max_hatches of them."""
    if e.get("cut") or (isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0):
        return False
    n = sum(1 for b in _l(e.get("equipment")) if isinstance(b, dict) and b.get("kind") == "hatch")
    return n <= cfg.get("hatch_lever_max_hatches", 2)


def _link_wanted(s: dict, e: dict, lever_id=None, hatches: bool = False) -> list:
    """Drawbridges at this entrance the AI gate lever should be linked to:
    ones no lever inside the fort works, and watched ones whose levers are
    all at the gate. [] with an older bridge (no lever details). (0.105.12)
    hatches: a hatch no lever works, too. (0.105.23) Drawbridges first."""
    out = [bid for bid in _l(e.get("bridges_unworked")) if isinstance(bid, int)]
    later = []
    if e.get("gatehouse") == "standing" and not e.get("outer"):
        hatches = False                     # (0.105.23) the gatehouse's drawbridge gets its lever first
    for b in _l(e.get("equipment")):
        if (isinstance(b, dict) and b.get("kind") == "bridge" and "lever_away" in b and not b["lever_away"]
                and not (lever_id is not None and lever_id in _l(b.get("levers")))):
            out.append(b.get("id"))
        elif (hatches and isinstance(b, dict) and b.get("kind") == "hatch" and "levers" in b
              and not _l(b.get("levers")) and isinstance(b.get("id"), int)):
            later.append(b["id"])
    return out + later


def _lever_rule(s: dict, memory, cfg: dict, es: list, now: int, proposals: list, traits: dict | None = None) -> None:
    """A drawbridge in an entrance that no lever inside works, or only levers
    at the gate: the lever named "AI gate", while it's linked to nothing (and
    is itself away from that gate), is linked to it, so a dwarf can close it
    from inside, away from the danger. Two free mechanisms are needed; if
    there aren't, they're ordered.
    (0.105.23, 14.1 step 4a) A fort that works its gates by machinery
    (machinery_wanted) gets a lever for its hatches too (hatch_levers): the
    gate watcher drives a hatch on a lever by DFHack's instant pull, and a
    hatch the link shut is opened at once. One lever for each gate: a free
    lever is linked once, and the next gate gets a lever of its own.
    Drawbridges before hatches; a lever is placed only with 3 mechanisms
    free (its own and the link's two), else they're ordered."""
    hatches = (cfg.get("hatch_levers") and machinery_wanted(traits or {})
               and not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"))
    ent = _d(s.get("entrances"))
    # (0.105.23) drawbridges before hatches: entrances with a bridge to link come first
    def bridge_first(e):
        wanted = _link_wanted(s, e, None, hatches=False)
        return 0 if wanted else 1
    es = sorted(es, key=bridge_first)
    levers = _free_gate_levers(s)
    if not levers:
        # (0.105.12) a fort that wants machinery and has a gate no lever works: a lever of its own
        if hatches:
            for e in es:
                if (e.get("sealed") and _lever_hatches_ok(e, cfg)
                        and _link_wanted(s, e, None, hatches=True)):
                    off = _d(s.get("map")).get("elevation_offset")
                    elev = (e.get("z") or 0) + (off if isinstance(off, int) else 0)
                    free = ent.get("free_mechanisms")
                    need = cfg.get("hatch_lever_mechanisms", 3)
                    if isinstance(free, int) and free < need:
                        # (0.105.23) the lever and its link's two first: never a lever left unlinked for want
                        if not queued(s, {"mechanisms"}):
                            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                                     "amount": need - free},
                                                      f"{need - free} mechanism(s) for a gate lever and its link "
                                                      f"({free} free)", 6, is_order=True))
                        break
                    proposals.append(Proposal("gate_lever", {"type": "place_gate_lever", "entrance_id": e["id"]},
                                              f"the gate at the {e.get('kind')} entrance at elevation {elev} has no "
                                              "lever, and this fort works its gates by machinery: a lever inside, "
                                              "away from the gate", 6))
                    break
        return
    for e in es:
        # the first free lever away from this gate (another may suit another gate)
        lever = next((lv for lv in levers if _lever_far_enough(lv, e)), None)
        if not lever:
            continue
        for bid in _link_wanted(s, e, lever["id"], hatches=hatches and _lever_hatches_ok(e, cfg)):
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
                                      f"the gate at the {e.get('kind')} entrance at elevation {elev} "
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
        # (0.105.9) a hatch is a gate too: the founding stair's hatch was every
        # fort's only gate, so no fort ever got a trap
        if not e.get("sealed") or not any(isinstance(b, dict) and b.get("kind") in ("door", "bridge", "hatch")
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
        n = min(8, n)                              # (0.105.10) the bridge places 1-8 a call (A asked 9: refused)
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        proposals.append(Proposal("traps", {"type": "place_traps", "entrance_id": e["id"], "kind": kind, "count": n},
                                  f"{where} has a gate but no traps: {n} {kind} trap(s) just inside it", 6))
        free = _d(s.get("entrances")).get("free_mechanisms")
        if isinstance(free, int) and free < n:
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": n - free},
                                      f"{n - free} mechanisms for the traps at {where}", 6, is_order=True))
        return


def _gatehouse_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list) -> None:
    """(0.105.23, 14.1 step 4a) The War-hold's gate as a level: a fort of
    Fortification gatehouse_fortification+ builds a gatehouse in front of
    the founding stair's hatch (lua/ai-gates.lua build_gatehouse): a walled
    corridor on the surface, its floor set with traps in the fort's style
    (cage when it has none), ended by a drawbridge the gate rule then gives
    a lever. Once at a spot, never while a threat can reach the dwarves (the
    caller), one a cycle; a refusal waits gate_retry_ticks. Mechanisms for
    the traps, the lever and its link are ordered when short."""
    import defence
    if (traits.get("fortification", 0) or 0) < cfg["gatehouse_fortification"]:
        return
    ent = _d(s.get("entrances"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    built = getattr(memory, "gatehouses", None) or {}
    for e in es:
        if not (e.get("sealed") and e.get("kind") == "surface" and e.get("gatehouse") == "possible"):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if _near_spot(e, built):
            continue                            # built here once: the scan sees its bridge, or it was taken down
        why, when = memory.gate_failures.get("gatehouse:" + spot), memory.gate_failure_ticks.get("gatehouse:" + spot)
        if why and isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
            continue
        kind = profile_from(traits, memory.culture)["traps"]
        kind = kind if kind in ("cage", "stonefall", "weapon") else "cage"
        n = max(2, min(4, defence.trap_count(traits)))
        where = f"the founding stair at elevation {(e.get('z') or 0) + off + 1} (x{e.get('x')} y{e.get('y')})"
        proposals.append(Proposal("gatehouse", {"type": "build_gatehouse", "entrance_id": e["id"], "kind": kind,
                                                "count": n},
                                  f"a fortified fort (Fortification {int(traits.get('fortification', 0)):+d}): a "
                                  f"gatehouse in front of the hatch at {where}: a walled corridor with {n} {kind} "
                                  "trap(s) and a drawbridge, raised with the hatch when danger comes", 6))
        need = n + 3                            # the traps, the bridge's lever and its link
        free = ent.get("free_mechanisms")
        if isinstance(free, int) and free < need and not queued(s, {"mechanisms"}):
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": need - free},
                                      f"{need - free} mechanisms for the gatehouse at {where}", 6, is_order=True))
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


def lone_intruders(s: dict, cfg: dict, traits: dict | None = None, memory=None) -> list:
    """The ids of the enemies that can reach the dwarves when they are only a
    few (`lone_intruder_max`) ordinary ones (no great danger, flier or
    building destroyer) already INSIDE the fort, and nothing hostile is left
    outside; [] otherwise. Inside is the gate scan's map of the fort
    (entrances.intruders_inside, lua/ai-gates.lua): DF's walk groups can't
    tell an enemy inside from one waiting at a locked door. Without that map
    (an older bridge, no scan yet): [] (as before). One read as inside before
    (memory) still counts while no new enemy came: a thief walking out past
    the gate doesn't arm it again behind him."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = reachable_threats(s, traits if traits is not None else _traits(s), cfg)
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    # (0.105.4 review) no map this cycle (a rescan, a reload): the ones read
    # as inside before still count, so the lone-thief case doesn't flip
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if isinstance(x, int)} | {
        x for x in _l(_lockdown(memory).get("lone_ids")) if isinstance(x, int)}
    if not inside:
        return []
    for i in reach:
        t = rows.get(i)
        if (not isinstance(t, dict) or i not in inside or t.get("great_danger") or t.get("flier")
                or t.get("destroyer")):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []                       # a siege still outside: the gates hold it off, as before
    return list(reach)


def few_ordinary(s: dict, cfg: dict, traits: dict | None = None) -> list:
    """(0.105.8) The ids of the enemies that can reach the dwarves when they
    are only a few (`lone_intruder_max`) ordinary ones (no great danger,
    flier or building destroyer), inside or outside, and no siege is held off
    at the gates; [] otherwise."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = list(reachable_threats(s, traits if traits is not None else _traits(s), cfg))
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    for i in reach:
        t = rows.get(i)
        if not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer"):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []
    return reach


def few_alert_over(s: dict, memory, cfg: dict) -> bool:
    """(0.105.8) The alarm has been up `lone_intruder_alert_ticks` while only a
    few ordinary enemies were about, inside or out. B (Monastery, 2 Nov): one
    thief outside, the alarm up 70 real minutes at 1-3 FPS; the shelter held
    the civilians from the drink and 31 died of thirst when it came down."""
    since, now = _lockdown(memory).get("few_since"), abs_tick(s)
    return (isinstance(since, int) and isinstance(now, int)
            and now - since >= cfg.get("lone_intruder_alert_ticks", 600))


def hunted_outside(s: dict, cfg: dict, traits: dict | None = None, memory=None) -> list:
    """The ids of the enemies that can reach the dwarves when they are only a
    few (`lone_intruder_max`) ordinary ones (no great danger, flier or
    building destroyer), some of them outside the fort, no siege is held off
    at the gates, and an armed squad has a kill order on every one of them
    (the gates then open: the squads must get out, the citizens in); []
    otherwise. Without the gate scan's map: []."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = list(reachable_threats(s, traits if traits is not None else _traits(s), cfg))
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    ent = _d(s.get("entrances"))
    if not ent.get("scanned"):
        return []
    for i in reach:
        t = rows.get(i)
        if not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer"):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []
    want = set(reach)
    hunted = set()
    for q in _l(_d(s.get("military")).get("squads")):
        if isinstance(q, dict) and q.get("ai_orders") and can_fight(q, cfg) and isinstance(q.get("kill_ids"), list):
            hunted |= want & set(q["kill_ids"])
    # (a squad on them, not citizens outside alone: without one the watcher
    # would be armed, shut and opened again each cycle)
    return reach if hunted == want else []


def ai_gates_shut(s: dict, memory=None) -> bool:
    """The AI's gates shut now: the watcher armed with an entrance closed, or
    the AI gate lever pulled by the AI."""
    ent = _d(s.get("entrances"))
    if ent.get("armed") and any(isinstance(e, dict) and e.get("closed") for e in _l(ent.get("entrances"))):
        return True
    return bool(memory is not None and getattr(memory, "gate_closed_by_ai", False))


class _Rec:
    """A stand-in memory holding only a lockdown record (note_lockdown reads
    lone_intruders against the record it is building)."""
    def __init__(self, rec: dict):
        self.atlas = {"lockdown": rec}


def _lockdown(memory) -> dict:
    """The lockdown's record, kept in the atlas beside the gates' history:
    {new: tick the last new enemy came, seen: ids, released: tick the AI
    opened up early, lone_since: tick only a lone intruder was left}."""
    return _d(_d(getattr(memory, "atlas", None)).get("lockdown")) if memory is not None else {}


def lockdown_released(memory) -> bool:
    return isinstance(_lockdown(memory).get("released"), int)


def lone_alert_over(s: dict, memory, cfg: dict) -> bool:
    """The alarm has been up `lone_intruder_alert_ticks` for a lone intruder."""
    since, now = _lockdown(memory).get("lone_since"), abs_tick(s)
    return (isinstance(since, int) and isinstance(now, int)
            and now - since >= cfg.get("lone_intruder_alert_ticks", 600))


def _lockdown_ids(s: dict, traits: dict, cfg: dict) -> list:
    ids = list(reachable_threats(s, traits, cfg))
    return ids + [t.get("id") for t in held_off_threats(s) if t.get("id") not in ids]


def _lockdown_cap_why(s: dict, cfg: dict, ids: list, quiet_ticks: int, rec: dict | None = None) -> str:
    """Why an AI lockdown is opened early ("" if it isn't): no new enemy for
    `lockdown_max_days`, only a few ordinary ones left, all of them already
    INSIDE the fort, and the game slow or citizens shut out. A siege or a
    great danger: never. (0.105.4 review) Enemies held off outside never
    count toward it: two camped at the gate of a slow fort for 2 days got the
    gates opened, and nothing closed them again when those two walked in."""
    if not ids or quiet_ticks < cfg.get("lockdown_max_days", 2) * TICKS_PER_DAY:
        return ""                       # (nothing left: all_clear's quiet days, as before)
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if isinstance(x, int)} | {
        x for x in _l(_d(rec).get("lone_ids")) if isinstance(x, int)}
    if held_off_threats(s) or any(i not in inside for i in ids):
        return ""
    rows = {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    if (len(ids) > cfg.get("lockdown_cap_threats", 2) or great_present(s)
            or any(i not in rows or rows[i].get("great_danger") for i in ids)):
        return ""
    out = int(_d(s.get("entrances")).get("citizens_outside") or 0)
    if s.get("fps_low"):
        return f"the game runs slowly (FPS {s.get('fps_low')})"
    if out > 0:
        return f"{out} citizen(s) are shut out"
    return ""


def note_lockdown(s: dict, memory, cfg: dict) -> list[str]:
    """(0.105.3) Bookkeeping before planning (note_cycle): when the last new
    enemy came while the AI held the fort shut, whether only a lone intruder
    is left (and since when), and whether the lockdown is opened early. A
    new enemy closes it again."""
    notes: list[str] = []
    if not isinstance(getattr(memory, "atlas", None), dict):
        memory.atlas = {}
    now = abs_tick(s)
    if not isinstance(now, int):
        return notes
    traits = _traits(s)
    ids = _lockdown_ids(s, traits, cfg)
    holding = _holding_off(s, memory) or bool(memory.gate_closed_by_ai)
    if not ids and not holding:
        memory.atlas.pop("lockdown", None)
        return notes
    rec = dict(_lockdown(memory))
    seen = _l(rec.get("seen"))
    new = [i for i in ids if i not in seen]
    if not isinstance(rec.get("new"), int) or rec["new"] > now:
        rec["new"] = now
    # (0.105.4 review) a lifted lockdown closes again for a new enemy, or for
    # one that can reach the dwarves now and couldn't (or wasn't inside) when
    # it was lifted: the same two camped outside walking in
    reach_now = list(reachable_threats(s, traits, cfg))
    came_in = [i for i in reach_now if i not in _l(rec.get("released_ids"))]
    if new:
        rec["new"] = now
        rec["seen"] = (seen + new)[-100:]
    if (new or came_in) and isinstance(rec.get("released"), int):
        rec.pop("released", None)
        rec.pop("released_ids", None)
        notes.append(f"{len(new) or len(came_in)} " + ("new enemy/enemies" if new else "enemy/enemies able to reach "
                     "the dwarves now") + ": the gates and alarm may close again")
    if new:
        rec.pop("lone_ids", None)       # a new enemy: read afresh from the map
    few = few_ordinary(s, cfg, traits)
    if few:
        if not isinstance(rec.get("few_since"), int) or rec["few_since"] > now:
            rec["few_since"] = now
    else:
        rec.pop("few_since", None)
    lone = lone_intruders(s, cfg, traits, _Rec(rec))
    if lone:
        if not isinstance(rec.get("lone_since"), int) or rec["lone_since"] > now:
            rec["lone_since"] = now
        rec["lone_ids"] = lone[:10]
    else:
        rec.pop("lone_since", None)
        rec.pop("lone_ids", None)
    if ids:
        rec["peak"] = max(int(rec.get("peak") or 0), len(ids))
    if great_present(s):
        rec["great"] = True
    if holding and not isinstance(rec.get("released"), int):
        why = _lockdown_cap_why(s, cfg, ids, now - rec["new"], rec)
        if why:
            rec["released"] = now
            rec["released_ids"] = reach_now[:50]
            notes.append(f"the AI has kept the fort shut {(now - rec['new']) // TICKS_PER_DAY} day(s) with no new "
                         f"enemy and only {len(ids)} left, and {why}: the gates open and the alarm comes down "
                         "(a new enemy closes them again)")
    memory.atlas["lockdown"] = rec
    return notes


def quick_clear(s: dict, memory, cfg: dict) -> str:
    """(0.105.3) Why the AI's shut gates and alarm may be lifted before
    all_clear's quiet days ("" if not): nothing hostile in sight (no enemy
    that can reach the dwarves, no siege held off at the gates, no great
    danger lately), a cycle quiet, and since the last enemy was seen either
    `lockdown_clear_ticks` with citizens or many visitors shut out (A, 2 Nov:
    9 citizens and 39 visitors outside a hatch shut for a sneaker who hid
    again), or `small_alert_ticks` when only a few ordinary enemies were ever
    seen (a sneaker, a thief). A siege in sight keeps the fort shut as before."""
    if memory is None or memory.quiet_cycles < cfg["alert_quiet_cycles"]:
        return ""                       # (the quiet cycles as all_clear: only its days are cut)
    if reachable_threats(s, _traits(s), cfg) or held_off_threats(s) or great_present(s):
        return ""
    now = abs_tick(s)
    if not isinstance(now, int):
        return ""
    if memory.last_great_tick and (now - memory.last_great_tick) // TICKS_PER_DAY < cfg["alert_quiet_days_great"]:
        return ""
    since = now - int(memory.last_threat_tick or 0) if memory.last_threat_tick else 10 ** 9
    rec = _lockdown(memory)
    # shut out: only while the AI's gates are shut (with them open, nobody is)
    shut = ai_gates_shut(s, memory)
    out = int(_d(s.get("entrances")).get("citizens_outside") or 0) if shut else 0
    # (0.105.4 review) visitors OUTSIDE the fort only (a tavern holds 20+
    # inside); an older bridge without the count: citizens alone
    vo = _d(s.get("entrances")).get("visitors_outside")
    visitors = vo if shut and isinstance(vo, int) and not isinstance(vo, bool) else 0
    # (0.105.4 review) only after a small one (a sneaker, a thief): a bigger
    # ambush that vanished keeps the normal quiet wait
    small = not rec.get("great") and 0 < int(rec.get("peak") or 0) <= cfg.get("lockdown_cap_threats", 2)
    if (small and (out > 0 or visitors >= cfg.get("lockdown_visitors", 20))
            and since >= cfg.get("lockdown_clear_ticks", 300)):
        return (f"nothing hostile in sight for {since // 50} game hour(s) and "
                + (f"{out} citizen(s)" if out else f"{visitors} visitors") + " shut out")
    if small and since >= cfg.get("small_alert_ticks", 1200):
        return f"only {int(rec['peak'])} enemy/enemies were seen and none for a day"
    return ""


# (0.105.3) B (2 Nov): 26 PenLargeAnimal jobs open at once behind the shut
# hatch (back to 1 after): animals led to pastures outside, every one
# re-routing to a way in that wasn't there. What puts animals in a pasture
# (or makes one, or pens the hens) waits while the AI's gates are shut.
PASTURE_ACTIONS = ("pasture", "make_pasture", "nest_boxes")


def _pasture_hold(s: dict, memory, proposals: list, notes: list) -> list:
    if not ai_gates_shut(s, memory):
        return proposals
    held = [p for p in proposals if p.action.get("type") in PASTURE_ACTIONS]
    if not held:
        return proposals
    notes.append(f"the AI's gates are shut: {len(held)} pasture assignment(s) wait until they open "
                 "(animals led to a pasture outside would only pile up at the gate)")
    return [p for p in proposals if p not in held]


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
    able = [q for q in squads if can_fight(q, cfg)
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
