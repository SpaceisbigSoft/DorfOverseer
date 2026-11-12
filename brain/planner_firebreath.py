"""(0.105.40b) Fire breathers: no melee squad goes at a creature that breathes,
spits or hurls fire.

A dragon's breath (or a fire imp's fireball, a generated beast's fire jet)
sets a whole squad alight in its armour before the soldiers land a blow; the
fort's squads were sent at one like at any other enemy. The bridge marks
such a threat `fire_breather` (lua/ai-threats.lua fire_breath_of, called from
the others_on_map section in lua/ai-bridge.lua: its
caste's natural abilities with a DRAGONFIRE / FIREJET / FIREBALL flow, or
the IMMOLATE caste flag; one answer per race and caste) with `fire_how`
('breath', 'jet', 'fireball', 'burns').

  * no melee kill order names it: _military_rules leaves it out of its
    targets and of the fight-or-hide weighing (planner_military), and this
    rule takes it off any other squad order proposed this cycle (a lone
    intruder's, a thief's, a second wave's); a melee squad already on it is
    called back; a gate guard of melee squads isn't posted against it;
  * crossbow squads only, and only from inside: only at one that can reach
    the dwarves, while the AI's gates are shut, it is not inside the fort,
    and it stands at the fort's walls (others_on_map.intruders_at_walls, by
    the gate scan's map, read only when a fire breather is about: at a shut
    door, before a raised bridge, in the tunnel in front of a gate). One that "can reach the dwarves" behind shut gates
    away from the walls has a way in nobody mapped, and the marksdwarves
    would walk out to it along that leaky path: no squad then (nor without
    the gate scan's map). Else no squad at all;
  * nor while it stands out in evil weather (planner_weather): the crossbows
    stay in the shelter with the others, as the weather filter would leave
    them (one note says so);
  * the dwarves hide: the alarm and the shut gates are the existing
    machinery (it can reach the dwarves: reachable_threats); it is never a
    "lone intruder" or one of "a few ordinary enemies" (planner_gates), so
    the gates and the alarm aren't lifted early for it, and the squads wait
    in the shelter with the civilians (planner_army hiding);
  * the fire it starts is the fire guard's (planner_threats _fire);
  * a note says why.

The Rules tab's "attack everything" is the player's: then the squads go as
before, and the note says what they face. Without the flag (an older bridge,
no fire breather about) nothing here changes a decision.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, can_fight, is_ranged, player_rules, reachable_threats, _traits

__all__ = ["fire_breathers", "fire_ranged_ok", "_fire_breather_rule", "FIRE_HOW"]

FIRE_HOW = {"breath": "breathes fire", "jet": "spits jets of fire", "fireball": "hurls fireballs",
            "burns": "burns to the touch"}


def fire_breathers(s: dict) -> dict:
    """{id: threat row} of the threats on the map the bridge marks fire_breather."""
    return {t["id"]: t for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and t.get("fire_breather") is True and t.get("id") is not None}


def fire_ranged_ok(s: dict, memory, t: dict, weather_out: set | None = None) -> str:
    """Why crossbows may NOT shoot at this fire breather now ("" if they
    may): only from inside the fort, with the AI's gates shut (the soldiers
    can't walk out to it), the creature not inside but at the fort's walls
    (never out along a path the gates don't close), and not standing in
    evil weather (`weather_out`: planner_weather.weather_outside)."""
    from planner_gates import ai_gates_shut
    ent = _d(s.get("entrances"))
    inside = {x for x in _l(ent.get("intruders_inside")) if isinstance(x, int)}
    if t.get("id") in inside:
        return "it is inside the fort"
    if not ai_gates_shut(s, memory):
        return "the gates are open (they would go out to it)"
    if weather_out and t.get("id") in weather_out:
        return "it stands out in the evil weather (the squads wait inside with the rest)"
    walls = _d(s.get("others_on_map")).get("intruders_at_walls")      # (fix41-ff) read with the fire breathers
    if walls is None:
        walls = ent.get("intruders_at_walls")
    if not isinstance(walls, list):
        return "no map of the fort's walls yet (the crossbows could walk out to it along a way the gates don't close)"
    if t.get("id") not in walls:
        return ("it isn't at the fort's walls (it reaches the dwarves some way the gates don't close: the "
                "crossbows would walk out to it)")
    return ""


def _who(t: dict) -> str:
    return f"{t.get('name') or 'a creature'} ({FIRE_HOW.get(t.get('fire_how'), 'breathes fire')})"


def _fire_breather_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    fb = fire_breathers(s)
    if not fb:
        return
    policy = player_rules(s)["attack_policy"]
    reach = set(reachable_threats(s, _traits(s), cfg))
    squads = {q.get("id"): q for q in _l(_d(s.get("military")).get("squads"))
              if isinstance(q, dict) and q.get("id") is not None}
    about = [t for i, t in fb.items() if i in reach or any(
        i in _l(p.action.get("kill")) for p in proposals if p.action.get("type") == "squad_orders")
        or any(i in _l(q.get("kill_ids")) for q in squads.values() if q.get("ai_orders"))]
    if policy == "all":
        if about:
            notes.append(f"{', '.join(_who(t) for t in about[:3])}: the squads go at it all the same (Rules tab: "
                         "attack everything); soldiers in melee rarely live through fire")
        return
    from planner_military import called_off_ids
    off = called_off_ids(s, memory)
    try:
        from planner_weather import weather_outside
        wx = weather_outside(s, cfg)
    except Exception:  # noqa: BLE001  (no weather word: as before)
        wx = set()
    why_not = {i: fire_ranged_ok(s, memory, t, wx) for i, t in fb.items()}
    may_shoot = {i for i in fb if policy != "never" and not why_not[i] and i not in off}

    def allowed(q, i):
        return q is not None and is_ranged(q) and i in may_shoot

    kept, dropped = [], []
    gate_inv = {t.get("id") for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)
                and t.get("invader") and not t.get("can_reach_dwarves") and t.get("layer") in (None, "surface")}
    for p in proposals:
        a = p.action
        if a.get("type") == "squad_orders" and isinstance(a.get("kill"), list):
            q = squads.get(a.get("squad_id"))
            bad = [i for i in a["kill"] if i in fb and not allowed(q, i)]
            if bad:
                rest = [i for i in a["kill"] if i not in bad]
                if not rest:
                    dropped.append(p)
                    continue
                p.action = dict(a, kill=rest)
                p.reason += " (not the fire breather: no melee squad goes at it)"
        elif a.get("type") == "guard_gate" and set(fb) & gate_inv:
            # a fire breather among those at the gate: only crossbows hold it
            keep = [x for x in _l(a.get("squads")) if is_ranged(_d(squads.get(x)))]
            if not keep:
                dropped.append(p)
                continue
            if keep != _l(a.get("squads")):
                p.action = dict(a, squads=keep)
                p.reason += " (crossbow squads only: a fire breather is among them)"
        kept.append(p)
    # a squad already on a fire breather it may not fight, with no new order
    # this cycle (a new kill order replaces the old one): called back
    ordered = {p.action.get("squad_id") for p in kept if p.action.get("type") == "squad_orders"}
    for q in squads.values():
        kill = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
        bad = [i for i in kill if i in fb and not allowed(q, i)]
        if q.get("ai_orders") and bad and q["id"] not in ordered:
            why = (f"the crossbows don't shoot at it now: {why_not[bad[0]]}" if is_ranged(q) and why_not.get(bad[0])
                   else "no melee squad goes at a fire breather")
            kept.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                 f"{_who(fb[bad[0]])} is no foe for {q.get('name') or 'the squad'}: it comes back "
                                 f"({why})", 0))
            ordered.add(q["id"])
    # crossbows from inside, at the ones they may shoot that no crossbow squad is on
    on = set()
    for q in squads.values():
        if is_ranged(q) and q.get("ai_orders") and not q.get("sheltering"):
            on |= {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
    for p in kept:
        if p.action.get("type") == "squad_orders" and is_ranged(_d(squads.get(p.action.get("squad_id")))):
            on |= set(_l(p.action.get("kill")))
    shoot = [i for i in sorted(may_shoot, key=str) if i in reach and i not in on]
    sent = None
    free = [q for q in squads.values() if is_ranged(q) and can_fight(q, cfg) and q["id"] not in ordered
            and (not q.get("ai_orders") or q.get("sheltering"))]
    if shoot and free:
        sent = max(free, key=lambda q: (int(_d(q.get("power")).get("armed") or 0), int(q.get("members") or 0)))
        kept.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": sent["id"], "kill": shoot[:10]},
                             f"{', '.join(_who(fb[i]) for i in shoot[:3])}: {sent.get('name') or 'the crossbow squad'} "
                             "shoots at it from inside the shut gates (no melee squad goes at a fire breather)", 0))
        ordered.add(sent["id"])
    # the crossbows sent (or on it) don't wait in the shelter
    shooting = {p.action.get("squad_id") for p in kept if p.action.get("type") == "squad_orders"
                and is_ranged(_d(squads.get(p.action.get("squad_id")))) and set(_l(p.action.get("kill"))) & may_shoot}
    shooting |= {q["id"] for q in squads.values() if is_ranged(q) and q.get("ai_orders") and not q.get("sheltering")
                 and set(_l(q.get("kill_ids"))) & may_shoot}
    if shooting:
        out = []
        for p in kept:
            if p.action.get("type") == "shelter_squads":
                rest = [x for x in _l(p.action.get("squads")) if x not in shooting]
                if not rest:
                    continue
                if rest != _l(p.action.get("squads")):
                    p.action = dict(p.action, squads=rest)
            out.append(p)
        kept = out
    proposals[:] = kept
    # the note: why
    if not about and not dropped:
        return
    for t in (about or [fb[i] for p in dropped for i in _l(p.action.get("kill")) if i in fb][:1])[:3]:
        i = t.get("id")
        if policy == "never":
            ranged = "no squad goes out (Rules tab: never)"
        elif i in off:
            ranged = "the fight with it was called off"
        elif why_not[i]:
            ranged = f"no crossbow squad shoots at it either: {why_not[i]}"
        elif sent is not None and i in shoot:
            ranged = f"{sent.get('name') or 'a crossbow squad'} shoots at it from inside the shut gates"
        elif i in on:
            ranged = "a crossbow squad shoots at it from inside the shut gates"
        else:
            ranged = "no crossbow squad free to shoot at it from inside"
        notes.append(f"{_who(t)}: no melee squad is sent at it (fire takes soldiers in their armour before they "
                     f"land a blow); {ranged}. The gates stay shut and the civilians in the shelter while it is "
                     "about, and the fire guard keeps the dwarves off any fire it starts")
