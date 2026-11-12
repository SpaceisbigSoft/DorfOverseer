"""(item5) Siege works and the field guard: ballistae at the gates, archers
behind fortifications, a squad out to a caravan under attack, dangerous
wild animals near the dwarves outside hunted.

The bridge's `siege` section (lua/ai-siege.lua report, daily, cached a day)
lists each gated surface entrance with its fortifications, the floor behind
them (`posts`), the natural walls beside it that could take more (`carve`:
smooth and thin, `smooth`: thin and rough, `dig`: 2-thick, its inner tile
dug first), the siege engines near it and a spot for a ballista
(`engine_spot`); the siege engines (`ai`: the AI's, by name or its record),
`built`/`planned` of the AI's, the parts and arrows (`ammo`), the dwarves
with the siege operating and siege engineering labours. Its `field_watch`
section (each pulse) lists the hostiles near a caravan's merchants
(`caravan`: dangers and hostile wild animals, distance to the nearest
merchant) and the hostile wild animals out under the sky near the dwarves
(`wild`: distance to the nearest dwarf outside and to any dwarf, `reach`:
DF's walk groups), each with fire_breather, great, flier, size.

The rules (_siege_rules), each behind its Rules switch:
  * siege_engines (Fortification or Engineering at `siege_slider` or more,
    `siege_min_citizens` citizens, no enemy in reach): a siege workshop
    (placed 5x5 near the gate: ai-layouts' workshop rooms are 3x3 shops'),
    then a ballista at each gated surface entrance
    with a spot (`siege_engines_max` at most, one more at Extreme), its
    parts ordered while one waits for them, ballista arrows (and their
    arrowheads, in a metal there are bars of) to `siege_ammo_per_engine` a
    built engine, and the siege operating labour to a dwarf an engine;
  * fortifications carved beside the gated surface entrances (smoothed
    first) when nothing is in reach, for the archers (archer_posts: a fort
    with a crossbow squad or Fortification at `archer_post_slider`) or for
    the ballistae to shoot through (siege_engines, engines wanted);
  * archer_posts: in a siege (invaders on
    the map, none in reach of the dwarves yet) the free crossbow squads are
    posted behind them (the gate guard takes the rest). Never while the AI
    hides (a great danger it doesn't fight: planner_army hiding), with a
    fire breather among the besiegers (fire passes fortifications), or at
    the Rules tab's "never";
  * caravan_guard: a hostile within `caravan_guard_tiles` of a merchant: a
    free squad with enough armed goes at it (one only, a squad already on
    it is enough); never a fire breather, never a great danger (unless the
    Rules tab says attack everything), never while evil weather is about
    (planner_weather: the squads would walk out into it), never at "never";
  * wildlife_hunts: a hostile wild animal (a large predator, or one DF
    agitated) within `wild_near_tiles` of a dwarf outside, or one that can
    walk to the dwarves within `wild_reach_tiles`: a free squad goes at it,
    under the same rules as the caravan guard; a big one
    (`wild_big_size`) only for a squad of power `wild_big_power`;
  * the squads sent are not called back by "no more threats" while what
    they were sent at is still listed (the animals are no threat to the
    game, so _military_rules would call them back every cycle).
Without a `siege` / `field_watch` section (an older bridge) nothing here
proposes or notes anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, RECIPE_SHOPS, TICKS_PER_DAY, Proposal, _best_metal, _has_shop, _traits,
                          can_fight, is_ranged, player_rules, queued, reachable_threats)

__all__ = ["siege_of", "field_of", "_siege_rules", "siege_lean", "engines_wanted", "SIEGE_CONFIG"]

SIEGE_CONFIG = {
    "siege_slider": 50,                 # Fortification or Engineering at least this for siege engines
    "siege_min_citizens": 30,           # ...and a fort this big
    "siege_engines_max": 2,             # ballistae at most (one more at Extreme, slider 150+)
    "siege_ammo_per_engine": 10,        # ballista arrows kept for each built engine
    "siege_ammo_order_max": 10,         # ballista arrows in one order at most
    "siege_operators_per_engine": 1,    # dwarves with the siege operating labour per built engine
    "siege_operators_max": 3,
    "archer_post_slider": 50,           # Fortification for the posts without a crossbow squad
    "archer_fortify_tiles": 4,          # tiles smoothed or carved in one go
    "archer_post_fortifications": 3,    # fortifications wanted at an entrance
    "caravan_guard_tiles": 12,          # a hostile this near a merchant: the caravan is under attack
    "wild_near_tiles": 15,              # a hostile wild animal this near a dwarf outside is hunted
    "wild_reach_tiles": 25,             # ...or this near any dwarf it can walk to
    "wild_big_size": 2000000,           # a body this big (a dwarf is ~60,000) is hunted only by...
    "wild_big_power": 12,               # ...a squad of this power (lua/ai-military squad_power)
    # cooldowns (select(): <rule>_cooldown_ticks)
    "siege_shop_cooldown_ticks": 7 * TICKS_PER_DAY,
    "siege_engine_cooldown_ticks": 7 * TICKS_PER_DAY,
    "siege_parts_cooldown_ticks": 7 * TICKS_PER_DAY,
    "siege_ammo_cooldown_ticks": 7 * TICKS_PER_DAY,
    "siege_operator_cooldown_ticks": 14 * TICKS_PER_DAY,
    "fortify_post_cooldown_ticks": 3 * TICKS_PER_DAY,
    "archer_post_cooldown_ticks": 300,
    "caravan_guard_cooldown_ticks": 100,
    "wild_hunt_cooldown_ticks": 300,
}
for _k, _v in SIEGE_CONFIG.items():
    PLANNER_CONFIG.setdefault(_k, _v)
for _r, _shop in (("ballista_parts", "Siege"), ("catapult_parts", "Siege"), ("ballista_arrows", "Siege"),
                  ("ballista_arrowheads", "MetalsmithsForge")):
    RECIPE_SHOPS.setdefault(_r, _shop)


def _c(cfg: dict, k: str):
    return cfg.get(k, SIEGE_CONFIG[k])


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _on(s: dict, k: str) -> bool:
    return _d(s.get("settings")).get(k) is not False


def siege_of(s: dict) -> dict:
    """The bridge's siege section; {} when absent or failed."""
    sg = _d(s.get("siege"))
    return {} if sg.get("error") or "siege" in _d(s.get("_errors")) else sg


def field_of(s: dict) -> dict:
    """The bridge's field_watch section; {} when absent or failed."""
    f = _d(s.get("field_watch"))
    return {} if f.get("error") or "field_watch" in _d(s.get("_errors")) else f


def siege_lean(s: dict) -> int:
    """The higher of Fortification and Engineering (effective, -200..200)."""
    t = _traits(s)
    return max(int(t.get("fortification", 0) or 0), int(t.get("engineering", 0) or 0))


def engines_wanted(lean: int, cfg: dict) -> int:
    if lean < _c(cfg, "siege_slider"):
        return 0
    return _c(cfg, "siege_engines_max") + (1 if lean >= 150 else 0)


def _entrances(sg: dict) -> list:
    return [e for e in _l(sg.get("entrances")) if isinstance(e, dict) and isinstance(e.get("id"), int)
            and not e.get("error") and e.get("sealed") and e.get("kind") != "cavern"]


def _squads(s: dict) -> list:
    return [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]


def _weather(s: dict, cfg: dict) -> str:
    try:
        from planner_weather import weather_danger
        return weather_danger(s, cfg)
    except Exception:  # noqa: BLE001  (no weather word: nothing held)
        return ""


# --- siege engines --------------------------------------------------------------------------

def _engine_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if not _on(s, "siege_engines"):
        return
    sg = siege_of(s)
    if not sg:
        return
    lean = siege_lean(s)
    want = engines_wanted(lean, cfg)
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    if want <= 0 or citizens < _c(cfg, "siege_min_citizens"):
        return
    if reachable_threats(s, _traits(s), cfg):
        return                          # building waits for quiet; the squads have the fight
    b = _d(s.get("buildings"))
    has_shop = _has_shop(b, "Siege") or int(sg.get("shops") or 0) > 0
    ents = _entrances(sg)
    if not has_shop and ents:
        proposals.append(Proposal("siege_shop", {"type": "place_siege_shop", "entrance_id": ents[0]["id"]},
                                  f"Fortification or Engineering at {lean}: a siege workshop near the gate at "
                                  f"x{ents[0].get('x')} y{ents[0].get('y')} for ballista parts and arrows", 6))
    ai = int(sg.get("ai_engines") or 0)
    if ai < want:
        spot = next((e for e in ents if not int(e.get("engines_near") or 0) and isinstance(e.get("engine_spot"), dict)),
                    None)
        if spot is not None:
            sp = spot["engine_spot"]
            proposals.append(Proposal("siege_engine", {"type": "place_siege_engine", "entrance_id": spot["id"],
                                                       "kind": "ballista"},
                                      f"Fortification or Engineering at {lean}: a ballista behind the entrance at "
                                      f"x{spot.get('x')} y{spot.get('y')} (at x{sp.get('x')} y{sp.get('y')}, facing "
                                      f"{str(sp.get('facing') or 'out').lower()}), {ai + 1} of {want}", 6))
        elif ents and not any(int(e.get("engines_near") or 0) for e in ents) and ai == 0:
            notes.append("siege engines wanted, but no gated entrance has fortifications with free roofed floor "
                         "behind them for a ballista yet (they are carved first)")
    ammo = _d(sg.get("ammo"))
    planned, built = int(sg.get("planned") or 0), int(sg.get("built") or 0)
    # parts for the engines placed and waiting (buildingplan holds them for parts)
    if planned and has_shop:
        have = int(ammo.get("ballista_parts") or 0) + queued(s, {"ballista_parts"})
        if have < planned:
            proposals.append(Proposal("siege_parts", {"type": "work_order", "recipe": "ballista_parts",
                                                      "amount": planned - have},
                                      f"{planned} ballista(e) placed wait for parts: make {planned - have} at the "
                                      "siege workshop", 5, True))
    if built and has_shop:
        target = built * _c(cfg, "siege_ammo_per_engine")
        arrows = int(ammo.get("siege_ammo") or 0) + queued(s, {"ballista_arrows"})
        if arrows < target:
            n = min(target - arrows, _c(cfg, "siege_ammo_order_max"))
            heads = int(ammo.get("arrowheads") or 0) + queued(s, {"ballista_arrowheads"})
            if heads < n:
                metal = _best_metal(s, n - heads)
                if metal and _has_shop(b, "MetalsmithsForge"):
                    proposals.append(Proposal("siege_ammo", {"type": "work_order", "recipe": "ballista_arrowheads",
                                                             "amount": n - heads, "material": metal},
                                              f"{built} ballista(e) and {arrows} arrows: {n - heads} arrowheads "
                                              f"of {metal.split(':')[-1].lower()} at the forge", 5, True))
                elif heads == 0:
                    notes.append(f"{built} ballista(e) with {arrows} arrows: arrowheads need metal bars and a forge "
                                 "(none to spare yet)")
            if heads > 0:
                proposals.append(Proposal("siege_ammo", {"type": "work_order", "recipe": "ballista_arrows",
                                                         "amount": min(n, heads)},
                                          f"{built} ballista(e) and {arrows} arrows (wanted {target}): "
                                          f"{min(n, heads)} arrows at the siege workshop", 5, True))
    if built:
        ops = sg.get("operators")
        want_ops = min(built * _c(cfg, "siege_operators_per_engine"), _c(cfg, "siege_operators_max"))
        if isinstance(ops, int) and ops < want_ops:
            proposals.append(Proposal("siege_operator", {"type": "assign_labor", "job": "SIEGEOPERATE",
                                                         "count": want_ops - ops},
                                      f"{built} ballista(e) built and {ops} siege operator(s): the labour given to "
                                      f"{want_ops - ops} more", 5))


# --- fortifications and the archer posts ----------------------------------------------------

def _fortify_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Fortifications beside the gated surface entrances, in quiet times: for
    the archers (Rules: archer_posts; a crossbow squad, or Fortification at
    archer_post_slider) or for the ballistae to shoot through (Rules:
    siege_engines, and engines wanted). One entrance a cycle."""
    ents = _entrances(siege_of(s))
    if not ents:
        return
    fort = int(_traits(s).get("fortification", 0) or 0)
    ranged = [q for q in _squads(s) if is_ranged(q)]
    for_posts = _on(s, "archer_posts") and (bool(ranged) or fort >= _c(cfg, "archer_post_slider"))
    for_engines = (_on(s, "siege_engines") and engines_wanted(siege_lean(s), cfg) > 0
                   and int(_d(s.get("dwarves")).get("total") or 0) >= _c(cfg, "siege_min_citizens"))
    if not (for_posts or for_engines) or reachable_threats(s, _traits(s), cfg):
        return
    need = _c(cfg, "archer_post_fortifications")
    for e in ents:
        have = int(e.get("fortifications") or 0)
        if have >= need:
            continue
        step = ("carve" if int(e.get("carve") or 0) else "smooth" if int(e.get("smooth") or 0)
                else "dig" if int(e.get("dig") or 0) and not have else None)
        if step is None:
            continue
        words = {"carve": "fortifications carved into the smoothed wall",
                 "smooth": "the thin wall smoothed (fortifications are carved into smooth rock)",
                 "dig": "the inner half of a 2-thick wall dug out from inside (the outer half takes the "
                        "fortifications)"}[step]
        who = "archers" if for_posts else "the ballistae"
        proposals.append(Proposal("fortify_post", {"type": "fortify_post", "entrance_id": e["id"],
                                                   "max": _c(cfg, "archer_fortify_tiles")},
                                  f"the entrance at x{e.get('x')} y{e.get('y')} has {have} fortification(s) for "
                                  f"{who} to shoot through: {words}", 6))
        return


def _post_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if not _on(s, "archer_posts"):
        return
    ents = _entrances(siege_of(s))
    if not ents:
        return
    ranged = [q for q in _squads(s) if is_ranged(q)]
    # posting the crossbows in a siege
    from planner_gates import gate_invaders
    inv = gate_invaders(s)
    if not inv or not ranged:
        return
    policy = player_rules(s)["attack_policy"]
    if policy == "never":
        return
    from planner_army import hiding
    if hiding(s, memory, cfg)[0]:
        notes.append("besiegers outside, but the AI hides from a danger it doesn't fight: the crossbows wait in "
                     "the shelter, not at the posts")
        return
    if policy != "all" and any(t.get("fire_breather") is True for t in inv):
        notes.append("a fire breather is among the besiegers: no archers at the fortifications (fire passes "
                     "through them)")
        return
    post = [e for e in ents if int(e.get("posts") or 0) > 0]
    if not post:
        return
    from planner_gates import main_gate
    mg = main_gate(s, memory)
    e = min(post, key=lambda x: (0 if mg and x.get("id") == mg.get("id") else 1, x["id"]))
    free = [q for q in ranged if can_fight(q, cfg) and not q.get("ai_orders") and not (q.get("orders") or 0)]
    if not free:
        return
    ids = [q["id"] for q in free][:6]
    proposals.append(Proposal("archer_post", {"type": "archer_post", "entrance_id": e["id"], "squads": ids},
                              f"{len(inv)} besieger(s) outside, none in reach yet: {len(ids)} crossbow squad(s) "
                              f"behind the fortifications at x{e.get('x')} y{e.get('y')}", 0))
    # the gate guard holds the gate with the others
    for p in list(proposals):
        if p.action.get("type") == "guard_gate":
            rest = [x for x in _l(p.action.get("squads")) if x not in ids]
            if not rest:
                proposals.remove(p)
            elif rest != _l(p.action.get("squads")):
                p.action = dict(p.action, squads=rest)


# --- squads sent out: the caravan and the wildlife ------------------------------------------

def _targeted(s: dict, proposals: list) -> set:
    out = set()
    for q in _squads(s):
        if q.get("ai_orders"):
            out |= {x for x in _l(q.get("kill_ids")) if isinstance(x, int)}
    for p in proposals:
        if p.action.get("type") == "squad_orders":
            out |= {x for x in _l(p.action.get("kill")) if isinstance(x, int)}
    return out


def _free_squad(s: dict, cfg: dict, proposals: list, big: bool = False):
    ordered = {p.action.get("squad_id") for p in proposals if p.action.get("type") in ("squad_orders", "archer_post",
                                                                                      "guard_gate")}
    for p in proposals:
        if p.action.get("type") in ("archer_post", "guard_gate", "shelter_squads"):
            ordered |= set(_l(p.action.get("squads")))
    free = [q for q in _squads(s) if can_fight(q, cfg) and not q.get("ai_orders") and not (q.get("orders") or 0)
            and q["id"] not in ordered and not is_ranged(q)]
    free += [q for q in _squads(s) if can_fight(q, cfg) and not q.get("ai_orders") and not (q.get("orders") or 0)
             and q["id"] not in ordered and is_ranged(q)]       # crossbows after the melee squads
    if big:
        free = [q for q in free if _num(_d(q.get("power")).get("power"))
                and _d(q.get("power"))["power"] >= _c(cfg, "wild_big_power")]
    return free[0] if free else None


def _held(s: dict, cfg: dict, what: str, notes: list) -> bool:
    """Why no squad goes out now (noted): the Rules tab's never, the alarm up
    for something else, evil weather about."""
    if player_rules(s)["attack_policy"] == "never":
        return True
    w = _weather(s, cfg)
    if w:
        notes.append(f"{what}, but {w[:80]}: no squad walks out into it")
        return True
    return False


def _caravan_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    if not _on(s, "caravan_guard"):
        return []
    f = field_of(s)
    if not f or not int(f.get("merchants") or 0):
        return []
    lim = _c(cfg, "caravan_guard_tiles")
    rows = [r for r in _l(f.get("caravan")) if isinstance(r, dict) and isinstance(r.get("id"), int)
            and _num(r.get("distance")) and r["distance"] <= lim]
    if not rows:
        return []
    policy = player_rules(s)["attack_policy"]
    from planner_military import called_off_ids
    off = called_off_ids(s, memory)
    ok = [r for r in rows if r["id"] not in off and (policy == "all" or (not r.get("fire_breather") and not r.get("great")))]
    names = ", ".join(str(r.get("name") or "?") for r in rows[:3])
    if not ok:
        notes.append(f"{names} by the caravan: too dangerous to send a squad at (fire, or a great danger)")
        return []
    if _held(s, cfg, f"{names} by the caravan", notes):
        return []
    done = _targeted(s, proposals)
    new = [r["id"] for r in ok if r["id"] not in done]
    if not new:
        return [r["id"] for r in ok]
    q = _free_squad(s, cfg, proposals)
    if q is None:
        notes.append(f"{names} by the caravan and no squad with {cfg.get('min_squad_to_fight', 3)}+ armed free "
                     "to send")
        return [r["id"] for r in ok]
    proposals.append(Proposal("caravan_guard", {"type": "squad_orders", "squad_id": q["id"], "kill": new[:10]},
                              f"{names} within {lim} tiles of the caravan's merchants: send "
                              f"{q.get('name') or 'the squad'} to guard it", 1, guard=True))
    return [r["id"] for r in ok]


def _wild_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    if not _on(s, "wildlife_hunts"):
        return []
    f = field_of(s)
    near, reach_lim = _c(cfg, "wild_near_tiles"), _c(cfg, "wild_reach_tiles")
    rows = [r for r in _l(f.get("wild")) if isinstance(r, dict) and isinstance(r.get("id"), int)
            and ((_num(r.get("distance_outside")) and r["distance_outside"] <= near)
                 or (r.get("reach") is True and _num(r.get("distance")) and r["distance"] <= reach_lim))]
    if not rows:
        return []
    policy = player_rules(s)["attack_policy"]
    ok = [r for r in rows if policy == "all" or not r.get("fire_breather")]
    names = ", ".join(str(r.get("name") or "?") for r in rows[:3])
    if not ok:
        notes.append(f"{names} near the dwarves outside: it breathes fire, no squad goes at it")
        return []
    if s.get("civ_alert"):
        return []                       # the alarm is up for something else: the squads have that
    if _held(s, cfg, f"{names} near the dwarves outside", notes):
        return []
    done = _targeted(s, proposals)
    new = [r for r in ok if r["id"] not in done]
    if not new:
        return [r["id"] for r in ok]
    big = any(_num(r.get("size")) and r["size"] >= _c(cfg, "wild_big_size") for r in new)
    q = _free_squad(s, cfg, proposals, big=big)
    if q is None:
        notes.append(f"{names} near the dwarves outside and no squad free to hunt "
                     + ("so big a beast" if big else "it"))
        return [r["id"] for r in ok]
    proposals.append(Proposal("wild_hunt", {"type": "squad_orders", "squad_id": q["id"],
                                            "kill": [r["id"] for r in new][:10]},
                              f"{names} (a dangerous wild animal) near the dwarves at work outside: send "
                              f"{q.get('name') or 'the squad'} to kill it", 2))
    return [r["id"] for r in ok]


def _keep_on(s: dict, guarded: set, proposals: list, notes: list) -> None:
    """A squad on a caravan's attacker or a wild animal still listed is not
    called back for "no more threats" (the game doesn't count an animal as a
    threat, so _military_rules would recall it every cycle)."""
    if not guarded:
        return
    squads = {q["id"]: q for q in _squads(s)}
    kept = []
    for p in proposals:
        a = p.action
        q = squads.get(a.get("squad_id"))
        if (p.rule == "squad_recall" and a.get("clear") and q is not None and "no more threats" in p.reason
                and {x for x in _l(q.get("kill_ids")) if isinstance(x, int)} & guarded):
            kept.append(p)
    for p in kept:
        proposals.remove(p)
    if kept:
        notes.append(f"{len(kept)} squad(s) stay on the caravan's attackers or the wild animals they were sent at")


def _siege_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if not isinstance(s.get("settings"), dict):
        return
    _engine_rule(s, memory, cfg, proposals, notes)
    _fortify_rule(s, memory, cfg, proposals, notes)
    _post_rule(s, memory, cfg, proposals, notes)
    guarded = set(_caravan_rule(s, memory, cfg, proposals, notes))
    guarded |= set(_wild_rule(s, memory, cfg, proposals, notes))
    _keep_on(s, guarded, proposals, notes)
