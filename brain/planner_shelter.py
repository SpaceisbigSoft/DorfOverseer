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
  * `squad_station_spot`: where the squads stand while the dwarves hide (a
    choke on the threat's walk to the shelter, inside the gate it faces,
    off the shelter's levels; else the barracks), read by planner_army's
    `_shelter_squads_rule` (the squads never wait in the civilians' shelter).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal

__all__ = ["choose_shelter", "squad_station_spot", "_shelter_pick_rule", "shelter_levels_now", "plan_ready"]

AGENDA_THEMES.update({"shelter_pick": "the shelter away from the threat",
                      "shelter_flee": "the civilians moved away from a beast inside"})

INF = 10 ** 9


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def plan_ready(s: dict) -> dict:
    """The shelter_plan section when it can be used (a danger on the map), else {}."""
    p = _d(s.get("shelter_plan"))
    if not p or p.get("error") or p.get("danger") is not True:
        return {}
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


def _margin(c: dict) -> int:
    d = _int(c.get("d_threat"))
    if d is None:
        return INF
    return d - (_int(c.get("civ_p90")) or 0)


def _wet(c: dict) -> bool:
    return (_int(c.get("wells")) or 0) > 0 or (_int(c.get("drink")) or 0) > 0


def choose_shelter(plan: dict, cfg: dict, exclude=(), citizens: int | None = None) -> dict | None:
    """The shelter away from the threat: {levels, main, d_threat, civ_p90,
    margin, safe, drink, tiles, way_in, why}, or None with no level to use.

    A level is safe when the threat can't reach it (d_threat None) or its
    walk there is at least `shelter_pick_margin` longer than the civilians'
    (90th percentile): the threat never gets there before them. Of the safe
    ones, the one with drink (a well, or drink lying there) the threat
    reaches last; its neighbours (safe ones, two levels at most away) added,
    the farthest from the threat first, until it holds 2 tiles a civilian
    (50 at least) and drink for them (2 units a civilian, or a well), up to
    `shelter_pick_max_levels` levels. None safe: the one with the most room
    between the threat and the civilians (safe False)."""
    margin_min = int(cfg.get("shelter_pick_margin", 5))
    max_levels = int(cfg.get("shelter_pick_max_levels", 3))
    ex = set(exclude or ())
    cands = [c for c in _l(plan.get("candidates")) if _usable(c) and c["z"] not in ex]
    if not cands:
        return None
    civs = citizens if isinstance(citizens, int) else (_int(plan.get("civilians")) or 0)
    need_tiles = max(50, 2 * civs)
    need_drink = max(1, 2 * civs)

    def safe(c):
        return _margin(c) >= margin_min

    def far(c):
        d = _int(c.get("d_threat"))
        return INF if d is None else d

    def group(main):
        g = [main]
        tiles = _int(main.get("tiles")) or 0
        drink = _int(main.get("drink")) or 0
        wells = _int(main.get("wells")) or 0
        others = sorted((c for c in cands if c is not main and safe(c) and abs(c["z"] - main["z"]) <= 2),
                        key=lambda c: (abs(c["z"] - main["z"]), -far(c)))
        for c in others:
            if len(g) >= max_levels or (tiles >= need_tiles and (wells > 0 or drink >= need_drink)):
                break
            g.append(c)
            tiles += _int(c.get("tiles")) or 0
            drink += _int(c.get("drink")) or 0
            wells += _int(c.get("wells")) or 0
        return g, tiles, drink, wells

    ranked = sorted(cands, key=lambda c: (safe(c), _wet(c), far(c), _int(c.get("tiles")) or 0), reverse=True)
    best = None
    for main in ranked:
        g, tiles, drink, wells = group(main)
        has_drink = wells > 0 or drink > 0
        row = {"levels": sorted(c["z"] for c in g), "main": main["z"], "d_threat": _int(main.get("d_threat")),
               "civ_p90": _int(main.get("civ_p90")), "margin": None if _margin(main) >= INF else _margin(main),
               "safe": safe(main), "drink": has_drink, "drink_short": has_drink and wells == 0 and drink < need_drink,
               "tiles": tiles, "way_in": main.get("way_in"), "chokes": _l(main.get("chokes"))}
        if row["safe"] and has_drink:
            best = row
            break
        if best is None or (row["safe"], row["drink"]) > (best["safe"], best["drink"]):
            best = row
    if best is None:
        return None
    w = _d(best.get("way_in"))
    where = (f"the {w.get('kind') or 'entrance'} at x{w.get('x')} y{w.get('y')} z{w.get('z')}" if w
             else "its way in")
    if best["d_threat"] is None:
        reach = f"the threat can't walk there from {where}"
    else:
        reach = (f"the threat's walk from {where} is {best['d_threat']}, the civilians' "
                 f"{best['civ_p90'] if best['civ_p90'] is not None else '?'} (90%)")
    best["why"] = (f"level{'s' if len(best['levels']) > 1 else ''} {', '.join(str(z) for z in best['levels'])}: "
                   f"the farthest from the threat ({reach})"
                   + ("" if best["drink"] else "; no drink there")
                   + ("" if best["safe"] else "; none the civilians surely reach first"))
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


def _shelter_pick_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """The civilians' shelter away from the threat's way in (rule 1), moved at
    once from a great danger inside the fort that comes close (rule 3), and
    the whole fort again once the danger is gone and the alarm is down."""
    raw = _d(s.get("shelter_plan"))
    if not raw or raw.get("error"):
        return
    cur = _levels(_d(raw.get("current")).get("levels"))
    if raw.get("danger") is not True:
        if cur and not s.get("civ_alert"):
            proposals.append(Proposal("shelter_pick", {"type": "shelter_pick", "clear": True},
                                      "no great danger or siege on the map and the alarm is down: the shelter "
                                      "covers the whole fort again", 4))
        return
    if s.get("civ_alert_shelter") not in (None, "ai"):
        if s.get("civ_alert_shelter") == "player":
            notes.append("a great danger or siege on the map: the civilian alert's burrow is yours, so the AI "
                         "doesn't move the shelter away from the threat")
        return
    plan = raw
    civs = _citizens(s)
    flee = int(cfg.get("shelter_flee_tiles", 20))
    # (rule 3) a great danger inside the fort, close to the shelter by walk
    close = []
    for t in _l(plan.get("dangers")):
        if not isinstance(t, dict) or not t.get("great") or not t.get("inside"):
            continue
        d = _int(t.get("to_shelter"))
        if not cur:
            close.append((0, t))               # the whole fort is the shelter: it is in it
        elif d is not None and d <= flee:
            close.append((d, t))
    if close:
        d, t = min(close, key=lambda x: x[0])
        choice = choose_shelter(plan, cfg, exclude=cur, citizens=civs)
        name = t.get("name") or "a great danger"
        if choice and not _same(choice["levels"], cur):
            where = ("the whole fort" if not cur else f"level{'s' if len(cur) > 1 else ''} "
                     f"{', '.join(str(z) for z in cur)}")
            reason = (f"{name} is inside the fort, {d} steps from the shelter ({where}): the civilians move at once "
                      f"to {choice['why']}")
            proposals.append(Proposal("shelter_flee", _pick_action(choice), reason, 0))
            notes.append(f"the shelter moved: {reason}")
        else:
            notes.append(f"{name} is inside the fort, {d} steps from the shelter, and no other level is farther "
                         "from it: the civilians stay where they are")
        return
    choice = choose_shelter(plan, cfg, citizens=civs)
    if not choice:
        notes.append("a great danger or siege on the map: no level of the fort to shelter in away from it "
                     "(the shelter stays as it is)")
        return
    if not choice["drink"]:
        notes.append(f"a great danger or siege on the map: the level farthest from it ({choice['why']}) holds no "
                     "drink nor well, so the shelter stays as it is (the drink rule brings drink back to it)")
        return
    if _same(choice["levels"], cur):
        return
    # hysteresis: a pick in use is kept unless the new one is clearly farther or the old one unsafe
    walk = _d(plan.get("current_walk"))
    if cur and walk:
        old_d = _int(walk.get("d_threat"))
        old_margin = INF if old_d is None else old_d - (_int(walk.get("civ_p90")) or 0)
        new_d = choice["d_threat"]
        gain = int(cfg.get("shelter_pick_hysteresis", 10))
        if old_margin >= int(cfg.get("shelter_pick_margin", 5)) and (
                old_d is None or (new_d is not None and new_d < old_d + gain)):
            return
    proposals.append(Proposal("shelter_pick", _pick_action(choice),
                              f"a great danger or siege on the map: the civilians' shelter is drawn over {choice['why']}",
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
    for c in sorted(cands, key=lambda c: c["d_threat"]):
        for ch in _l(c.get("chokes")):
            if not isinstance(ch, dict) or any(_int(ch.get(k)) is None for k in ("x", "y", "z")):
                continue
            if (_int(ch.get("to_shelter")) or 0) < min_to or (_int(ch.get("width")) or 0) > max_w:
                continue
            if ch["z"] in on:
                continue
            w = _d(c.get("way_in"))
            return {"x": ch["x"], "y": ch["y"], "z": ch["z"], "kind": "choke",
                    "why": (f"a choke {ch.get('from_src')} steps in from the {w.get('kind') or 'entrance'} at "
                            f"x{w.get('x')} y{w.get('y')} z{w.get('z')}, {ch.get('to_shelter')} from the shelter"
                            if w else f"a choke {ch.get('to_shelter')} steps from the shelter")}
        break                    # only the path the threat takes first
    squads = {q.get("id") for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)}
    bars = [b for b in _l(plan.get("barracks")) if isinstance(b, dict) and b.get("walkable")
            and all(_int(b.get(k)) is not None for k in ("x", "y", "z")) and b["z"] not in on]
    bars.sort(key=lambda b: -len(set(_l(b.get("squads"))) & squads))
    if bars:
        b = bars[0]
        return {"x": b["x"], "y": b["y"], "z": b["z"], "kind": "barracks",
                "why": "no choke between the threat and the shelter: the barracks"}
    return None
