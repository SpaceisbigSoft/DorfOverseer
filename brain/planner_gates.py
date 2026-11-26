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
from planner_construct import _wings_rule, cavern_wall_style  # (0.105.30) wing walls, the Hermit's cavern walls
from planner_gates_stuck import *  # noqa: F401,F403  (r7: split out by theme)
from planner_gates_stuck import _row_danger, _flags_text, _gate_stuck_rule, _way_in_doing, _way_in_area, _way_in_rule, _surface_entrances, _second_way_rule, _stranded_relook, _stranded_rule  # noqa: F401  (* skips the underscored names)
from planner_gates_lockdown import *  # noqa: F401,F403  (r7: split out by theme)
from planner_gates_lockdown import _sortie_on, _Rec, _lockdown, _lockdown_ids, _lockdown_cap_why, _pasture_hold, _gate_guard_rule, _gate_dogs_rule  # noqa: F401  (* skips the underscored names)

__all__ = ["sortie_out", "_gate_rules", "_stranded_rule", "player_gate_row", "split_pieces", "stuck_rows", "note_gate_stuck", "note_gate_stuck_cycle", "note_second_way", "_second_way_rule", "WAY_IN_KINDS", "GATE_STUCK_TRIED", "STRANDED_CONFIG", "GATE_PART_RECIPES", "GATE_PART_STUCK_DAYS", "_gate_parts_rule", "_free_gate_levers", "_lever_far_enough", "machinery_wanted", "_lever_hatches_ok", "_link_wanted", "_lever_rule", "_trap_rule", "_gatehouse_rule", "fort_years", "destroyer_gate_due", "gatehouse_wanted", "gatehouse_asked", "GATEHOUSE_WAGON", "_near_spot", "lone_intruders", "few_ordinary", "few_alert_over", "few_near", "hunted_outside", "ai_gates_shut", "_Rec", "_lockdown", "lockdown_released", "lone_alert_over", "_lockdown_ids", "_lockdown_cap_why", "note_lockdown", "quick_clear", "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule"]


# (0.105.26) citizens stranded outside (lua/ai-gates.lua stranded_citizens)
STRANDED_CONFIG = {
    "stranded_after_ticks": 200,         # out this long (~4 game hours) before the rule acts
    "stranded_danger_near": 30,          # an enemy this close to them or the gate: held back
    "gate_close_tiles": 12,              # (0.105.34) an enemy this close to their gate keeps it shut for the stranded
    "stranded_cooldown_ticks": 300,
}
PLANNER_CONFIG.update({k: v for k, v in STRANDED_CONFIG.items() if k not in PLANNER_CONFIG})
STEER_PROTECTED.add("stranded")
AGENDA_THEMES["stranded"] = "bring in the dwarves shut outside"
AGENDA_THEMES["gate_stuck"] = "free the gate the game holds shut"
AGENDA_THEMES["way_in"] = "dig a way in for the dwarves cut off"
AGENDA_THEMES["second_way"] = "a second way to the surface"     # (0.105.33)


def _gate_rules(s: dict, memory, cfg: dict, rules_: dict, any_reach: bool,
                proposals: list, notes: list, traits: dict | None = None) -> None:
    ent = _d(s.get("entrances"))
    now = abs_tick(s)
    letting_in = _stranded_rule(s, cfg, proposals, notes, memory, any_reach)   # (0.105.26; 0.105.32 memory)
    if ent.get("stranded_error"):
        # (0.105.33 merge) the stranded check failed in the game: said as the
        # watcher's failure is, not read as "nobody shut outside"
        # (0.105.35) kept: the AI can't see who is out; said with what it does meanwhile
        notes.append(f"Needs you: the check for citizens shut outside failed ({str(ent['stranded_error'])[:120]}): "
                     "the AI can't see who is left outside this cycle; it checks again next cycle and opens "
                     "the gates it shut as soon as the danger is gone")
    note_second_way(s, memory)                                           # (0.105.33)
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
    if hunted:
        # (0.105.47, R2 item 7) E's doctor died 7 ticks after "only 1 ordinary
        # enemy outside: open the gates": that one is judged (planner_holdfast)
        from planner_holdfast import one_enemy_hold
        hold = one_enemy_hold(s, cfg, memory, traits)
        if hold:
            notes.append(hold["why"])
            hunted = []
    released = lockdown_released(memory)
    from planner_gates_why import release_void, released_text, entrances_not_shutting, cant_text
    if released and release_void(s, cfg, _lockdown_ids(s, traits if traits is not None else _traits(s), cfg)):
        released = False                    # (R32 b) a destroyer, a flier or one among the dwarves: not lifted
    # (0.105.54) the squads out on a sortie: the gates open for them (a
    # gatehouse's drawbridge lowered) while the civilians shelter
    sortie = [] if lone or hunted else sortie_out(s, cfg, memory)
    sortie_still = [] if lone or hunted else _sortie_on(s, cfg, memory,
                                                                sortie if ent.get("armed") and rules_["gate_lever"] else [])
    if sortie_still and any_reach and closable and not ent.get("armed") and rules_["gate_lever"]:
        notes.append(f"the squads are out on a sortie at {len(sortie_still)} enemy/enemies outside, the civilians in "
                     "the shelter: the gates stay open until the squads are back")
    elif any_reach and closable and not ent.get("armed") and rules_["gate_lever"] and (lone or released or hunted):
        notes.append(f"{len(lone)} enemy/enemies inside the fort and none outside: the gates stay open "
                     "(shut, they keep only the others out)" if lone else
                     f"only {len(hunted)} ordinary enemy/enemies outside, and a squad on them or citizens out: "
                     "the gates stay open (shut, they keep the squads in and the citizens out)" if hunted else
                     "the AI's lockdown was lifted (only a few ordinary enemies left, all inside the fort): the "
                     "gates stay open until a new one comes")
    elif any_reach and closable and not ent.get("armed") and rules_["gate_lever"] and not letting_in:
        # (R32 b) every entrance counted, and the ones that can't shut named with why
        cant = entrances_not_shutting(s, memory, cfg, es, off)
        proposals.append(Proposal("gates", {"type": "arm_gates"},
                                  f"a threat can reach the dwarves: watch the {len(closable)} gate(s) of the "
                                  f"{len(es)} entrance(s); each closes once everyone is inside or the danger is "
                                  "12 tiles away" + cant_text(cant), 0))
    elif any_reach and closable and _reach_lift(s, memory, cfg, traits):
        # (0.105.48, K16) the reach alarm came down at its cap: the lockdown lifts too
        proposals.append(Proposal("gates", {"type": "open_gates"}, _reach_lift(s, memory, cfg, traits), 0))
    elif ent.get("armed") and sortie and rules_["gate_lever"]:
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"the squads sortie against {len(sortie)} enemy/enemies outside the gates, the "
                                  "civilians in the shelter: open the gates (a gatehouse's drawbridge lowered) to "
                                  "let them out; shut again once they are back", 0))
    elif ent.get("armed") and (lone or released or hunted):
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"only {len(lone)} enemy/enemies left, inside the fort: open the gates (shut, they "
                                  "keep only the others out)" if lone else
                                  f"only {len(hunted)} ordinary enemy/enemies outside and "
                                  + (f"{int(ent.get('citizens_outside') or 0)} citizen(s) shut out"
                                     if int(ent.get("citizens_outside") or 0) else "a squad sent at them")
                                  + ": open the gates (the squads go out, the citizens come in)" if hunted else
                                  released_text(s, memory, cfg, traits), 0))
    elif not any_reach and ent.get("armed") and all_clear(s, memory, cfg)[0]:
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"no threat for {memory.quiet_cycles} cycles: open the gates", 1))
    elif not any_reach and ent.get("armed") and quick_clear(s, memory, cfg):
        # (0.105.3) A (2 Nov): shut on 9 citizens for a sneaker who hid again
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"{quick_clear(s, memory, cfg)}: open the gates", 0))
    if any_reach and es and not closable and rules_["gate_lever"]:
        # (R32 b) no entrance has a gate to close: said, each with why
        notes.append(f"a threat can reach the dwarves and none of the {len(es)} entrance(s) can shut"
                     + cant_text(entrances_not_shutting(s, memory, cfg, es, off)))
    werr = _d(ent.get("watch_error"))
    if ent.get("armed") and werr.get("error"):
        # (0.104.81, 13c) the gate watcher errors: it closes nothing.
        # (0.105.35, the player: nothing waits for them) the AI shuts the
        # gates an enemy comes within 12 tiles of itself, each cycle
        # (close_threatened_gates), while a threat can reach the dwarves
        notes.append(f"the gate watcher failed {werr.get('n', 1)} time(s) and closes no gate "
                     f"({str(werr['error'])[:120]}): "
                     + ("the AI shuts each gate an enemy comes within 12 tiles of itself, every cycle"
                        if any_reach and closable else "nothing threatens now; the AI shuts the gates itself if "
                        "an enemy comes near"))
        if any_reach and closable and not any(p.rule == "gates" for p in proposals):
            proposals.append(Proposal("gates", {"type": "close_threatened_gates"},
                                      "the gate watcher fails: shut the gates an enemy is within 12 tiles of", 0))
    # (0.105.33 merge) the gates group's report fields, said: a drawbridge that
    # waited too long for a lever that can work it (counted open now), and a
    # door or hatch on a lever shared with another gate (the watcher only
    # locks it, it doesn't pull)
    for e in es:
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        wait = e.get("lever_wait_days")
        if isinstance(wait, int) and not isinstance(wait, bool) and wait > 0 and not e.get("sealed"):
            notes.append(f"{where}: its drawbridge waited {wait} day(s) for a lever that can work it; "
                         "counted as open now")
        if e.get("lock_only") and ent.get("armed"):
            notes.append(f"{where}: its door or hatch shares a lever with another gate; the watcher only "
                         "locks it, it pulls no lever there")
    if stale:
        return                              # building gates waits for the new map
    _gate_parts_rule(s, ent, es, off, proposals, notes, memory)
    _second_way_rule(s, memory, cfg, traits or {}, proposals, notes, rules_)     # (0.105.33; fix33 rules_)
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
        # (0.105.30, construction 3.4) the Hermit hold walls a narrow cavern
        # opening for good (walls, no door), the doors' turn or not
        e_style = cavern_wall_style(e, traits or {}, cfg, memory, style, now) if rules_["fortify_entrances"] else style
        if e_style == "sealed":
            if not fortify_proposed:
                proposals.append(Proposal("fortify", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                      "style": "sealed"},
                                          f"{where} is {e.get('width')} wide and leads to the caverns: wall it up "
                                          "for good (a hidden hold keeps no door there)", 5))
                fortify_proposed = True
            continue
        if e.get("door_spots"):
            if rules_["build_gate_doors"] and spot not in memory.gate_doors_requested and not doors_proposed:
                proposals.append(Proposal("gate_doors", {"type": "build_gate_doors", "entrance_id": e["id"]},
                                          f"{where} has nothing to close it: put {e['door_spots']} door(s) "
                                          "across it", 5))
                doors_proposed = True
        elif (rules_["fortify_entrances"] and (e.get("width") or 0) <= cfg["fortify_max_width"]):
            if not fortify_proposed:
                # (0.105.30) the underground depot's wagon road: a 3-wide drawbridge, never doors
                st = "wagon" if e.get("deep_road") else style
                why_f = (f"{where} is the underground trade depot's wagon road: a 3-wide drawbridge across it "
                         "(wagons roll over it lowered; a door would shut them out)" if e.get("deep_road")
                         else f"{where} is {e.get('width')} wide: wall it down to a {style} gate")
                proposals.append(Proposal("fortify", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                      "style": st}, why_f, 5))
                fortify_proposed = True
        elif not (isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0):
            open_wide.append((e, where))        # (0.105.0) one a cut closes is _gate_cut_rule's (planner_army)
    if rules_["gate_lever"]:
        _lever_rule(s, memory, cfg, es, now, proposals, traits or {})
    if not any_reach and rules_["fortify_entrances"]:
        _trap_rule(s, memory, cfg, es, now, traits or {}, proposals)
        _gatehouse_rule(s, memory, cfg, es, now, traits or {}, proposals)     # (0.105.23)
        try:
            _wings_rule(s, memory, cfg, es, now, traits or {}, proposals, notes)  # (0.105.30) its wing walls
        except Exception as e_:  # noqa: BLE001  (an odd report value: the gates go on)
            notes.append(f"rule _wings_rule failed ({type(e_).__name__}: {str(e_)[:120]}); the others ran")
    if refused:
        def short_why(text: str, n: int = 140) -> str:
            text = str(text)
            return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."
        # (0.105.35) said as what the AI does: it tries again (a stockpile in
        # the way it moves itself, water it looks at)
        notes.append(f"the game refused to build at {len(refused)} entrance(s), e.g. "
                     + "; ".join(f"{w}: {short_why(r)}" for w, r in refused[:2])
                     + ". The AI tries again every 2 weeks (at once when it moved a stockpile in the way)")
    # Entrances doors can't close: one item for all of them (a big old fort
    # can have dozens), the widest named.
    if open_wide:
        open_wide.sort(key=lambda x: -(x[0].get("width") or 0))
        named = "; ".join(f"{w} ({e.get('width')} wide)" for e, w in open_wide[:3])
        surface = sum(1 for e, _ in open_wide if e.get("kind") == "surface")
        head = (f"{len(open_wide)} entrance(s) can't be closed with doors ({surface} to the surface, "
                f"{len(open_wide) - surface} to the caverns or deeper), e.g. {named}")
        if not rules_["fortify_entrances"]:
            # (0.105.35) the player's own switch (on by default): respected, said plainly
            notes.append(f"{head}: walling entrances down is off on the Rules tab, so the AI leaves them open")
        else:
            # (0.105.35) kept: past the AI's walls (and no stair below to cut
            # off), said with what the AI does meanwhile
            ask_player(notes, f"{head}: wider than {cfg['fortify_max_width']} tiles, past what the AI can wall, "
                              "and no stair below them for it to cut off with hatches: they stay open; when "
                              "danger comes through them the AI's alarm and squads answer it there, not a gate")


def _reach_lift(s: dict, memory, cfg: dict, traits) -> str:
    """(0.105.48, K16) planner_alarm.reach_gates_lift for the enemies in reach now."""
    from planner_alarm import reach_gates_lift
    ids = reachable_threats(s, traits if traits is not None else _traits(s), cfg)
    return reach_gates_lift(s, memory, cfg, ids)


GATE_PART_RECIPES = {"hatch": ("hatch_covers", "stone_hatch_cover", "hatch cover"),
                     "door": ("doors", "stone_door", "door")}


GATE_PART_STUCK_DAYS = 7


def _gate_parts_rule(s: dict, ent: dict, es: list, off: int, proposals: list, notes: list, memory=None) -> None:
    """(0.104.105, overnight review) A hatch or door planned at an entrance is
    built only from one the fort has. The hatch over the main stair waited 15
    hours for a hatch cover nobody made; the entrance read "closing" all along,
    so nothing else was tried, and two titans walked in. Parts are ordered at
    the mason's when none is free; a gate still waiting a week with parts free
    is put to the player. (0.105.35) Then its suspended building jobs are
    resumed (free_gate_jobs); still waiting two weeks: Needs you, kept (what
    holds it is past what the AI can see)."""
    from planner_gate_jobs import gate_jobs_paced   # (item20) paced when DF suspends the job again
    parts = _d(ent.get("parts"))
    jobs_freed = False
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
                if not jobs_freed and isinstance(e.get("id"), int) and gate_jobs_paced(s, e, memory):
                    jobs_freed = True       # (item20) resumed lately and suspended again: later
                elif not jobs_freed and isinstance(e.get("id"), int):
                    act = {"type": "free_gate_jobs", "entrance_id": e["id"]}
                    # (0.105.36, D2) the AI fortified it: a piece it planned before v35's records is its own
                    if memory is not None and _near_spot(e, getattr(memory, "gates_fortified", None) or {}):
                        act["ai_plan"] = True
                    proposals.append(Proposal("gate_jobs", act,
                                              f"the {word} planned at {where} has waited {e['closing_days']} days "
                                              f"with {free} free: resume its suspended building job", 3))
                    jobs_freed = True
                if e["closing_days"] >= 2 * GATE_PART_STUCK_DAYS:
                    ask_player(notes, f"a {word} planned at {where} has waited {e['closing_days']} days though "
                                      f"{free} {word}(s) are free, one more was made and the suspended jobs "
                                      "on what the AI planned there resumed: something the AI can't see holds it (the spot blocked?); the AI "
                                      "keeps it planned and maps the entrances again each week")
                else:
                    notes.append(f"a {word} planned at {where} has waited {e['closing_days']} days though "
                                 f"{free} {word}(s) are free: one more is made and its suspended building "
                                 "job resumed")
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
    # (R32 b) every fort, not only one that cares for its machinery (the
    # standing rule: the AI does it itself). B (26 Nov): the gatehouse's hatch
    # had no lever ("levers": []) in a fort of low Engineering, and nothing
    # ever placed one. Still never while a threat can reach the dwarves (the
    # link shuts the hatch; the watcher opens it again)
    hatches = (cfg.get("hatch_levers")
               and not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"))
    ent = _d(s.get("entrances"))
    # (0.105.23) drawbridges before hatches: entrances with a bridge to link come first
    def bridge_first(e):
        wanted = _link_wanted(s, e, None, hatches=False)
        return 0 if wanted else 1
    es = sorted(es, key=bridge_first)
    levers = _free_gate_levers(s)
    if not levers:
        # (0.105.12) a gate no lever works: a lever of its own. (R32 b) a
        # drawbridge too (one whose lever is gone or at the gate: nothing
        # placed a new one), whatever the fort's leanings. Not while an AI
        # gate lever is being built (it goes first: place_gate_lever waits)
        if any(isinstance(g, dict) and g.get("pending") for g in _l(_d(s.get("military")).get("gates"))):
            return
        for e in es:
            bridge_wants = bool(_link_wanted(s, e, None, hatches=False))
            hatch_wants = bool(hatches and e.get("sealed") and _lever_hatches_ok(e, cfg)
                               and _link_wanted(s, e, None, hatches=True))
            if not (bridge_wants or hatch_wants):
                continue
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
            what = "drawbridge" if bridge_wants else "hatch"
            proposals.append(Proposal("gate_lever", {"type": "place_gate_lever", "entrance_id": e["id"]},
                                      f"the {what} at the {e.get('kind')} entrance at elevation {elev} "
                                      f"(x{e.get('x')} y{e.get('y')}) has no lever a dwarf can pull from "
                                      "inside: a lever inside, away from the gate (then linked to it)", 6))
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
        # (0.105.47) Fortification picks the gates: every one when high, the
        # surface and used ones in between, the used ones only when low
        from planner_traplean import trap_gate_why
        lean_why = trap_gate_why(e, traits, memory, cfg)
        if not lean_why:
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
                                  f"{where} has a gate but no traps: {n} {kind} trap(s) just inside it"
                                  + (f" ({lean_why})" if cfg.get("traps_by_fortification", True) else ""), 6))
        free = _d(s.get("entrances")).get("free_mechanisms")
        if isinstance(free, int) and free < n:
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": n - free},
                                      f"{n - free} mechanisms for the traps at {where}", 6, is_order=True))
        return


GATEHOUSE_WAGON = "the embark wagon"     # (0.105.51) a refusal that only waits for the wagon to go


def fort_years(s: dict, memory) -> int | None:
    """(0.105.51) Whole game years since the AI began keeping this fort (the
    chronicle's "founded" entry), or None when unknown."""
    ys = [x.get("y") for x in _l(_d(getattr(memory, "chronicle", None)).get("entries"))
          if isinstance(x, dict) and x.get("k") == "founded" and isinstance(x.get("y"), int)]
    year = _d(s.get("date")).get("year")
    if not ys or not isinstance(year, int):
        return None
    return max(0, year - min(ys))


def destroyer_gate_due(s: dict, memory, cfg: dict) -> str | None:
    """(0.105.51) Why every fort now wants a gate a building destroyer can't
    break, or None: a great danger or building destroyer on the map (anywhere,
    the caverns too), one seen before (last_great_tick), or the fort's
    `destroyer_gate_year`th year (the second). R3, 15 Nov: C's titans walked
    in by the founding stair's bare hatch in its seventh year; nothing but a
    War-hold ever built the gatehouse."""
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if isinstance(t, dict) and (t.get("great_danger") or t.get("destroyer")):
            return f"{str(t.get('name') or 'a great danger')[:60]} is on the map"
    if memory is not None and int(getattr(memory, "last_great_tick", 0) or 0) > 0:
        return "a great danger has come before"
    years = fort_years(s, memory) if memory is not None else None
    if years is not None and years >= int(cfg.get("destroyer_gate_year", 1)):
        return "the fort is in its second year"
    return None


def gatehouse_wanted(s: dict, memory, cfg: dict, e: dict, now: int) -> bool:
    """(0.105.51) May a gatehouse be asked for at this entrance now? The
    founding stair's lid with room for one (or room once the embark wagon is
    gone), none built there, no refusal waiting gate_retry_ticks (one that
    only waited for the wagon: `gatehouse_wagon_retry_ticks`, or at once when
    the wagon is gone)."""
    if not (e.get("sealed") and e.get("kind") == "surface" and e.get("gatehouse") in ("possible", "wagon")):
        return False
    spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
    if _near_spot(e, getattr(memory, "gatehouses", None) or {}):
        return False                            # built here once: the scan sees its bridge, or it was taken down
    why, when = memory.gate_failures.get("gatehouse:" + spot), memory.gate_failure_ticks.get("gatehouse:" + spot)
    if why and isinstance(when, int) and now >= when:
        if str(why).startswith(GATEHOUSE_WAGON):
            if e.get("gatehouse") == "wagon" and now - when < cfg.get("gatehouse_wagon_retry_ticks", 3 * 1200):
                return False
        elif now - when < cfg["gate_retry_ticks"]:
            return False
    return True


def gatehouse_asked(proposals: list) -> bool:
    return any(isinstance(p.action, dict) and p.action.get("type") == "build_gatehouse" for p in proposals)


def _gatehouse_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list) -> None:
    """(0.105.23, 14.1 step 4a) The War-hold's gate as a level: a fort of
    Fortification gatehouse_fortification+ builds a gatehouse in front of
    the founding stair's hatch (lua/ai-gates.lua build_gatehouse): a walled
    corridor on the surface, its floor set with traps in the fort's style
    (cage when it has none), ended by a drawbridge the gate rule then gives
    a lever. Once at a spot, never while a threat can reach the dwarves (the
    caller), one a cycle; a refusal waits gate_retry_ticks. Mechanisms for
    the traps, the lever and its link are ordered when short.
    (0.105.51) Every other fort builds it too, plain (no traps), once
    destroyer_gate_due says so: a hatch or door is no gate against a titan,
    a raised drawbridge is. The embark wagon in its way is taken down first."""
    import defence
    war = (traits.get("fortification", 0) or 0) >= cfg["gatehouse_fortification"]
    due = None if war else destroyer_gate_due(s, memory, cfg)
    if not war and not due:
        return
    if gatehouse_asked(proposals):
        return
    ent = _d(s.get("entrances"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    for e in es:
        if not gatehouse_wanted(s, memory, cfg, e, now):
            continue
        where = f"the founding stair at elevation {(e.get('z') or 0) + off + 1} (x{e.get('x')} y{e.get('y')})"
        wagon = " (the embark wagon in its way is taken down first)" if e.get("gatehouse") == "wagon" else ""
        if war:
            kind = profile_from(traits, memory.culture)["traps"]
            kind = kind if kind in ("cage", "stonefall", "weapon") else "cage"
            n = max(2, min(4, defence.trap_count(traits)))
            why = (f"a fortified fort (Fortification {int(traits.get('fortification', 0)):+d}): a "
                   f"gatehouse in front of the hatch at {where}: a walled corridor with {n} {kind} "
                   "trap(s) and a drawbridge, raised with the hatch when danger comes" + wagon)
        else:
            kind, n = "cage", 0
            why = (f"{due}: a gate a building destroyer can't break, before one comes: a drawbridge at the end of "
                   f"a short walled corridor in front of the hatch at {where} (titans break hatches and doors), "
                   "raised with the hatch when danger comes and lowered after" + wagon)
        # (the plain one is defence, as destroyer_gate's: no hold on new works keeps it back)
        act = {"type": "build_gatehouse", "entrance_id": e["id"], "kind": kind, "count": n}
        if war:
            proposals.append(Proposal("gatehouse", act, why, 6))
        else:
            proposals.append(Proposal("destroyer_gate", act, why, 6))
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
