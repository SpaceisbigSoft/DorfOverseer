"""(0.105.47, R2 item 7) Holding fast: the fixes from I7d's titans and thieves.

The violent deaths of 12-14 Nov (forensics I7d, sections 2a and 2c):

1. One ordinary enemy at the gates (`one_enemy_hold`, read by
   planner_gates). `open_gates` opened every gate the watcher shut for "only
   1 ordinary enemy outside": E's doctor died 7 ticks later at the gate, B's
   two recruits sent at a macedwarf thief died there, C lost three within
   1400 ticks. Now that one enemy is judged by the threat judge
   (planner_matchup) against the squads on it, and the gates stay shut while
   it is within `one_enemy_gate_tiles` of a gate or the squads on it don't
   clear `fight_ratio`; citizens shut out are let in by another gate, far
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
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, MULTI_PER_CYCLE, NO_COOLDOWN, Proposal, TICKS_PER_DAY,
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


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


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
    for lst in (_d(t.get("thieves")).get("list"), _d(t.get("interrupters")).get("list"),
                _d(s.get("hunt")).get("targets")):
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
    bar = float(cfg.get("fight_ratio", 2.0))
    names = ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:80]
    if near is not None and near <= tiles:
        why = (f"{names} is {int(near)} tiles from a gate (under {tiles}): the gates stay shut while it is that "
               "close (opened, it walks in on the citizens coming home)")
    elif ratio < bar:
        why = (f"the squads on {names} are too weak for it ({ratio:.1f}x, {bar:g}x needed): the gates stay shut "
               "rather than send them out to it")
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

def _squad_matchup_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """Kill orders on ordinary enemies only with squads strong enough: per
    group of orders on the same enemies, the squads already on them and the
    ones sent this cycle against the targets (planner_matchup). Short of
    `fight_ratio`: the strongest free squads go instead, as few as clear it;
    if none do, all free ones go together at an enemy inside the fort, and
    none at one outside (the gates hold it off)."""
    squads = {q["id"]: q for q in _squads(s)}
    if not squads:
        return proposals
    bar = float(cfg.get("fight_ratio", 2.0))
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
    drop, add = set(), []
    for key, ps in groups.items():
        rows = _target_rows(s, key)
        if not rows or any(t.get("great_danger") for t in rows):
            continue                     # a great danger: fight_or_hide's judgement, not this one
        if len(rows) > int(cfg.get("lone_intruder_max", 2)):
            continue                     # a siege: every able squad goes already (the military rules)
        sent = [squads[p.action["squad_id"]] for p in ps]
        if any(_num(_d(q.get("power")).get("power")) is None for q in sent):
            continue                     # an older bridge: no power to judge by (as before)
        sent_ids = {q["id"] for q in sent}
        on = [q for q in squads.values() if q["id"] not in sent_ids and q.get("ai_orders")
              and _kill_set(q) & key]
        if _ratio(rows, on + sent, memory) >= bar:
            continue
        free = [q for q in squads.values() if q["id"] not in busy and (not q.get("ai_orders") or q.get("sheltering"))
                and not _players(q) and can_fight(q, cfg) and _power(q) > 0]
        pool = sorted({q["id"]: q for q in sent + free}.values(),
                      key=lambda q: (-_ratio(rows, [q], memory), -_power(q), q["id"]))
        party = []
        for q in pool:
            party.append(q)
            if _ratio(rows, on + party, memory) >= bar:
                break
        r_all = _ratio(rows, on + party, memory)
        names = ", ".join(sorted({str(t.get("name") or "an enemy") for t in rows}))[:80]
        alone = ", ".join(str(q.get("name") or q["id"]) for q in sent)
        if r_all < bar and not (set(key) & inside):
            drop.update(id(p) for p in ps)
            notes.append(f"{alone} not sent at {names}: the squads free are too weak for them "
                         f"({r_all:.1f}x, {bar:g}x needed); the gates and the alarm hold them off meanwhile")
            continue
        if {q["id"] for q in party} == sent_ids:
            continue                     # the strongest there are: the orders as the rules gave them
        drop.update(id(p) for p in ps)
        pr = min(p.priority for p in ps)
        first = ps[0]
        for q in party:
            how = ("the strongest free squads together" if r_all >= bar else
                   "every free squad together, still short of the bar (the enemy is inside the fort)")
            add.append(Proposal(first.rule, dict(first.action, squad_id=q["id"]),
                                f"{names}: send {q.get('name') or q['id']} ({how}: {r_all:.1f}x, {bar:g}x needed; "
                                f"{alone} alone was too weak)", pr, getattr(first, "guard", False)))
            busy.add(q["id"])
    if not drop:
        return proposals
    return [p for p in proposals if id(p) not in drop] + add


# --- 3. no recall flapping ---------------------------------------------------------------

def note_kill_orders(s: dict, memory) -> dict:
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
            rec[k] = {"ids": sorted(ids), "since": now}
        else:
            r["ids"] = sorted(ids)
    for k in [k for k in rec if k not in seen]:
        del rec[k]
    return rec


def _kill_hold_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """A squad's kill order kept `kill_hold_ticks` (a game day) at least: a
    calm recall (squad_recall, priority 1 or more) of a squad whose kill
    order is younger is held while one of its targets is still loose on the
    map and the matchup doesn't turn to hide (a great danger: fight_or_hide;
    others: three quarters of `fight_ratio`, as a fight begun goes on)."""
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
            from planner_military import fight_or_hide
            able = [x for x in on if can_fight(x, cfg)] or on
            go = fight_or_hide(s, memory, cfg, great, able)[0]
        else:
            go = _ratio(rows, on, memory) >= float(cfg.get("fight_ratio", 2.0)) * 0.75
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
    if "military" in _d(s.get("_errors")):
        return
    note_kill_orders(s, memory)
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


def note_holdfast(p, r: dict, state: dict, memory, now: int) -> None:
    """After acting (record()): a guard posted, a destroyer's gate tried."""
    if memory is None or not isinstance(getattr(p, "action", None), dict) or p.action.get("dry_run"):
        return
    a = p.action
    if p.rule == GUARD_RULE and a.get("type") == "squad_station" and r.get("ok") is not False:
        _sub(holdfast(memory), "guards")[str(a.get("squad_id"))] = {
            "x": a.get("x"), "y": a.get("y"), "z": a.get("z"), "what": a.get("what"), "tick": now}
    elif p.rule == WALL_RULE and a.get("type") == "fortify_entrance":
        from planner_core import _entrance_spot
        spot = _entrance_spot(state, a.get("entrance_id"))
        if spot:
            _sub(holdfast(memory), "walls")[spot] = {"style": a.get("style"), "tick": now}
