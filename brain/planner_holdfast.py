"""(0.105.47, R2 item 7) Holding fast: the fixes from I7d's titans and thieves.

The violent deaths of 12-14 Nov (forensics I7d, sections 2a and 2c):

1. One ordinary enemy at the gates (`one_enemy_hold`, read by
   planner_gates). `open_gates` opened every gate the watcher shut for "only
   1 ordinary enemy outside": E's doctor died 7 ticks later at the gate, B's
   two recruits sent at a macedwarf thief died there, C lost three within
   1400 ticks. Now that one enemy is judged by the threat judge
   (planner_matchup) against the squads on it, and the gates stay shut while
   it is within `one_enemy_gate_tiles` of a gate or the squads on it don't
   clear the bar (about even odds since 0.105.54: planner_matchup.fight_bar); citizens shut out are let in by another gate, far
   from it, where there is one (`other_gate`).
2. Never recruits alone (`_squad_matchup_filter`, after every rule): a kill
   order on ordinary enemies goes only with squads whose power clears the
   matchup, the strongest free ones first; none at all at an enemy outside
   when even all of them fall short (the gates hold it off), all of them
   together at one inside.
3. Building destroyers (`_destroyer_gate_rule`): a titan or beast that
   smashes buildings counts every gate held only by doors or hatches as
   open (C's titans came in by a stair under a bare hatch while the AI read
   both gates shut). Said; the shelter plan takes such an entrance as the
   threat's way in (lua/ai-shelter-plan.lua) and the shelter's margins keep
   off it (lua/ai-society.lua); the AI puts a drawbridge there, else walls
   it (fortify_entrance), never with citizens shut out nor at the fort's
   only other way.
4. Hidden intruders (`_intruder_guard_rule`): DF reports an intruder nobody
   has seen (planner_threats.unseen_intrusion): a squad stationed on the
   main stair and one at the artifact a thief named (`note_thief_targets`,
   from "You will not stand between me and <artifact>!"), until it is seen
   or gone (B lost 3 on the founding stair in 150 ticks).
5. Squads sent out to eat one at a time while the danger lasts, and back
   once fed (`rest_turn`, `rest_done`, read by planner_army); the station
   on a level with drink where there is one (planner_shelter). C: "held the
   shelter 3 days, out for 2", 20 recalls in 2 hours with the titan inside.
6. No recall flapping (`_kill_hold_filter`, after every rule): a squad's
   kill order is held at least `kill_hold_ticks` (a game day) unless its
   targets are dead, gone or caged or the matchup turns to hide. A: squads
   sent at a titan and recalled "no more threats" 200-400 ticks later while
   it was still about.

The record is memory.holdfast: {kill: {squad id: {ids, since}}, guards:
{squad id: {x, y, z, what, tick}}, named: {tick, name}, walls: {spot:
{style, tick}}}.
"""

from __future__ import annotations

import re

from digest import _d, _l
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, MULTI_PER_CYCLE, NO_COOLDOWN, PLANNER_CONFIG, Proposal, TICKS_PER_DAY,
                          abs_tick, can_fight, player_rules)

__all__ = ["note_holdfast_cycle", "note_holdfast", "one_enemy_hold", "other_gate", "door_only", "building_destroyers", "note_thief_targets",
           "rest_turn", "rest_done", "_squad_matchup_filter", "_kill_hold_filter", "_destroyer_gate_rule",
           "_intruder_guard_rule", "holdfast"]

GUARD_RULE = "intruder_guard"
WALL_RULE = "destroyer_gate"
NO_COOLDOWN.update({GUARD_RULE})
MULTI_PER_CYCLE.update({GUARD_RULE})
LIMIT_EXEMPT.update({GUARD_RULE, WALL_RULE})
AGENDA_THEMES.update({GUARD_RULE: "a squad on the stair while an unseen intruder is about",
                      WALL_RULE: "a gate a building destroyer can't break"})

HUMANOID_SIZE = 70000        # a thief's or visitor's body when the report gives none


from util import int_or_none as _int  # noqa: E402  (r6 c2) was a copy here


from util import float_or_none as _num  # noqa: E402  (r6 c2) was a copy here


def holdfast(memory) -> dict:
    """memory.holdfast, made a dict if it isn't one (an old save)."""
    h = getattr(memory, "holdfast", None) if memory is not None else None
    if not isinstance(h, dict):
        h = {}
        if memory is not None:
            try:
                memory.holdfast = h
            except AttributeError:
                pass
    return h


def _hf(memory) -> dict:
    """memory.holdfast read only (plan() never writes memory)."""
    return _d(getattr(memory, "holdfast", None)) if memory is not None else {}


def _sub(h: dict, k: str) -> dict:
    v = h.get(k)
    if not isinstance(v, dict):
        v = h[k] = {}
    return v


def _threats(s: dict) -> dict:
    return {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and _int(t.get("id")) is not None}


def _squads(s: dict) -> list:
    return [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]


def _power(q: dict) -> float:
    return _num(_d(q.get("power")).get("power")) or 0.0


def _players(q: dict) -> bool:
    """A squad on the player's own orders (the AI leaves it be)."""
    return int(q.get("orders") or 0) > int(q.get("ai_orders") or 0)


def _kill_set(q: dict) -> set:
    return {x for x in _l(q.get("kill_ids")) if _int(x) is not None}


def _dist(a: dict, b: dict):
    """Straight distance: x/y, a level counting 3 (as the bridge's)."""
    if not all(_num(a.get(k)) is not None and _num(b.get(k)) is not None for k in ("x", "y", "z")):
        return None
    return int(max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"])) + 3 * abs(a["z"] - b["z"]))


def _ratio(rows: list, squads: list, memory=None) -> float:
    from planner_matchup import matchup
    from planner_military import fight_key
    ff = _d(getattr(memory, "fight_factor", None)) if memory is not None else {}
    return matchup(rows, squads, lambda t: float(ff.get(fight_key(t)) or 1.0))[0] if squads else 0.0


def _inside_ids(s: dict) -> set:
    out = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if _int(x) is not None}
    th = _d(s.get("threats"))
    out |= {x.get("id") for x in _l(_d(th.get("thieves")).get("list"))
            if isinstance(x, dict) and _int(x.get("id")) is not None and x.get("inside")}
    out |= {x.get("id") for x in _l(_d(th.get("interrupters")).get("list"))
            if isinstance(x, dict) and _int(x.get("id")) is not None}
    out |= {t.get("id") for t in _l(_d(s.get("hunt")).get("targets"))
            if isinstance(t, dict) and _int(t.get("id")) is not None and t.get("region") == "inside"}
    return out


def _target_rows(s: dict, ids) -> list:
    """The rows of these unit ids the report describes: a threat's own row
    (with the bridge's facts), else a thief's, an interrupter's or a hunt
    target's (a humanoid's size where none is given). Ids it doesn't know
    (a citizen killer, a stand-in id) are left out."""
    th = _threats(s)
    extra = {}
    t = _d(s.get("threats"))
    # (0.105.48, K1) and the field watch's wild animals (a wildlife squad judged too)
    for lst in (_d(t.get("thieves")).get("list"), _d(t.get("interrupters")).get("list"),
                _d(s.get("hunt")).get("targets"), _d(s.get("field_watch")).get("wild")):
        for x in _l(lst):
            if isinstance(x, dict) and _int(x.get("id")) is not None:
                extra.setdefault(x["id"], x)
    out = []
    for i in ids:
        if i in th:
            out.append(th[i])
        elif i in extra:
            x = extra[i]
            out.append({"id": i, "name": x.get("name"), "kinds": _l(x.get("kinds")),
                        "size": x.get("size") if _num(x.get("size")) else HUMANOID_SIZE,
                        "great_danger": bool(x.get("great_danger")), "flier": x.get("flier"),
                        "fire_breather": x.get("fire_breather")})
    return out


# --- 1. one ordinary enemy at the gates ------------------------------------------------

def one_enemy_hold(s: dict, cfg: dict, memory=None, traits=None) -> dict | None:
    """The few ordinary enemies (planner_gates.few_ordinary) still outside,
    judged: {ids, rows, near, ratio, tiles, why} when the gates must stay
    shut for them (one within `one_enemy_gate_tiles` of an entrance, or the
    squads with a kill order on them short of `fight_ratio`), else None."""
    from planner_gates import few_ordinary
    try:
        ids = [i for i in few_ordinary(s, cfg, traits) if _int(i) is not None]
    except Exception:  # noqa: BLE001  (an odd report: as before)
        return None
    if not ids:
        return None
    th = _threats(s)
    inside = _inside_ids(s)
    rows = [th[i] for i in ids if i in th and i not in inside]
    if not rows:
        return None
    tiles = int(cfg.get("one_enemy_gate_tiles", 20))
    es = [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)]
    near = None
    for t in rows:
        pos = _d(t.get("pos"))
        ds = [d for d in (_dist(pos, e) for e in es) if d is not None]
        d = min(ds) if ds else _num(t.get("distance_to_nearest_dwarf"))
        if d is not None:
            near = d if near is None else min(near, d)
    want = {t["id"] for t in rows}
    on = [q for q in _squads(s) if q.get("ai_orders") and _kill_set(q) & want]
    ratio = _ratio(rows, on, memory)
    from planner_matchup import strike_bar
    bar, bar_why = strike_bar(rows, cfg, retreating_ids(memory, cfg))     # (0.105.54) about even odds
    names = ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:80]
    if near is not None and near <= tiles:
        why = (f"{names} is {int(near)} tiles from a gate (under {tiles}): the gates stay shut while it is that "
               "close (opened, it walks in on the citizens coming home)")
    elif ratio < bar:
        why = (f"the squads on {names} are too weak for it ({ratio:.1f}x, {bar:g}x needed: {bar_why}): the gates "
               "stay shut rather than send them out to it")
    else:
        return None
    return {"ids": sorted(want), "rows": rows, "near": near, "ratio": ratio, "tiles": tiles, "why": why}


def other_gate(s: dict, hold: dict, not_id=None) -> dict | None:
    """Another entrance shut by the AI, farther than the hold's tiles from
    every enemy held off: the one the shut-out citizens are let in by (the
    farthest), or None."""
    tiles = int(_d(hold).get("tiles") or 20)
    rows = [t for t in _l(_d(hold).get("rows")) if isinstance(t, dict)]
    best, best_d = None, None
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict) or e.get("id") == not_id or not e.get("closed") or not _l(e.get("equipment")):
            continue
        if e.get("kind") == "cavern":
            continue
        ds = [_dist(_d(t.get("pos")), e) for t in rows]
        if any(d is None for d in ds) or not ds:
            continue
        d = min(ds)
        if d > tiles and (best_d is None or d > best_d):
            best, best_d = e, d
    return best


# --- 2. never recruits alone -------------------------------------------------------------

def _free(s: dict, squads: dict, busy: set, cfg: dict, memory=None, militia: bool = False) -> list:
    """The squads free to send: not on another order (or waiting in the
    shelter), not on the player's own orders, able to fight (with `militia`:
    any squad with an armed soldier: an all-out attack), not regrouping after
    a fight that turned bad (planner_matchup.losses_turned) unless all-out."""
    regroup = set() if militia else regrouping(s, memory, cfg)
    out = []
    for q in squads.values():
        if q["id"] in busy or (q.get("ai_orders") and not q.get("sheltering")) or _players(q) or _power(q) <= 0:
            continue
        if str(q["id"]) in regroup:
            continue
        armed = _d(q.get("power")).get("armed")
        if can_fight(q, cfg) or (militia and int(q.get("members") or 0) > 0
                                 and (not isinstance(armed, int) or armed > 0)):
            out.append(q)
    return out


def regrouping(s: dict, memory, cfg: dict) -> set:
    """(0.105.54) Squads that fell back from a fight that turned bad less than
    `fight_regroup_ticks` ago (note_kill_orders): they are not sent again
    before (save an all-out attack); then the odds decide again."""
    if memory is None:
        return set()
    fb = _d(_hf(memory).get("fell_back"))
    span = int(cfg.get("fight_regroup_ticks", TICKS_PER_DAY // 2))
    now = abs_tick(s)
    return {k for k, t in fb.items() if isinstance(t, int) and 0 <= now - t < span}


def _squad_matchup_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """Kill orders on ordinary enemies only with squads strong enough: per
    group of orders on the same enemies, the squads already on them and the
    ones sent this cycle against the targets (planner_matchup). Short of the
    bar (planner_matchup.strike_bar: about even odds since 0.105.54): the
    strongest free squads go instead, as few as clear it; if none do, all
    free ones go together at an enemy inside the fort; at one outside, every
    squad (militia too) once the wait is over (planner_matchup.all_out),
    else none (the gates hold it off)."""
    from planner_matchup import all_out, strike_bar
    squads = {q["id"]: q for q in _squads(s)}
    if not squads:
        return proposals
    proposals = _losses_pass(s, memory, cfg, squads, proposals, notes)
    groups: dict = {}
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        if (a.get("type") != "squad_orders" or not isinstance(a.get("kill"), list) or not a["kill"]
                or a.get("squad_id") not in squads):
            continue
        groups.setdefault(frozenset(i for i in a["kill"] if _int(i) is not None), []).append(p)
    if not groups:
        return proposals
    busy = set()
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        busy.add(a.get("squad_id"))
        busy.update(_l(a.get("squad_ids")))
        busy.update(_l(a.get("squads")))
    inside = _inside_ids(s)
    retreat = retreating_ids(memory, cfg)
    # (0.105.119 item32) a were in beast form: every squad sent goes, whatever
    # the odds (F's Wereskink: three squads' orders dropped at 0.4x while it
    # killed inside; sent only once it had changed back)
    from planner_military_weres import were_ids
    weres = were_ids(s)
    drop, add = set(), []
    for key, ps in groups.items():
        if key & weres:
            continue
        rows = _target_rows(s, key)
        if not rows or any(t.get("great_danger") for t in rows):
            continue                     # a great danger: fight_or_hide's judgement, not this one
        many = len(rows) > int(cfg.get("lone_intruder_max", 2))
        sent = [squads[p.action["squad_id"]] for p in ps]
        if any(_num(_d(q.get("power")).get("power")) is None for q in sent):
            continue                     # an older bridge: no power to judge by (as before)
        sent_ids = {q["id"] for q in sent}
        on = [q for q in squads.values() if q["id"] not in sent_ids and q.get("ai_orders")
              and _kill_set(q) & key]
        bar, bar_why = strike_bar(rows, cfg, retreat)
        if many:
            # (0.105.48, K1) an ambush or a siege is judged too (60 goblins got
            # six squads at 0.7x): the smallest party that clears the bar, the
            # rest kept home; short of it, an opening (a group apart), the
            # ones inside, or all-out once the wait is over (0.105.54)
            _many_matchup(s, memory, cfg, rows, key, ps, sent, on, squads, busy, inside, bar, drop, add, notes,
                          bar_why=bar_why, retreat=retreat)
            continue
        names = ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:80]
        r0 = _ratio(rows, on + sent, memory)
        if r0 >= bar and len(_fit(rows, sent)) == len(sent):
            notes.append(f"{names}: {', '.join(str(q.get('name') or q['id']) for q in sent)} goes ({r0:.1f}x; "
                         f"{bar_why})")
            continue
        free = _free(s, squads, busy, cfg, memory)
        regroup = regrouping(s, memory, cfg)
        party, r_all = _party(rows, on, [q for q in sent if str(q["id"]) not in regroup] + free, bar, memory)
        alone = ", ".join(str(q.get("name") or q["id"]) for q in sent)
        how = None
        if r_all < bar and not (set(key) & inside):
            ao = all_out(s, memory, cfg)
            if ao:
                every = _fit(rows, sent + [q for q in _free(s, squads, busy, cfg, memory, militia=True)
                                           if q["id"] not in sent_ids])
                r_every = _ratio(rows, on + every, memory)
                if r_every >= float(cfg.get("all_out_min_ratio", 0.25)):
                    party, r_all = every, r_every
                    how = f"all-out, every squad: {ao}"
            if how is None:
                drop.update(id(p) for p in ps)
                notes.append(f"{alone} not sent at {names}: the squads free are too weak for them "
                             f"({r_all:.1f}x, {bar:g}x needed: {bar_why}); the gates and the alarm hold them off "
                             "meanwhile")
                _fall_back_lost(s, memory, cfg, rows, key, on + sent, bar, names, add, busy)
                continue
        if how is None and {q["id"] for q in party} == sent_ids:
            continue                     # the strongest there are: the orders as the rules gave them
        drop.update(id(p) for p in ps)
        pr = min(p.priority for p in ps)
        first = ps[0]
        for q in party:
            why = how or ("the strongest free squads together" if r_all >= bar else
                          "every free squad together, still short of the bar (the enemy is inside the fort)")
            add.append(Proposal(first.rule, dict(first.action, squad_id=q["id"]),
                                f"{names}: send {q.get('name') or q['id']} ({why}: {r_all:.1f}x, {bar:g}x needed, "
                                f"{bar_why}; {alone} alone was too weak)", pr, getattr(first, "guard", False)))
            busy.add(q["id"])
    if not drop:
        return proposals
    return [p for p in proposals if id(p) not in drop] + add


def _losses_pass(s: dict, memory, cfg: dict, squads: dict, proposals: list, notes: list) -> list:
    """(0.105.54) The losses guard for a fight going on: an AI squad out on
    ordinary enemies (a great danger is fight_or_hide's, a hunt the hunt
    rule's) that has lost a third of the soldiers it went with, or has half
    of them wounded, falls back (planner_army.fall_back) and regroups; the
    other orders for it this cycle are dropped."""
    if memory is None:
        return proposals
    from planner_matchup import losses_turned
    start = kill_start(memory)
    try:
        from planner_hunt import hunt_rows
        hr = hunt_rows(s)
        hunting = {h.get("squad_id") for h in (hr[2] if hr else [])}
        hunting |= {q.get("id") for q in (hr[1] if hr else []) if isinstance(q, dict) and q.get("hunting") is not None}
    except Exception:  # noqa: BLE001
        hunting = set()
    back, whys = [], []
    for q in squads.values():
        kill = _kill_set(q)
        if (not q.get("ai_orders") or not kill or q.get("sheltering") or _players(q) or q["id"] in hunting
                or str(q["id"]) not in start):
            continue
        rows = _target_rows(s, kill)
        if not rows or any(t.get("great_danger") for t in rows):
            continue
        turned = losses_turned([q], start, cfg)
        if turned:
            back.append(q["id"])
            whys.append(f"{q.get('name') or q['id']}: {turned}")
    if not back:
        return proposals
    from planner_army import fall_back
    keep = [p for p in proposals if not (isinstance(p.action, dict) and p.action.get("squad_id") in back)]
    notes.append("the fight turned bad: " + "; ".join(whys)[:200] + ": they fall back and regroup, and go again "
                 "when the odds return")
    return keep + fall_back(s, cfg, back, "the fight turned bad (" + "; ".join(whys)[:120] + ")", keep)


def _fit(rows: list, qs: list, inside: bool = False) -> list:
    """(0.105.54) The squads fit to go at these threats: against fliers (and
    a fire breather) crossbows only (planner_matchup.fight_bar ranged_only):
    a squad with ranged power or a crossbow uniform. (0.105.83) Inside the
    fort a flier comes down into the corridors to strike, so melee squads go
    too (B's ravens, 23 Nov: three dead, no crossbow squad, 37 soldiers stayed
    home); never at a fire breather."""
    from planner_matchup import fight_bar, fire_breather
    from planner_core import is_ranged
    if not fight_bar(rows, PLANNER_CONFIG)["ranged_only"]:
        return qs
    if inside and not any(fire_breather(t) for t in rows if isinstance(t, dict)):
        return qs
    return [q for q in qs if is_ranged(q) or (_num(_d(q.get("power")).get("ranged_power")) or 0) > 0]


def _party(rows: list, on: list, pool: list, bar: float, memory, inside: bool = False) -> tuple[list, float]:
    """The strongest squads of the pool, as few as clear the bar with the
    ones already on them: (party, its ratio with `on`). Crossbows only
    against fliers (_fit), but inside the fort."""
    pool = _fit(rows, pool, inside)
    pool = sorted({q["id"]: q for q in pool}.values(), key=lambda q: (-_ratio(rows, [q], memory), -_power(q), q["id"]))
    party: list = []
    for q in pool:
        party.append(q)
        if _ratio(rows, on + party, memory) >= bar:
            break
    return party, _ratio(rows, on + party, memory)


def _opening(rows: list, on: list, pool: list, cfg: dict, retreat: set, memory):
    """(0.105.54) A strike below even odds against the whole: a group apart
    from the main body (stragglers, a rearguard, one wandering invader) the
    squads beat at its own bar (lower when it is wounded or falling back).
    The squads already on such a group keep it. (party to add, the group's
    ids, ratio, how) or None; the group most enemies first."""
    from planner_matchup import groups_apart, strike_bar
    best = None
    for g in groups_apart(rows, cfg):
        ids = {t.get("id") for t in g}
        bar_g, why_g = strike_bar(g, cfg, retreat)
        on_g = [q for q in on if _kill_set(q) & ids]
        what = (f"{g[0].get('name') or 'an enemy'} alone, apart from the main body" if len(g) == 1 else
                f"a group of {len(g)} apart from the main body")
        if on_g and _ratio(g, on_g, memory) >= bar_g:
            cand = ([], ids, _ratio(g, on_g, memory), f"{what}: the squads out on it have it ({why_g})", 1)
        else:
            party, r = _party(g, on_g, pool, bar_g, memory)
            if r < bar_g:
                continue
            cand = (party, ids, r, f"{what}: a strike at it ({why_g})", 0)
        if best is None or (cand[4], len(cand[1])) > (best[4], len(best[1])):
            best = cand
    return best[:4] if best else None


def _many_matchup(s, memory, cfg, rows, key, ps, sent, on, squads, busy, inside, bar, drop, add, notes,
                  bar_why: str = "", retreat=None) -> None:
    """(0.105.48, K1) Kill orders on more than `lone_intruder_max` ordinary
    enemies (an ambush, a siege): the smallest party of the strongest squads
    that clears the bar goes (the others stay home: a reserve). (0.105.54)
    Short of it: the ones inside among the civilians are fought whatever the
    odds (the smallest party that clears them, else every squad); once the
    wait is over (planner_matchup.all_out) every squad, militia too, goes at
    them all; else a strike at an opening (_opening); else no sortie (the
    gates and the alarm hold them off)."""
    from planner_matchup import all_out
    retreat = retreat if retreat is not None else retreating_ids(memory, cfg)
    bar_why = bar_why or f"{bar:g}x"
    names = f"{len(rows)} enemies (" + ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:60] + ")"
    sent_ids = {q["id"] for q in sent}
    # (0.105.48 merge) the matchup judged this fight: select()'s free-squad
    # pick must not send out a squad it kept home (a reserve, or all of them)
    try:
        memory.matchup_judged = abs_tick(s)
    except Exception:  # noqa: BLE001
        pass
    if on and _ratio(rows, on, memory) >= bar:
        drop.update(id(p) for p in ps)
        notes.append(f"{names}: the squads already out clear them ({_ratio(rows, on, memory):.1f}x; {bar_why}); "
                     "the others stay home")
        return
    free = _free(s, squads, busy, cfg, memory)
    regroup = regrouping(s, memory, cfg)          # (0.105.54) back from a fight that turned bad: not yet
    pool = [q for q in sent if str(q["id"]) not in regroup] + [q for q in free if q["id"] not in sent_ids]
    party, r = _party(rows, on, pool, bar, memory)
    target_ids = None
    how = f"{len(party)} of the strongest squads clear them, the others stay home"
    if r < bar:
        how = None
        in_rows = [t for t in rows if t.get("id") in inside]
        if in_rows:
            bar_in = min(bar, float(cfg.get("fight_ratio_inside", 1.0)))
            party, r_in = _party(in_rows, [], pool, bar_in, memory, inside=True)
            target_ids = [t["id"] for t in in_rows]
            if r_in >= bar_in:
                how = f"the {len(in_rows)} inside only (the squads are too weak for all of them)"
            else:
                every = pool + [q for q in _free(s, squads, busy, cfg, memory, militia=True)
                                if q["id"] not in {x["id"] for x in pool}]
                every = _fit(in_rows, every, inside=True)
                party, r_in = every, _ratio(in_rows, every, memory)
                how = (f"the {len(in_rows)} inside the fort among the civilians: every squad, whatever the odds")
            r = r_in
        else:
            ao = all_out(s, memory, cfg)
            if ao:
                every = pool + [q for q in _free(s, squads, busy, cfg, memory, militia=True)
                                if q["id"] not in {x["id"] for x in pool}]
                every = _fit(rows, every)
                r_every = _ratio(rows, on + every, memory)
                lo = float(cfg.get("all_out_min_ratio", 0.25))
                if every and r_every >= lo:
                    party, r, how = every, r_every, f"all-out, every squad and the militia: {ao}"
                else:
                    notes.append(f"{names}: the wait is over ({ao}), but every squad together is only "
                                 f"{r_every:.1f}x ({lo:g}x at least for an all-out attack)")
            if how is None:
                opp = _opening(rows, on, pool, cfg, retreat, memory)
                if opp:
                    party, ids, r, how = opp
                    target_ids = sorted(ids, key=str)
                    if not party:
                        drop.update(id(p) for p in ps)
                        notes.append(f"{names}: {how} ({r:.1f}x); the others stay home")
                        return
        if how is None:
            drop.update(id(p) for p in ps)
            notes.append(f"{names}: the squads are too weak for them ({r:.1f}x with every free squad, {bar:g}x "
                         f"needed: {bar_why}) and no group apart to strike at: no sortie; the gates and the alarm "
                         "hold them off and the squads stay in")
            _fall_back_lost(s, memory, cfg, rows, key, on + sent, bar, names, add, busy)
            _siege_hold(s, cfg, rows, pool, names, add, busy, notes, sent_ids, memory)
            return
    if target_ids is None and {q["id"] for q in party} == sent_ids:
        notes.append(f"{names}: the squads sent go ({how}: {r:.1f}x; {bar_why})")
        return                           # the orders as the rules gave them
    drop.update(id(p) for p in ps)
    if not party:
        notes.append(f"{names}: no crossbow squad free to send ({bar_why}); the gates and the alarm hold them off")
        return
    pr = min(p.priority for p in ps)
    first = ps[0]
    for q in party:
        act = dict(first.action, squad_id=q["id"])
        if target_ids:
            act["kill"] = list(target_ids)[:50]
        add.append(Proposal(first.rule, act, f"{names}: send {q.get('name') or q['id']} ({how}: {r:.1f}x; "
                                             f"{bar_why})", pr, getattr(first, "guard", False)))
        busy.add(q["id"])


def siege_gate(s: dict, rows: list, memory=None) -> dict | None:
    """(R29 W2) The surface entrance these enemies come at, from the entrances
    section; None without one. (R32 d) The one most of them are heading to
    (planner_siege_watch.gate_they_come_at), not the one nearest to whichever
    enemy is nearest to any gate (A, 26 Nov: gate 3 held, 31 came at gate 1)."""
    from planner_siege_watch import gate_they_come_at
    return gate_they_come_at(s, rows, memory)[0]


def _siege_hold(s: dict, cfg: dict, rows: list, pool: list, names: str, add: list, busy: set, notes: list,
                sent_ids=(), memory=None) -> None:
    """(R29 W2) An army outside the squads can't beat: no sortie, but the
    free squads hold the gate it comes at (a defend order on the gate guard
    burrow just inside it: ai-society guard_gate), behind the kill zone or
    the gatehouse there, instead of training on wherever they were. Before,
    they stayed where they were (the gate guard, planner_gates, waits until
    no enemy can reach the dwarves: the gates shut). Never for enemies
    inside, never against the Rules' train_squads, never on the player's squads."""
    if not player_rules(s).get("train_squads", True) or not any(t.get("invader") for t in rows):
        return
    if set(t.get("id") for t in rows) & _inside_ids(s):
        return
    gate = siege_gate(s, rows, memory)
    if not gate:
        return
    taken = set(busy) - set(sent_ids)          # the kill orders dropped above free their squads
    qs = [q for q in pool if q["id"] not in taken and not _players(q) and can_fight(q, cfg)
          and not (isinstance(q.get("stationed"), dict) and _dist(_d(q["stationed"]), gate) is not None
                   and _dist(_d(q["stationed"]), gate) <= 6)]
    if not qs:
        return
    kz = {k.get("id"): k for k in _l(_d(s.get("killzones")).get("entrances")) if isinstance(k, dict)}
    st = str(_d(kz.get(gate.get("id"))).get("state") or "")
    behind = ("behind its gatehouse" if st == "gatehouse" else "behind its kill zone" if st in ("standing", "building")
              else "inside it")
    add.append(Proposal("gate_guard", {"type": "guard_gate", "x": gate["x"], "y": gate["y"], "z": gate["z"],
                                       "squads": [q["id"] for q in qs]},
                        f"{names}: too strong to go out at, so {len(qs)} squad(s) hold the gate they come at "
                        f"(x{gate['x']} y{gate['y']}), {behind}; each gate shuts before they are 12 tiles off", 0))
    busy.update(q["id"] for q in qs)
    notes.append(f"{names}: {len(qs)} squad(s) hold the gate x{gate['x']} y{gate['y']} ({behind})")


def _fall_back_lost(s, memory, cfg, rows, key, cands, bar, names, add, busy) -> None:
    """(0.105.48, K16) A fight now lost (more enemies came, squads fell): the
    squads already out on these enemies (an AI kill order on one of them)
    come back to the station or the shelter (planner_army.fall_back),
    whatever the attack policy, when they are short of three quarters of
    the bar against the group they fight (0.105.54: the threats near their
    targets, planner_matchup.clusters), or the fight turned bad (a third of
    their soldiers lost, half wounded: planner_matchup.losses_turned). They
    regroup (`fight_regroup_ticks`), then the odds decide again."""
    from planner_matchup import clusters, losses_turned, strike_bar
    out = {q["id"]: q for q in cands if q.get("ai_orders") and not q.get("sheltering") and not _players(q)
           and _kill_set(q) & set(key) and q["id"] not in _fell_back(add)}
    if not out:
        return
    kill = set()
    for q in out.values():
        kill |= _kill_set(q)
    facing = [t for g in clusters(rows, float(cfg.get("fight_split_tiles", 15)))
              if any(t.get("id") in kill for t in g) for t in g] or rows
    fbar, _ = strike_bar(facing, cfg, retreating_ids(memory, cfg))
    r = _ratio(facing, list(out.values()), memory)
    turned = losses_turned(list(out.values()), kill_start(memory), cfg)
    if not turned and r >= fbar * 0.75:
        return
    from planner_army import fall_back
    why = (f"the fight turned bad ({turned})" if turned else f"they can't win now ({r:.1f}x, {fbar:g}x needed)")
    add.extend(fall_back(s, cfg, sorted(out), f"{names}: the squads out on them fall back: {why}; they go again "
                                              "when the odds return"))
    busy.update(out)


def _fell_back(add: list) -> set:
    """The squads already called back by _fall_back_lost this cycle."""
    got = set()
    for p in add:
        a = p.action if isinstance(p.action, dict) else {}
        if p.rule == "squad_recall":
            got.add(a.get("squad_id"))
            got.update(_l(a.get("squads")))
    return got


# --- 3. no recall flapping ---------------------------------------------------------------

def note_kill_orders(s: dict, memory, cfg: dict | None = None) -> dict:
    """Each squad's kill order and since when (first seen in the report, or a
    new one: no target of the old one in it). Bookkeeping (note_cycle)."""
    rec = _sub(holdfast(memory), "kill")
    now = abs_tick(s)
    seen = set()
    for q in _squads(s):
        k = str(q["id"])
        ids = _kill_set(q)
        if not (q.get("ai_orders") and ids):
            continue
        seen.add(k)
        r = _d(rec.get(k))
        old = {x for x in _l(r.get("ids")) if _int(x) is not None}
        if not r or not (old & ids) or not isinstance(r.get("since"), int):
            # (0.105.54) the soldiers it went with: the losses guard (planner_matchup.losses_turned)
            rec[k] = {"ids": sorted(ids), "since": now, "members": int(q.get("members") or 0)}
        else:
            r["ids"] = sorted(ids)
            if not isinstance(r.get("members"), int):
                r["members"] = int(q.get("members") or 0)      # (a record from before 0.105.54)
    # (0.105.54) a squad whose kill order ended after the fight turned bad (a
    # third of its soldiers lost, half wounded) regroups (regrouping)
    from planner_matchup import losses_turned
    fb = _sub(holdfast(memory), "fell_back")
    by = {str(q["id"]): q for q in _squads(s)}
    for k in [k for k in rec if k not in seen]:
        q, n0 = by.get(k), _d(rec[k]).get("members")
        if q and isinstance(n0, int) and losses_turned([q], {k: n0}, cfg or PLANNER_CONFIG):
            fb[k] = now
        del rec[k]
    for k in [k for k, t in fb.items() if not isinstance(t, int) or not 0 <= now - t < 2 * TICKS_PER_DAY]:
        del fb[k]
    return rec


def _kill_hold_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """A squad's kill order kept `kill_hold_ticks` (a game day) at least: a
    calm recall (squad_recall, priority 1 or more) of a squad whose kill
    order is younger is held while one of its targets is still loose on the
    map and the matchup doesn't turn to hide (a great danger: fight_or_hide;
    others: three quarters of the bar, planner_matchup.strike_bar, as a
    fight begun goes on, unless a third of its soldiers are lost or half
    wounded)."""
    if memory is None or "others_on_map" in _d(s.get("_errors")):
        return proposals
    rec = _d(_hf(memory).get("kill"))
    hold = int(cfg.get("kill_hold_ticks", TICKS_PER_DAY))
    now = abs_tick(s)
    squads = {q["id"]: q for q in _squads(s)}
    th = _threats(s)
    out = []
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        q = squads.get(a.get("squad_id"))
        if not (p.rule == "squad_recall" and a.get("type") == "squad_orders" and a.get("clear") and q
                and p.priority >= 1):
            out.append(p)
            continue
        r = _d(rec.get(str(q["id"])))
        kill = _kill_set(q)
        old = {x for x in _l(r.get("ids")) if _int(x) is not None}
        since = r.get("since") if old & kill else now        # not booked yet: a new order
        if not kill or not isinstance(since, int) or not 0 <= now - since < hold:
            out.append(p)
            continue
        rows = [th[i] for i in kill if i in th]          # loose and alive: the report's threats
        if not rows:
            out.append(p)                                 # dead, gone or caged
            continue
        if any(t.get("fire_breather") is True for t in rows):
            out.append(p)                                 # planner_firebreath's call (no melee at it)
            continue
        great = [t for t in rows if t.get("great_danger")]
        on = [x for x in squads.values() if x.get("ai_orders") and _kill_set(x) & kill]
        if great:
            from planner_matchup import fight_judged      # (r9, audit A6 #13) asks, writes no memory
            able = [x for x in on if can_fight(x, cfg)] or on
            go = fight_judged(s, memory, cfg, great, able)[0]
        else:
            # (0.105.54) about even odds (planner_matchup.strike_bar), a fight
            # begun going on above three quarters of it, unless it turned bad
            from planner_matchup import losses_turned, strike_bar
            bar = strike_bar(rows, cfg, retreating_ids(memory, cfg))[0]
            go = (_ratio(rows, on, memory) >= bar * 0.75
                  and not losses_turned(on, kill_start(memory), cfg))
        if not go:
            out.append(p)                                 # the matchup says hide: back it comes
            continue
        names = ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:60]
        notes.append(f"{q.get('name') or 'a squad'} keeps its kill order on {names} (given "
                     f"{max(0, now - since) // 50} hour(s) ago, held a day unless it is dead, gone or too strong): "
                     f"not called back ({p.reason[:60]})")
    return out


# --- 4. building destroyers ---------------------------------------------------------------

def door_only(e: dict) -> bool:
    """An entrance held only by doors or hatches (no drawbridge in it or in
    front of it): a building destroyer breaks it."""
    eq = [b for b in _l(e.get("equipment")) if isinstance(b, dict)]
    if not eq:
        return False
    if any(b.get("kind") not in ("door", "hatch") for b in eq):
        return False
    return not any(isinstance(b, dict) and b.get("kind") == "bridge" for b in _l(e.get("outer")))


def building_destroyers(s: dict) -> list:
    """Loose building destroyers that can come at the fort: in reach, on the
    surface, or invaders (a cavern beast that can't get up is the seal's)."""
    return [t for t in _threats(s).values() if t.get("destroyer")
            and (t.get("can_reach_dwarves") is True or t.get("layer") == "upper_levels" or t.get("invader"))]


def _destroyer_gate_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A gate held only by doors or hatches while a building destroyer is
    about: said as open (the AI's "shut" doesn't hold it); a drawbridge put
    there (fortify_entrance drawbridge), else walled (sealed) when the fort
    keeps another way in; never with citizens shut out, nor with the
    destroyer within `destroyer_wall_min_tiles` of it. A refusal is said
    once and not asked again while it lasts (record()'s gate_failures)."""
    ds = building_destroyers(s)
    ent = _d(s.get("entrances"))
    if not ds or not ent.get("scanned"):
        return
    es = [e for e in _l(ent.get("entrances")) if isinstance(e, dict) and _int(e.get("id")) is not None]
    weak = [e for e in es if door_only(e) and e.get("kind") != "cavern"]
    if not weak:
        return
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    names = ", ".join(sorted({str(t.get("name") or "a beast") for t in ds}))[:80]
    for e in weak:
        notes.append(f"{names} breaks buildings: the {e.get('kind')} entrance at x{e.get('x')} y{e.get('y')} elevation "
                     f"{(e.get('z') or 0) + off}, held only by a door or hatch, counts as open"
                     + (" though its gate is shut" if e.get("closed") else "")
                     + " (the shelter keeps away from it as the threat's way in)")
    if not player_rules(s).get("fortify_entrances", True) or memory is None:
        return
    stranded = [r for r in _l(ent.get("stranded")) if isinstance(r, dict)]
    if stranded or int(ent.get("citizens_outside") or 0) > 0:
        notes.append("a building destroyer is about and citizens are shut out: no gate is walled or bridged now "
                     "(their way home stays)")
        return
    walls = _d(_hf(memory).get("walls"))
    fails = _d(getattr(memory, "gate_failures", None))
    near_min = int(cfg.get("destroyer_wall_min_tiles", 15))
    for e in weak:
        if e.get("closing"):
            continue                       # being built already
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        dd = [x for x in (_dist(_d(t.get("pos")), e) for t in ds) if x is not None]
        d = min(dd) if dd else None
        if d is not None and d <= near_min:
            notes.append(f"the gate at x{e.get('x')} y{e.get('y')}: the destroyer is {d} tiles from it, too close to "
                         "build there now")
            continue
        # (0.105.51) the founding stair's lid: a hatch can't take a drawbridge
        # nor a wall (C, R3: "the way in at x108 y149 is a stair updown ..."):
        # the gatehouse in front of it is the gate a destroyer can't break
        if e.get("gatehouse") == "standing":
            notes.append(f"the gatehouse at x{e.get('x')} y{e.get('y')} stands: its drawbridge holds once its lever "
                         "is linked (the gate rule links it)")
            continue
        from planner_gates import gatehouse_asked, gatehouse_wanted
        if gatehouse_asked(proposals):
            return
        if gatehouse_wanted(s, memory, cfg, e, abs_tick(s)):
            wagon = (" (the embark wagon in its way is taken down first)"
                     if e.get("gatehouse") == "wagon" else "")
            proposals.append(Proposal(WALL_RULE, {"type": "build_gatehouse", "entrance_id": e["id"], "kind": "cage",
                                                  "count": 0},
                                      f"{names} breaks doors and hatches: the founding stair's hatch at x{e.get('x')} "
                                      f"y{e.get('y')} elevation {(e.get('z') or 0) + off + 1} gets a gatehouse, a "
                                      "drawbridge at the end of a walled corridor (raised with the gates)" + wagon, 1))
            return
        r = _d(walls.get(spot))
        tried = r.get("style")
        when = _d(getattr(memory, "gate_failure_ticks", None)).get(spot)
        failed = spot in fails and isinstance(r.get("tick"), int) and isinstance(when, int) and when >= r["tick"]
        if not tried:
            style = "drawbridge"
        elif tried == "drawbridge" and failed:
            others = [x for x in es if x is not e and x.get("kind") != "cavern"]
            if e.get("lid") or not others:
                notes.append(f"the gate at x{e.get('x')} y{e.get('y')} can't take a drawbridge "
                             f"({str(fails.get(spot))[:100]}) and it is the fort's only or founding way in: "
                             "not walled; the shelter keeps away from it")
                continue
            style = "sealed"
        elif failed:
            notes.append(f"the gate at x{e.get('x')} y{e.get('y')} can be neither bridged nor walled "
                         f"({str(fails.get(spot))[:100]}): the shelter keeps away from it")
            continue
        elif isinstance(r.get("tick"), int) and abs_tick(s) - r["tick"] >= TICKS_PER_DAY:
            style = tried                  # proposed a day ago and nothing came of it (not chosen): again
        else:
            continue
        what = "a drawbridge (raised with the gates)" if style == "drawbridge" else "a wall (the fort keeps its other way in)"
        proposals.append(Proposal(WALL_RULE, {"type": "fortify_entrance", "entrance_id": e["id"], "style": style},
                                  f"{names} breaks doors and hatches: the gate at x{e.get('x')} y{e.get('y')} "
                                  f"elevation {(e.get('z') or 0) + off} gets {what}", 1))
        return


# --- 5. hidden intruders ------------------------------------------------------------------

NAMED_RE = re.compile(r"stand between me and (.+?)[!\"'.]*\s*$", re.IGNORECASE)


def note_thief_targets(state: dict, memory, events: list) -> int:
    """The artifact a thief names ("You will not stand between me and
    <artifact>!"), from the bridge's report events: memory.holdfast.named
    {tick, name}. Returns how many were read."""
    n = 0
    for e in events or []:
        if not isinstance(e, dict) or e.get("kind") != "report":
            continue
        text = " ".join(str(e.get("text") or "").split())
        m = NAMED_RE.search(text)
        if not m:
            continue
        name = m.group(1).strip().strip("\"'!. ")
        if name:
            holdfast(memory)["named"] = {"tick": abs_tick(state), "name": name[:80]}
            n += 1
    return n


def _norm(t) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", str(t or "").lower()).split())


def named_artifact(s: dict, memory) -> dict | None:
    """The artifact row the last thief named (its position known), or None."""
    nm = _d(holdfast(memory).get("named"))
    want = _norm(nm.get("name"))
    if not want:
        return None
    for a in _l(_d(s.get("artifacts")).get("artifacts")):
        if not isinstance(a, dict) or any(_int(a.get(k)) is None for k in ("x", "y", "z")):
            continue
        have = _norm(a.get("name"))
        if have and (have in want or want in have):
            return a
    return None


def _stair_spot(s: dict, memory) -> dict | None:
    """The main stair: the founding stair's entrance (its lid), else the main gate."""
    es = [e for e in _l(_d(s.get("entrances")).get("entrances"))
          if isinstance(e, dict) and all(_int(e.get(k)) is not None for k in ("x", "y", "z"))]
    e = next((e for e in es if e.get("lid")), None)
    if e is None:
        from planner_gates import main_gate
        e = main_gate(s, memory)
    return {"x": e["x"], "y": e["y"], "z": e["z"]} if e else None


def _intruder_guard_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """DF reports an intruder nobody has seen: the strongest free squad on
    the main stair, the next at the artifact a thief named (squad_station),
    until it is seen or gone; then the guards come off (squad_orders clear)
    and the usual rules send them at it."""
    if memory is None or player_rules(s).get("attack_policy") == "never":
        return
    from planner_threats import unseen_intrusion
    rec = unseen_intrusion(s, memory, cfg)
    guards = _d(_hf(memory).get("guards"))
    squads = {q["id"]: q for q in _squads(s)}
    if not rec:
        for k, g in guards.items():
            q = squads.get(int(k)) if str(k).lstrip("-").isdigit() else None
            at = {c: _d(g).get(c) for c in ("x", "y", "z")}
            if q and _d(q.get("stationed")) == at and not _players(q):
                proposals.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                          f"the intruder DF reported has been seen or is gone: "
                                          f"{q.get('name') or 'the squad'} comes off the {_d(g).get('what') or 'post'}",
                                          1))
        return
    spots = []
    st = _stair_spot(s, memory)
    if st:
        spots.append(("main stair", st))
    art = named_artifact(s, memory)
    if art:
        spots.append((f"artifact {str(art.get('name'))[:40]} the thief named",
                      {"x": art["x"], "y": art["y"], "z": art["z"]}))
    if not spots:
        notes.append("DF reports an intruder nobody has seen: no main stair or named artifact known to guard")
        return
    busy = {p.action.get("squad_id") for p in proposals if isinstance(p.action, dict)}
    held = {(g.get("x"), g.get("y"), g.get("z")) for g in (_d(v) for v in guards.values())}
    held |= {(_d(q.get("stationed")).get("x"), _d(q.get("stationed")).get("y"), _d(q.get("stationed")).get("z"))
             for q in squads.values() if q.get("stationed")}
    free = sorted([q for q in squads.values() if not q.get("ai_orders") and not _players(q)
                   and q["id"] not in busy and can_fight(q, cfg) and not int(q.get("parched") or 0)],
                  key=lambda q: (-_power(q), q["id"]))
    for what, at in spots:
        if (at["x"], at["y"], at["z"]) in held:
            continue
        if not free:
            notes.append(f"DF reports an intruder nobody has seen: no free squad to put on the {what}")
            break
        q = free.pop(0)
        hours = max(0, (abs_tick(s) - int(rec.get("tick") or 0)) // 50)
        proposals.append(Proposal(GUARD_RULE, {"type": "squad_station", "squad_id": q["id"], **at, "what": what},
                                  f"DF reported an intruder {hours} game hour(s) ago and nobody has seen it (a thief "
                                  f"hides until it strikes): {q.get('name') or 'a squad'} stands on the {what} at "
                                  f"x{at['x']} y{at['y']} z{at['z']} until it is seen", 0))


# --- 6. out to eat one squad at a time ----------------------------------------------------

def rest_turn(rest: dict, now: int, me) -> bool:
    """Another squad is out eating now (its rest not over): this one waits its turn."""
    return any(str(k) != str(me) and isinstance(t, int) and t > now for k, t in rest.items())


def rest_done(rest: dict, squads: list, now: int, cfg: dict) -> list:
    """The squads out to eat whose soldiers are fed and watered again, out at
    least `post_rest_min_ticks`: their rest ends now (they go back to the
    post rather than wait out `shelter_rest_days`). Returns their ids."""
    by = {str(q.get("id")): q for q in squads if isinstance(q, dict)}
    span = int(cfg.get("shelter_rest_days", 2)) * TICKS_PER_DAY
    least = int(cfg.get("post_rest_min_ticks", 300))
    done = []
    for k, t in list(rest.items()):
        q = by.get(str(k))
        if not q or not isinstance(t, int) or int(q.get("parched") or 0) or q.get("sheltering"):
            continue
        if now - (t - span) >= least:
            del rest[k]
            done.append(q.get("id"))
    return done


# --- bookkeeping (outside plan(): plan() never writes memory) --------------------------

def note_holdfast_cycle(s: dict, memory, cfg: dict) -> None:
    """Before planning (note_cycle): each squad's kill order and since when;
    the guards no longer on their posts forgotten."""
    if memory is None:
        return
    # (R29 W2) the siege watch and its summary (planner_siege_watch): any report with the threats
    from planner_siege_watch import note_siege_watch
    note_siege_watch(s, memory, cfg)
    if "military" in _d(s.get("_errors")):
        return
    note_kill_orders(s, memory, cfg)
    note_siege(s, memory)
    h = holdfast(memory)
    guards = h.get("guards")
    if isinstance(guards, dict) and guards:
        squads = {str(q["id"]): q for q in _squads(s)}
        for k in list(guards):
            g = _d(guards[k])
            at = {c: g.get(c) for c in ("x", "y", "z")}
            q = squads.get(str(k))
            # a day to take the post; then off it means the guard is over
            if not q or (_d(q.get("stationed")) != at and abs_tick(s) - int(g.get("tick") or 0) > TICKS_PER_DAY // 2):
                del guards[k]


def _siege_rows(s: dict) -> list:
    """The threat rows that make a siege: invaders (not a thief) or great
    dangers that can reach the dwarves or are inside."""
    inside = _inside_ids(s)
    return [t for t in _threats(s).values()
            if (t.get("great_danger") or (t.get("invader") and not t.get("thief")))
            and (t.get("can_reach_dwarves") is True or t.get("id") in inside)]


def note_siege(s: dict, memory) -> None:
    """(0.105.54) Bookkeeping: memory.holdfast.siege {since, last, unhappy}
    (since when invaders or a great danger have been in reach without a
    half-day break, and the unhappy share then: planner_matchup.all_out),
    and dist {tick, prev, cur} (each threat's distance to the nearest dwarf
    this cycle and the one before: falling back, planner_matchup.weakened)."""
    if "others_on_map" in _d(s.get("_errors")) or not isinstance(s.get("others_on_map"), dict):
        return
    h = holdfast(memory)
    now = abs_tick(s)
    rows = _siege_rows(s)
    sg = _d(h.get("siege"))
    if rows:
        if not isinstance(sg.get("since"), int) or not isinstance(sg.get("last"), int) \
                or now - sg["last"] > TICKS_PER_DAY // 2 or now < sg["since"]:
            try:
                from planner_society import unhappy_share
                share = round(unhappy_share(s), 3)
            except Exception:  # noqa: BLE001
                share = None
            sg = {"since": now, "unhappy": share}
        sg["last"] = now
        h["siege"] = sg
    elif sg and (not isinstance(sg.get("last"), int) or now - sg["last"] > TICKS_PER_DAY // 2 or now < sg["last"]):
        h.pop("siege", None)
    ds = _d(h.get("dist"))
    cur = {str(t["id"]): int(t["distance_to_nearest_dwarf"]) for t in _threats(s).values()
           if _num(t.get("distance_to_nearest_dwarf")) is not None}
    if ds.get("tick") != now:
        h["dist"] = {"tick": now, "prev": _d(ds.get("cur")), "cur": cur}


def retreating_ids(memory, cfg: dict) -> set:
    """(0.105.54) Threats `fight_retreat_tiles` farther from the dwarves than
    the cycle before (note_siege's record): falling back."""
    ds = _d(_hf(memory).get("dist"))
    prev, cur = _d(ds.get("prev")), _d(ds.get("cur"))
    step = int(cfg.get("fight_retreat_tiles", 5))
    out = set()
    for k, d in cur.items():
        p = prev.get(k)
        if isinstance(p, int) and isinstance(d, int) and d - p >= step:
            try:
                out.add(int(k))
            except ValueError:
                pass
    return out


def kill_start(memory) -> dict:
    """(0.105.54) {squad id (str): members when its kill order began}."""
    return {k: _d(v).get("members") for k, v in _d(_hf(memory).get("kill")).items()
            if isinstance(_d(v).get("members"), int)}


def note_holdfast(p, r: dict, state: dict, memory, now: int) -> None:
    """After acting (record()): a guard posted, a destroyer's gate tried."""
    if memory is None or not isinstance(getattr(p, "action", None), dict) or p.action.get("dry_run"):
        return
    a = p.action
    if a.get("type") == "invite_siege":              # (R29 W2) the invited siege's answer, a journal line
        from planner_siege_watch import note_invite
        note_invite(p, r, state, memory, now)
        return
    if p.rule == GUARD_RULE and a.get("type") == "squad_station" and r.get("ok") is not False:
        _sub(holdfast(memory), "guards")[str(a.get("squad_id"))] = {
            "x": a.get("x"), "y": a.get("y"), "z": a.get("z"), "what": a.get("what"), "tick": now}
    elif p.rule == WALL_RULE and a.get("type") == "fortify_entrance":
        from planner_core import _entrance_spot
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot:
            _sub(holdfast(memory), "walls")[spot] = {"style": a.get("style"), "tick": now}
