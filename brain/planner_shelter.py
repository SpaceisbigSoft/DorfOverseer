"""(0.105.45, Phase 11 brief (c)) Never let a beast reach the civilians' shelter.

F (27 Galena y257): a hill titan killed 42 in the shelter, where the
civilians and two squads waited together. The shelter was the whole fort
(less the margins round the open entrances), so the titan walked into it.

The bridge's `shelter_plan` section (lua/ai-shelter-plan.lua) gives, while a
great danger or a siege is on the map, each danger's way in (the entrance
nearest it, or its own tile inside the fort), the fort's levels as shelters
with the threat's walk and the civilians' walk to each, the drink and wells
on them, the choke points on the threat's way to each, the barracks, and
the AI's pick in use. Here:

  * `choose_shelter`: the level (and its neighbours, for room and drink)
    the threat reaches last, with drink, and never one it reaches before
    the civilians (its walk at least `shelter_pick_margin` more than the
    civilians' 90th percentile); `_shelter_pick_rule` redraws the AI
    shelter over it (`shelter_pick`), says which, why and the way in, and
    the whole fort again once the danger is gone and the alarm down;
  * the check rule: a great danger inside the fort within
    `shelter_flee_tiles` (walk) of the shelter: the civilians moved to the
    next shelter at once (`shelter_flee`, an emergency), a note says so;
  * (0.105.48, K1) a shelter must hold the civilians: room, drink and food
    (`_needs`); none away from the threat that does, within
    `shelter_pick_max_levels` or wider (`shelter_pick_wide_levels`): the
    whole fort rather than one they starve in, and a pick in use that no
    longer holds them is replaced or dropped. The bridge leaves out the
    dangers that can't come (hidden, sealed in a cavern); once none is left
    for `shelter_widen_ticks` the whole fort again, the alarm up or not. A
    plan still being walked (the bridge walks it in slices) or made for
    other ways in moves nothing;
  * (R1 g4) B (y262): the civilians sent down the one central stair a killer
    stood by (14 of 26 dead within a tile of it); A2/E: the flee step sent
    them to levels with 0 drink and 0 food and the ordinary pick undid it
    the next cycle, 18 moves in two minutes. Now every danger inside the fort
    (not only a great one) is measured from its own tile, a level whose way
    there passes an intruder (`civ_exposed`) is never safe, a pick the
    planner marks unsafe is never taken (the civilians stay where they are),
    the flee step takes only a level that holds them (room, drink, food),
    and once the shelter moved it is held `g4_shelter_hold_ticks` for the
    same dangers (one decision a threat);
  * `squad_station_spot`: where the squads stand while the dwarves hide (a
    choke on the threat's walk to the shelter, inside the gate it faces,
    off the shelter's levels; else the barracks), read by planner_army's
    `_shelter_squads_rule` (the squads never wait in the civilians' shelter).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal

__all__ = ["choose_shelter", "shelter_supplies", "squad_station_spot", "_shelter_pick_rule", "shelter_levels_now", "plan_ready"]

AGENDA_THEMES.update({"shelter_pick": "the shelter away from the threat",
                      "shelter_flee": "the civilians moved away from a beast inside"})

INF = 10 ** 9


from util import int_or_none as _int  # noqa: E402  (r6 c2) was a copy here


def plan_ready(s: dict) -> dict:
    """The shelter_plan section when it can be used (a danger on the map), else {}."""
    p = _d(s.get("shelter_plan"))
    if not p or p.get("error") or p.get("danger") is not True:
        return {}
    if p.get("walking"):
        return {}               # (0.105.48, A1) nothing walked whole yet: no levels to go by
    return p


def _levels(v) -> list:
    return sorted({z for z in (_int(x) for x in _l(v)) if z is not None})


def shelter_levels_now(s: dict, proposals: list | None = None) -> list:
    """The shelter's levels: a pick proposed this cycle, else the AI's pick in
    use ([]: the whole fort)."""
    for p in proposals or []:
        a = _d(getattr(p, "action", None))
        if a.get("type") == "shelter_pick":
            return [] if a.get("clear") else _levels(a.get("levels"))
    return _levels(_d(_d(s.get("shelter_plan")).get("current")).get("levels"))


def _usable(c: dict) -> bool:
    return isinstance(c, dict) and _int(c.get("z")) is not None and (_int(c.get("civ_reached")) or 0) > 0


def _d_threat(c: dict):
    """The threat's walk to a level: the nearest way in's or (R1 g4) an
    intruder's own (d_inside); None: none reaches it."""
    ds = [d for d in (_int(c.get("d_threat")), _int(c.get("d_inside"))) if d is not None]
    return min(ds) if ds else None


def _margin(c: dict) -> int:
    d = _d_threat(c)
    if d is None:
        return INF
    return d - (_int(c.get("civ_p90")) or 0)


def _exposed(c: dict) -> int:
    """(R1 g4) Civilians whose walk to this level passes an intruder (the
    bridge's zone round it, its level's stair)."""
    return _int(c.get("civ_exposed")) or 0


def _wet(c: dict) -> bool:
    return (_int(c.get("wells")) or 0) > 0 or (_int(c.get("drink")) or 0) > 0


def _needs(civs: int, cfg: dict) -> dict:
    """(0.105.48, K1) What a shelter must hold for `civs` civilians: room (2
    tiles a civilian, 50 at least), drink (2 units a civilian, or a well) and
    food (`shelter_pick_food_per_civ` a civilian)."""
    return {"tiles": max(50, 2 * civs), "drink": max(1, 2 * civs),
            "food": max(1, int(cfg.get("shelter_pick_food_per_civ", 2)) * civs),
            "per_well": int(cfg.get("g3_civs_per_well", 40) or 0)}     # (r1 g3) a well weighed


def _shortfalls(tiles: int, drink: int, wells: int, food: int, need: dict) -> list:
    """What a shelter lacks for the civilians: [] when it holds them."""
    out = []
    if tiles < need["tiles"]:
        out.append(f"{tiles} tiles (needs {need['tiles']})")
    # (r1 g3) a well gives water to `per_well` civilians, not to any number:
    # E sheltered 80-94 on the level of its one cavern well (R-CE)
    per = need.get("per_well") or 0
    if per > 0 and wells > 0:
        if wells * per * 2 + drink < need["drink"]:
            out.append(f"{drink} drink and {wells} well(s) for {need['drink'] // 2} civilians "
                       f"(a well for every {per}; needs {need['drink']} drink)")
    elif wells == 0 and drink < need["drink"]:
        out.append(f"{drink} drink and no well (needs {need['drink']})")
    if food < need["food"]:
        out.append(f"{food} food (needs {need['food']})")
    return out


def shelter_supplies(plan: dict, levels) -> dict | None:
    """(0.105.48, K1) The room, drink, wells and food on these levels, from the
    plan's levels (candidates and other_levels); None when a level is unread."""
    by = {}
    for c in _l(plan.get("candidates")) + _l(plan.get("other_levels")):
        if isinstance(c, dict) and _int(c.get("z")) is not None:
            by.setdefault(c["z"], c)
    tot = {"tiles": 0, "drink": 0, "wells": 0, "food": 0}
    for z in levels:
        c = by.get(z)
        if c is None:
            return None
        for k in tot:
            tot[k] += _int(c.get(k)) or 0
    return tot


def choose_shelter(plan: dict, cfg: dict, exclude=(), citizens: int | None = None) -> dict | None:
    """The shelter away from the threat: {levels, main, d_threat, civ_p90,
    margin, safe, drink, tiles, food, livable, short, way_in, why}, or None
    with no level to use.

    A level is safe when the threat can't reach it (d_threat None) or its
    walk there is at least `shelter_pick_margin` longer than the civilians'
    (90th percentile): the threat never gets there before them. Of the safe
    ones, the one with drink (a well, or drink lying there) the threat
    reaches last; its neighbours (safe ones, two levels at most away) added,
    the farthest from the threat first, until it holds 2 tiles a civilian
    (50 at least), drink for them (2 units a civilian, or a well) and
    (0.105.48, K1) food for them, up to `shelter_pick_max_levels` levels.
    (0.105.48) A shelter that can't hold them so is looked for again wider
    (`shelter_pick_wide_levels`, four levels away); `livable` False: none
    holds them (the rule then keeps the whole fort). None safe: the one with
    the most room between the threat and the civilians (safe False)."""
    margin_min = int(cfg.get("shelter_pick_margin", 5))
    max_levels = int(cfg.get("shelter_pick_max_levels", 3))
    wide_levels = max(max_levels, min(6, int(cfg.get("shelter_pick_wide_levels", 6))))
    ex = set(exclude or ())
    cands = [c for c in _l(plan.get("candidates")) if _usable(c) and c["z"] not in ex]
    if not cands:
        return None
    civs = citizens if isinstance(citizens, int) else (_int(plan.get("civilians")) or 0)
    need = _needs(civs, cfg)

    def safe(c):
        # (R1 g4) and nobody's way there passes an intruder
        return _margin(c) >= margin_min and _exposed(c) == 0

    def far(c):
        d = _d_threat(c)
        return INF if d is None else d

    def group(main, most, span):
        g = [main]
        tot = {k: _int(main.get(k)) or 0 for k in ("tiles", "drink", "wells", "food")}
        others = sorted((c for c in cands if c is not main and safe(c) and abs(c["z"] - main["z"]) <= span),
                        key=lambda c: (abs(c["z"] - main["z"]), -far(c)))
        for c in others:
            if len(g) >= most or not _shortfalls(tot["tiles"], tot["drink"], tot["wells"], tot["food"], need):
                break
            g.append(c)
            for k in tot:
                tot[k] += _int(c.get(k)) or 0
        return g, tot

    ranked = sorted(cands, key=lambda c: (safe(c), _wet(c), far(c), _int(c.get("tiles")) or 0), reverse=True)
    best = None
    for most, span in ((max_levels, 2), (wide_levels, 4)):
        for main in ranked:
            g, tot = group(main, most, span)
            has_drink = tot["wells"] > 0 or tot["drink"] > 0
            short = _shortfalls(tot["tiles"], tot["drink"], tot["wells"], tot["food"], need)
            row = {"levels": sorted(c["z"] for c in g), "main": main["z"], "d_threat": _d_threat(main),
                   "civ_p90": _int(main.get("civ_p90")), "margin": None if _margin(main) >= INF else _margin(main),
                   "safe": safe(main), "exposed": _exposed(main), "drink": has_drink,
                   "drink_short": has_drink and tot["wells"] == 0 and tot["drink"] < need["drink"],
                   "tiles": tot["tiles"], "food": tot["food"], "livable": not short, "short": short,
                   "way_in": main.get("way_in"), "chokes": _l(main.get("chokes"))}
            if row["safe"] and row["livable"]:
                best = row
                break
            if best is None or (row["livable"], row["safe"], row["drink"]) > (best["livable"], best["safe"], best["drink"]):
                best = row
        if best is not None and best["livable"] and best["safe"]:
            break
    if best is None:
        return None
    w = _d(best.get("way_in"))
    where = ((f"{w.get('name') or 'the intruder'} inside, at x{w.get('x')} y{w.get('y')} z{w.get('z')}"
              if w.get("kind") == "intruder" else
              f"the {w.get('kind') or 'entrance'} at x{w.get('x')} y{w.get('y')} z{w.get('z')}") if w
             else "its way in")
    if best["d_threat"] is None:
        reach = f"the threat can't walk there from {where}"
    else:
        reach = (f"the threat's walk from {where} is {best['d_threat']}, the civilians' "
                 f"{best['civ_p90'] if best['civ_p90'] is not None else '?'} (90%)")
    best["why"] = (f"level{'s' if len(best['levels']) > 1 else ''} {', '.join(str(z) for z in best['levels'])}: "
                   f"the farthest from the threat ({reach})"
                   + ("" if best["drink"] else "; no drink there")
                   + ("" if best["livable"] else f"; for {civs} civilians it holds only {', '.join(best['short'])}")
                   + ("" if best["safe"] else "; none the civilians surely reach first")
                   + (f"; the way there passes an intruder for {best['exposed']} civilian(s)" if best["exposed"] else ""))
    return best


def _citizens(s: dict) -> int | None:
    return _int(_d(s.get("dwarves")).get("total"))


def _same(a: list, b: list) -> bool:
    return sorted(a) == sorted(b)


def _pick_action(choice: dict) -> dict:
    a = {"type": "shelter_pick", "levels": choice["levels"], "why": choice["why"][:200]}
    w = _d(choice.get("way_in"))
    if w:
        a["way_in"] = {k: w.get(k) for k in ("id", "kind", "x", "y", "z") if w.get(k) is not None}
    return a


def _now(s: dict):
    try:
        from planner_core import abs_tick
        return abs_tick(s)
    except Exception:  # noqa: BLE001
        return None


def _danger_ids(plan: dict) -> list:
    return sorted(str(t.get("id")) for t in _l(plan.get("dangers")) if isinstance(t, dict) and t.get("id") is not None)


def _hold_book(memory, cur: list, raw: dict, now) -> dict:
    """(R1 g4) memory.shelter_hold {levels, tick, ids}: the shelter as last
    seen, and since when (the tick it changed: the pick's own, else the cycle
    the change was first seen). A change is seen in the report, so a move
    proposed and not made holds nothing."""
    if memory is None:
        return {}
    h = getattr(memory, "shelter_hold", None)
    if not isinstance(h, dict):
        h = {}
    if "levels" not in h or sorted(_l(h.get("levels"))) != sorted(cur):
        tick = _int(_d(raw.get("current")).get("tick")) if cur else None
        if "levels" in h and tick is None:
            tick = now                    # a change (a clear) seen this cycle
        h = {"levels": list(cur), "tick": tick, "ids": _danger_ids(raw)}
        try:
            memory.shelter_hold = h
        except Exception:  # noqa: BLE001
            pass
    return h


def _held(h: dict, raw: dict, now, cfg: dict) -> int | None:
    """(R1 g4) Ticks left of the hold on the shelter (one decision a threat):
    None when not held (no move seen yet, the hold over, or a danger come
    since that wasn't there when it moved)."""
    tick = _int(h.get("tick")) if isinstance(h, dict) else None
    if tick is None or not isinstance(now, int):
        return None
    left = int(cfg.get("g4_shelter_hold_ticks", 1200)) - (now - tick)
    if left <= 0:
        return None
    if set(_danger_ids(raw)) - set(_l(h.get("ids"))):
        return None                       # a new danger: a new decision
    return left


def _shelter_pick_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """The civilians' shelter away from the threat's way in (rule 1), moved at
    once from a great danger inside the fort that comes close (rule 3), and
    the whole fort again once the danger is gone and the alarm is down."""
    raw = _d(s.get("shelter_plan"))
    if not raw or raw.get("error"):
        return
    cur = _levels(_d(raw.get("current")).get("levels"))
    if raw.get("danger") is not True:
        # (0.105.48, K1) the whole fort again once no danger that can come is
        # on the map: at once with the alarm down, else after
        # `shelter_widen_ticks` (an alarm held up for something small kept
        # the War-hold's 34 on one level for good)
        calm = _int(raw.get("calm_ticks"))
        widen = int(cfg.get("shelter_widen_ticks", 600))
        if cur and not s.get("civ_alert"):
            proposals.append(Proposal("shelter_pick", {"type": "shelter_pick", "clear": True},
                                      "no great danger or siege on the map and the alarm is down: the shelter "
                                      "covers the whole fort again", 4))
        elif cur and calm is not None and calm >= widen:
            proposals.append(Proposal("shelter_pick", {"type": "shelter_pick", "clear": True},
                                      f"no great danger or siege that can come has been on the map for {calm} ticks: "
                                      "the shelter covers the whole fort again (the alarm, if up, is for "
                                      "something else)", 4))
        return
    if s.get("civ_alert_shelter") not in (None, "ai"):
        if s.get("civ_alert_shelter") == "player":
            notes.append("a great danger or siege on the map: the civilian alert's burrow is yours, so the AI "
                         "doesn't move the shelter away from the threat")
        return
    plan = raw
    civs = _citizens(s)
    # (0.105.48, A1) the plan is walked in slices: none whole yet, or one made
    # for other ways in or another pick: nothing is moved on it
    if raw.get("walking") or raw.get("stale"):
        notes.append("a great danger or siege on the map: the shelter plan is still being walked (the shelter "
                     "stays as it is meanwhile)")
        return
    flee = int(cfg.get("shelter_flee_tiles", 20))
    now = _now(s)
    book = _hold_book(memory, cur, raw, now)
    held = _held(book, raw, now, cfg)
    # (rule 3) a danger inside the fort, close to the shelter by walk: (R1 g4)
    # any danger (an invader, a thief, a beast), not only a great one: B's
    # lone killer was an invader
    close = []
    for t in _l(plan.get("dangers")):
        if not isinstance(t, dict) or not t.get("inside"):
            continue
        d = _int(t.get("to_shelter"))
        if not cur:
            close.append((0, t))               # the whole fort is the shelter: it is in it
        elif d is not None and d <= flee:
            close.append((d, t))
    if close:
        d, t = min(close, key=lambda x: x[0])
        name = t.get("name") or "a danger"
        where = ("the whole fort" if not cur else f"level{'s' if len(cur) > 1 else ''} "
                 f"{', '.join(str(z) for z in cur)}")
        # (R1 g4) held: the shelter was set for these dangers a moment ago.
        # Only a picked shelter the intruder comes close to is fled again
        # (with the whole fort as the shelter it is always "in it": A2's flip)
        if held is not None and not cur:
            notes.append(f"{name} is inside the fort; the shelter ({where}) was set for it {now - book['tick']} "
                         f"ticks ago and is held {held} more: the civilians stay where they are")
            return
        choice = choose_shelter(plan, cfg, exclude=cur, citizens=civs)
        # (R1 g4) the flee step takes only what the ordinary pick would keep:
        # a level the civilians surely reach first, whose way there passes no
        # intruder, and that holds them (room, drink, food). Else they stay
        # where they are, behind the doors (A2: 97 civilians sent to levels
        # with 0 drink and 0 food, the next cycle undoing it)
        why_not = None
        if not choice or _same(choice["levels"], cur):
            why_not = "no other level is farther from it"
        elif not choice["safe"]:
            why_not = f"no level the civilians surely reach first without passing it ({choice['why']})"
        elif not choice["livable"] or not choice["drink"]:
            why_not = f"no level away from it holds the civilians ({choice['why']})"
        if why_not is None:
            reason = (f"{name} is inside the fort, {d} steps from the shelter ({where}): the civilians move at once "
                      f"to {choice['why']}")
            proposals.append(Proposal("shelter_flee", _pick_action(choice), reason, 0))
            notes.append(f"the shelter moved: {reason}")
        else:
            notes.append(f"{name} is inside the fort, {d} steps from the shelter ({where}), and {why_not}: "
                         "the civilians stay where they are")
        return
    choice = choose_shelter(plan, cfg, citizens=civs)
    if not choice:
        notes.append("a great danger or siege on the map: no level of the fort to shelter in away from it "
                     "(the shelter stays as it is)")
        return
    # (0.105.48, K1) the pick in use must still hold the civilians
    need = _needs(civs if isinstance(civs, int) else (_int(plan.get("civilians")) or 0), cfg)
    cur_sup = shelter_supplies(plan, cur) if cur else None
    cur_short = (_shortfalls(cur_sup["tiles"], cur_sup["drink"], cur_sup["wells"], cur_sup["food"], need)
                 if cur_sup else [])
    # (R1 g4) held: one decision a threat. Only a pick in use that no longer
    # holds the civilians is changed meanwhile
    if held is not None and not cur_short:
        if not _same(choice["levels"], cur):
            notes.append(f"a great danger or siege on the map: the shelter was set for it {now - book['tick']} "
                         f"ticks ago and is held {held} more (the civilians aren't moved back and forth)")
        return
    if not choice["livable"]:
        # no levels away from it hold them: the whole fort (a bigger shelter)
        # rather than one they starve or go thirsty in
        if cur:
            proposals.append(Proposal("shelter_pick", {"type": "shelter_pick", "clear": True},
                                      f"a great danger or siege on the map, but no levels away from it can hold the "
                                      f"civilians ({choice['why']}): the shelter covers the whole fort again", 0))
        else:
            notes.append(f"a great danger or siege on the map: no levels away from it can hold the civilians "
                         f"({choice['why']}), so the shelter stays the whole fort")
        return
    if not choice["drink"]:
        notes.append(f"a great danger or siege on the map: the level farthest from it ({choice['why']}) holds no "
                     "drink nor well, so the shelter stays as it is (the drink rule brings drink back to it)")
        return
    if not choice["safe"]:
        # (R1 g4) never a pick the planner itself marks unsafe (B: level 163,
        # "none the civilians surely reach first", taken; they walked down the
        # killer's stair). A pick in use that no longer holds them: the whole
        # fort (a bigger burrow: nobody is sent walking for it)
        if cur and cur_short:
            proposals.append(Proposal("shelter_pick", {"type": "shelter_pick", "clear": True},
                                      f"a great danger or siege on the map: the shelter in use holds only "
                                      f"{', '.join(cur_short)} and no level away from it is safe to walk to "
                                      f"({choice['why']}): the shelter covers the whole fort again", 0))
        else:
            notes.append(f"a great danger or siege on the map: no level the civilians surely reach first without "
                         f"passing an intruder ({choice['why']}): the civilians stay where they are, behind the doors")
        return
    if _same(choice["levels"], cur):
        return
    # hysteresis: a pick in use is kept unless the new one is clearly farther,
    # the old one unsafe, or (0.105.48) the old one can't hold the civilians
    walk = _d(plan.get("current_walk"))
    if cur and walk and not cur_short:
        old_d = _d_threat(walk)
        old_margin = INF if old_d is None else old_d - (_int(walk.get("civ_p90")) or 0)
        new_d = choice["d_threat"]
        gain = int(cfg.get("shelter_pick_hysteresis", 10))
        if old_margin >= int(cfg.get("shelter_pick_margin", 5)) and _exposed(walk) == 0 and (
                old_d is None or (new_d is not None and new_d < old_d + gain)):
            return
    proposals.append(Proposal("shelter_pick", _pick_action(choice),
                              f"a great danger or siege on the map: the civilians' shelter is drawn over {choice['why']}"
                              + (f" (the shelter in use holds only {', '.join(cur_short)})" if cur_short else ""),
                              0))


def squad_station_spot(s: dict, cfg: dict, proposals: list | None = None) -> dict | None:
    """Where the squads stand while the dwarves hide: {x, y, z, kind, why}.
    A choke on the threat's walk to the shelter (the nearest shelter level's
    path), at least `shelter_choke_min_tiles` from it, no wider than
    `shelter_choke_max_width`, off the shelter's levels: the first from the
    threat's side (just inside the gate it faces). Else the barracks (off
    the shelter's levels; the squads' own first). None: neither."""
    plan = plan_ready(s)
    if not plan:
        return None
    levels = shelter_levels_now(s, proposals)
    on = set(levels)
    cands = [c for c in _l(plan.get("candidates")) if isinstance(c, dict) and _int(c.get("z")) is not None]
    if on:
        cands = [c for c in cands if c["z"] in on]
    cands = [c for c in cands if _int(c.get("d_threat")) is not None]
    min_to = int(cfg.get("shelter_choke_min_tiles", 10))
    max_w = int(cfg.get("shelter_choke_max_width", 4))
    # (0.105.47, R2 item 7) the post on a level with drink (a well, or drink
    # lying there) where the threat's path has one: C's squads left the
    # shelter every few hours to eat and drink while the titan was inside
    wet = {_int(c.get("z")) for c in _l(plan.get("candidates")) + _l(plan.get("other_levels"))
           if isinstance(c, dict) and ((_int(c.get("drink")) or 0) > 0 or (_int(c.get("wells")) or 0) > 0)}
    for c in sorted(cands, key=lambda c: c["d_threat"]):
        ok = []
        for ch in _l(c.get("chokes")):
            if not isinstance(ch, dict) or any(_int(ch.get(k)) is None for k in ("x", "y", "z")):
                continue
            if (_int(ch.get("to_shelter")) or 0) < min_to or (_int(ch.get("width")) or 0) > max_w:
                continue
            if ch["z"] in on:
                continue
            ok.append(ch)
        if ok:
            ch = next((x for x in ok if x["z"] in wet), ok[0])
            w = _d(c.get("way_in"))
            return {"x": ch["x"], "y": ch["y"], "z": ch["z"], "kind": "choke", "drink": ch["z"] in wet,
                    "why": (f"a choke {ch.get('from_src')} steps in from the {w.get('kind') or 'entrance'} at "
                            f"x{w.get('x')} y{w.get('y')} z{w.get('z')}, {ch.get('to_shelter')} from the shelter"
                            if w else f"a choke {ch.get('to_shelter')} steps from the shelter")
                    + ("; drink on its level" if ch["z"] in wet else "")}
        break                    # only the path the threat takes first
    squads = {q.get("id") for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)}
    bars = [b for b in _l(plan.get("barracks")) if isinstance(b, dict) and b.get("walkable")
            and all(_int(b.get(k)) is not None for k in ("x", "y", "z")) and b["z"] not in on]
    bars.sort(key=lambda b: (-len(set(_l(b.get("squads"))) & squads), b["z"] not in wet))
    if bars:
        b = bars[0]
        return {"x": b["x"], "y": b["y"], "z": b["z"], "kind": "barracks", "drink": b["z"] in wet,
                "why": "no choke between the threat and the shelter: the barracks"
                + ("; drink on its level" if b["z"] in wet else "")}
    return None
