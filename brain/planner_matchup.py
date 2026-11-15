"""planner_matchup: a threat judged against the fort's squads (0.105.45, Phase 11 (a)).

The bridge (lua/ai-threat-facts.lua) puts on each `others_on_map.threats` row
what the threat brings to a fight: its attacks (and venom), breath kinds
(fire, dragonfire, web, poison gas, dust, "deadly"), webs, no pain / no
exertion / no stun, regeneration, a natural-armour hint, raising the dead,
its speed and its wounds, with `facts = 1`. The squads' `power` (lua/ai-
military.lua squad_power) is split into `melee_power` and `ranged_power`.

- `facts_mult(t)`: what the facts add to a threat's strength (with reasons),
  used by planner_military.threat_power when the row has `facts`.
- `squad_weights(t)`: how much melee and ranged power count against it (a
  fire breather: only ranged; a flier: ranged more, melee less).
- `judge(threats, squads, factor)` and `matchup(t, squads)`: the squads'
  effective strength against the threats' need, the ratio and the reasons in
  words. With rows that have no `facts` (an older bridge) the ratio is the
  old one exactly: total power against threat_power.

Why (A, 4-5 Nov): a breathing titan scored 39 against squads of 488 and 25
soldiers died in six minutes; F's hill titan killed 42 in the shelter.
"""

from __future__ import annotations

from digest import _d, _l

__all__ = ["BREATH_WEIGHT", "facts_mult", "squad_weights", "squad_split", "judge", "matchup", "fight_bar", "strike_bar", "weakened", "clusters", "groups_apart", "all_out", "siege_days", "losses_turned", "fire_breather", "melee_bar", "shoots", "ranged_only", "fight_bar_of", "beast_plan", "TACTICS"]

# (0.105.45) a breath's weight against squads that close in (the highest of
# its kinds counts): fire and dragonfire burn a squad in its armour, deadly
# dust or poison gas lays out everyone in the cloud, webs hold soldiers
# while it strikes
BREATH_WEIGHT = {"dragonfire": 6.0, "fire": 4.0, "poison_gas": 5.0, "dust": 2.5, "web": 2.0,
                 "spit": 1.5, "rock": 1.5, "other": 1.5, "deadly": 6.0}
SYNDROME_ATTACK = 2.0       # venom in a bite or sting
DEADLY_ATTACK = 2.5         # ...whose syndrome kills or cripples
NO_PAIN = 1.3
NO_EXERT = 1.15
NO_STUN = 1.15
REGENERATES = 1.5
ARMOR_STEP = 0.25           # per level of natural armour (0-3)
WEBS = 1.3                  # spins webs (no web spray)
UNDEAD_RAISER = 1.5
OTHER_ABILITY = 1.5         # an ability the bridge couldn't name (was x3 for any, GREAT_ABILITY)
FLIER = 1.5                 # as GREAT_FLIER
SPEED_LO, SPEED_HI = 0.8, 1.3

# how much melee (wm) and ranged (wr) power count against a threat that...
WEIGHT_FIRE = (0.0, 1.0)            # breathes fire or dragonfire: only ranged
WEIGHT_CLOUD = (0.35, 1.0)          # breathes poison gas or deadly dust
WEIGHT_DUST = (0.6, 1.0)            # breathes dust (no deadly syndrome known)
WEIGHT_WEB = (0.6, 1.0)             # sprays or spins webs
WEIGHT_FLIER = (0.6, 1.25)          # flies: it picks its fights, crossbows reach it
WEIGHT_VENOM = (0.8, 1.1)           # venom in its attacks: every blow taken counts

BREATH_WORDS = {"dragonfire": "dragonfire", "fire": "fire", "poison_gas": "poison gas", "dust": "dust",
                "web": "webs", "spit": "spit", "rock": "rocks", "other": "something"}


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _breath(t: dict) -> list:
    return [str(b) for b in _l(t.get("breath"))]


def facts_mult(t: dict) -> tuple[float, list]:
    """What the bridge's facts add to a threat's strength: (multiplier,
    reasons). Flight counts here too (as GREAT_FLIER did)."""
    mult, why = 1.0, []
    br = _breath(t)
    if br:
        w = max(BREATH_WEIGHT.get(b, 1.5) for b in br)
        mult *= w
        kinds = [BREATH_WORDS.get(b, b) for b in br if b != "deadly"]
        why.append(f"it breathes {' and '.join(kinds) or 'a cloud'}"
                   + (" that kills" if "deadly" in br else "") + f" (x{w:g})")
    elif t.get("abilities") and not t.get("undead_raiser"):
        mult *= OTHER_ABILITY
        why.append(f"it has abilities the AI can't name (x{OTHER_ABILITY:g})")
    att = _d(t.get("attacks"))
    if att.get("deadly"):
        mult *= DEADLY_ATTACK
        why.append(f"its attacks carry a deadly venom (x{DEADLY_ATTACK:g})")
    elif t.get("syndrome_attack") or att.get("syndrome"):
        mult *= SYNDROME_ATTACK
        why.append(f"its attacks carry a venom (x{SYNDROME_ATTACK:g})")
    if t.get("webs") and "web" not in br:
        mult *= WEBS
        why.append("it spins webs")
    tough = [w for k, w in (("no_pain", "feels no pain"), ("no_exert", "never tires"), ("no_stun", "can't be stunned"))
             if t.get(k)]
    for k, f in (("no_pain", NO_PAIN), ("no_exert", NO_EXERT), ("no_stun", NO_STUN)):
        if t.get(k):
            mult *= f
    if tough:
        why.append("it " + ", ".join(tough))
    if t.get("regenerates"):
        mult *= REGENERATES
        why.append(f"it heals its wounds (x{REGENERATES:g})")
    lvl = _num(t.get("armor"))
    if lvl and lvl > 0:
        lvl = min(3, lvl)
        mult *= 1 + ARMOR_STEP * lvl
        why.append(f"it is armoured ({t.get('armor_kind') or 'tough hide'})")
    if t.get("undead_raiser"):
        mult *= UNDEAD_RAISER
        why.append("it raises the dead")
    sp = _num(t.get("speed"))
    if sp and sp > 0:
        f = max(SPEED_LO, min(SPEED_HI, 0.85 + 0.15 * sp))
        mult *= f
        if sp >= 1.5:
            why.append(f"it is fast ({sp:.1f}x a dwarf)")
        elif sp <= 0.6:
            why.append("it is slow")
    if t.get("flier"):
        mult *= FLIER
        why.append("it flies")
    lost = _num(t.get("blood_lost"))
    if lost and lost > 0:
        mult *= 1 - 0.6 * min(lost, 0.8)
        why.append(f"it has lost {round(lost * 100)}% of its blood")
    wounds = _num(t.get("wounds"))
    if wounds and wounds >= 10:
        mult *= 0.85
        why.append(f"it carries {int(wounds)} wounds")
    return mult, why


def squad_weights(t: dict) -> tuple[float, float, list]:
    """(melee weight, ranged weight, reasons) against one threat. A row with
    no facts: (1, 1, []), the old judgement."""
    if not t.get("facts"):
        return 1.0, 1.0, []
    br = set(_breath(t))
    wm, wr, why = 1.0, 1.0, []

    def take(w, words):
        nonlocal wm, wr
        wm, wr = wm * w[0], max(wr, w[1])
        why.append(words)
    if br & {"fire", "dragonfire"} or t.get("fire_breather") is True:
        take(WEIGHT_FIRE, "against its fire only ranged squads count")
    elif "poison_gas" in br or ("dust" in br and "deadly" in br) or "deadly" in br:
        take(WEIGHT_CLOUD, "its cloud lays out soldiers who close in: ranged squads count more")
    elif "dust" in br:
        take(WEIGHT_DUST, "its dust falls on soldiers who close in")
    if "web" in br or t.get("webs"):
        take(WEIGHT_WEB, "its webs hold the soldiers who close in")
    if t.get("flier"):
        take(WEIGHT_FLIER, "it flies: crossbows count more, melee less")
    if t.get("syndrome_attack") or _d(t.get("attacks")).get("syndrome"):
        take(WEIGHT_VENOM, "every blow it lands poisons")
    return wm, wr, why


def squad_split(q: dict) -> tuple[float, float]:
    """A squad's (melee, ranged) power; an older bridge's squad (no split):
    all of its power as melee."""
    p = _d(q.get("power"))
    total = float(_num(p.get("power")) or 0)
    m, r = _num(p.get("melee_power")), _num(p.get("ranged_power"))
    if m is None or r is None:
        return total, 0.0
    return float(m), float(r)


def judge(threats, squads: list, factor=None) -> dict:
    """The squads against the threats: {army (effective), total (the raw
    power sum), need, ratio, reasons}. `factor(t)`: what the fort learned
    of that kind (memory.fight_factor), 1 by default."""
    from planner_military import threat_power
    ts = [t for t in (threats if isinstance(threats, list) else [threats]) if isinstance(t, dict)]
    melee = ranged = total = 0.0
    for q in squads or []:
        if isinstance(q, dict):
            m, r = squad_split(q)
            melee, ranged = melee + m, ranged + r
            total += float(_num(_d(q.get("power")).get("power")) or 0)
    need, wm_sum, wr_sum, reasons = 0.0, 0.0, 0.0, []
    for t in ts:
        f = float(factor(t)) if callable(factor) else 1.0
        n = threat_power(t) * f
        wm, wr, why = squad_weights(t)
        need += n
        wm_sum, wr_sum = wm_sum + wm * n, wr_sum + wr * n
        if t.get("facts"):
            for w in facts_mult(t)[1] + why:
                if w not in reasons:
                    reasons.append(w)
    if need > 0 and any(t.get("facts") for t in ts):
        army = melee * wm_sum / need + ranged * wr_sum / need
    else:
        army = total
    if army < total * 0.5 and ranged < melee and any(t.get("facts") for t in ts):
        reasons.append(f"the squads are mostly melee ({melee:.0f} melee, {ranged:.0f} ranged)")
    return {"army": army, "total": total, "need": need, "ratio": army / max(1.0, need), "reasons": reasons}


def matchup(t, squads: list, factor=None) -> tuple[float, list]:
    """(ratio, reasons): the squads' strength against the threat (a row or a
    list of rows), weighing melee and ranged power by what it brings. The
    squads go at fight_bar's bar (about even odds since 0.105.54) or better."""
    j = judge(t, squads, factor)
    return j["ratio"], j["reasons"]


# --- (0.105.54) when to fight -------------------------------------------------------------
# The player (15 Nov): "fight back": the squads went out only on a clear win
# (fight_ratio 2x), else everyone hid. Now the sortie bar is about even odds
# (`fight_even_ratio`); a clear win only where the audit's reasons hold (a
# fire breather: crossbows only; a great danger whose abilities the AI can't
# read). An enemy all wounded or falling back lowers the bar; a group apart
# from the main body (stragglers, a rearguard, one wandering invader) is a
# strike of its own; a siege that lasts (`siege_wait_max_days`), a shelter
# short of drink or food, thirst deaths or the unhappy share rising end the
# wait (an all-out attack); the losses guard (a third lost, half wounded)
# still calls the squads back. Every decision says why.

def _rows(threat) -> list:
    return [t for t in (threat if isinstance(threat, list) else [threat]) if isinstance(t, dict)]


def fire_breather(t: dict) -> bool:
    return t.get("fire_breather") is True or bool(set(_breath(t)) & {"fire", "dragonfire"})


def unknown_powers(t: dict) -> bool:
    """A great danger with abilities the AI can't read: none read at all (an
    older bridge), or ones the bridge couldn't name."""
    if not (t.get("great_danger") and t.get("abilities")):
        return False
    br = _breath(t)
    return not t.get("facts") or "other" in br or (not br and not t.get("undead_raiser"))


def fight_bar(threat, cfg: dict) -> dict:
    """The bar the squads' matchup ratio must reach to go at these threats
    (a row or a list): {bar, why, ranged_only}. About even odds
    (`fight_even_ratio`) for invaders and beasts; a clear win (`fight_ratio`)
    against a fire breather (and crossbows only) or a great danger whose
    abilities aren't known; a flier: crossbows only. For the other builders'
    rules to call too."""
    rows = _rows(threat)
    even = float(cfg.get("fight_even_ratio", 1.0))
    clear = float(cfg.get("fight_ratio", 2.0))
    if any(fire_breather(t) for t in rows):
        return {"bar": clear, "ranged_only": True,
                "why": f"it breathes fire: never melee, crossbows only and at a clear win ({clear:g}x)"}
    if any(unknown_powers(t) for t in rows):
        return {"bar": clear, "ranged_only": False,
                "why": f"its abilities can't be read: a clear win ({clear:g}x) wanted"}
    if any(t.get("flier") for t in rows) and all(t.get("flier") for t in rows):
        # (0.105.54 merge) a flier inside the fort is in reach of melee: fought
        # however the fort is armed (a fort with no crossbow squad left it free)
        if any(t.get("inside") is True for t in rows):
            return {"bar": even, "ranged_only": False, "why": f"about even odds ({even:g}x); it flies but is inside"}
        return {"bar": even, "ranged_only": True, "why": f"about even odds ({even:g}x); it flies: crossbows"}
    return {"bar": even, "ranged_only": False, "why": f"about even odds ({even:g}x)"}


def weakened(t: dict, cfg: dict, retreating=()) -> str:
    """Why this threat is weakened ("" if it isn't): wounded (blood lost,
    many wounds: the bridge's threat facts) or falling back (farther from the
    dwarves than last cycle: planner_holdfast's distance record)."""
    lost = _num(t.get("blood_lost"))
    if lost is not None and lost >= float(cfg.get("fight_wounded_blood", 0.25)):
        return f"wounded ({round(lost * 100)}% of its blood lost)"
    w = _num(t.get("wounds"))
    if w is not None and w >= int(cfg.get("fight_wounded_wounds", 6)):
        return f"wounded ({int(w)} wounds)"
    if t.get("id") in set(retreating or ()):
        return "falling back"
    return ""


def strike_bar(threat, cfg: dict, retreating=()) -> tuple[float, str]:
    """fight_bar, lowered by `fight_weak_factor` when every one of them is
    wounded or falling back (never for a fire breather): (bar, why)."""
    rows = _rows(threat)
    fb = fight_bar(rows, cfg)
    bar, why = fb["bar"], fb["why"]
    weak = [weakened(t, cfg, retreating) for t in rows]
    if rows and all(weak) and not any(fire_breather(t) for t in rows):
        f = float(cfg.get("fight_weak_factor", 0.8))
        bar *= f
        why = f"{why}; {'they are' if len(rows) > 1 else 'it is'} {weak[0]}: the bar x{f:g}"
    return bar, why


def _pos(t: dict):
    p = _d(t.get("pos"))
    if all(isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) for k in ("x", "y", "z")):
        return p
    return None


def _gap(a: dict, b: dict) -> float:
    return max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"])) + 3 * abs(a["z"] - b["z"])


def clusters(rows: list, link: float) -> list:
    """The threats grouped by distance (single link: one within `link` tiles
    of another is in its group), largest first. Rows without a position
    join the largest group (where they are is unknown)."""
    rows = _rows(rows)
    placed = [t for t in rows if _pos(t)]
    groups: list = []
    for t in placed:
        p = _pos(t)
        near = [g for g in groups if any(_gap(p, _pos(o)) <= link for o in g)]
        merged = [t]
        for g in near:
            merged.extend(g)
            groups.remove(g)
        groups.append(merged)
    groups.sort(key=lambda g: (-len(g), min(str(x.get("id")) for x in g)))
    rest = [t for t in rows if not _pos(t)]
    if rest:
        if groups:
            groups[0].extend(rest)
        else:
            groups.append(rest)
    return groups


def groups_apart(rows: list, cfg: dict) -> list:
    """The groups apart from the main body (the largest group): stragglers,
    a rearguard, one wandering invader. [] when they are all together."""
    gs = clusters(rows, float(cfg.get("fight_split_tiles", 15)))
    return gs[1:] if len(gs) > 1 else []


def _siege(memory) -> dict:
    h = getattr(memory, "holdfast", None) if memory is not None else None
    return _d(_d(h).get("siege"))


def siege_days(s: dict, memory) -> float:
    """How long the siege (invaders or a great danger in reach, without a
    break: planner_holdfast's record) has lasted, in game days; 0 if none."""
    from planner_core import TICKS_PER_DAY, abs_tick
    since = _siege(memory).get("since")
    if not isinstance(since, int):
        return 0.0
    return max(0, abs_tick(s) - since) / TICKS_PER_DAY


def all_out(s: dict, memory, cfg: dict) -> str:
    """Why the wait is over ("" while it isn't): the siege has lasted
    `siege_wait_max_days`; the shelter is short of drink or food (its last
    fill, with the alarm up); citizens died of thirst during it; the unhappy
    share rose `siege_unhappy_rise` since it began, to `siege_unhappy_min` at
    least. Then every able squad goes, militia and crossbows too."""
    rec = _siege(memory)
    since = rec.get("since")
    if not isinstance(since, int):
        return ""
    days = siege_days(s, memory)
    wait = float(cfg.get("siege_wait_max_days", 4))
    if days >= wait:
        return f"the siege has lasted {days:.1f} days ({wait:g} at most before the squads go out)"
    sup = _d(getattr(memory, "shelter_supply", None)) if memory is not None else {}
    if s.get("civ_alert") is True:
        short = [str(sup[k]) for k in ("no_water", "drink_short", "no_food") if sup.get(k)]
        if sup.get("dry") and not short:
            short = ["no drink in the shelter"]
        if short:
            return f"the shelter runs short ({'; '.join(short)[:80]})"
    dead = [d for d in _l(_d(s.get("thirst")).get("deaths"))
            if isinstance(d, dict) and isinstance(d.get("tick"), int) and d["tick"] >= since]
    if dead:
        return f"{len(dead)} citizen(s) died of thirst during the siege"
    try:
        from planner_society import unhappy_share
        now = unhappy_share(s)
    except Exception:  # noqa: BLE001
        return ""
    start = rec.get("unhappy")
    if (isinstance(start, (int, float)) and now >= float(cfg.get("siege_unhappy_min", 0.3))
            and now - start >= float(cfg.get("siege_unhappy_rise", 0.15))):
        return f"the unhappy share rose from {round(start * 100)}% to {round(now * 100)}% during the siege"
    return ""


def losses_turned(squads: list, start: dict, cfg: dict) -> str:
    """A fight turned bad for these squads ("" if not): a third of the
    soldiers they went with lost, or half of those left wounded (the bridge's
    power.wounded). `start`: {squad id (str): members when the order began}."""
    went = now = wounded = 0
    for q in squads:
        if not isinstance(q, dict):
            continue
        n0 = start.get(str(q.get("id")))
        n = int(q.get("members") or 0)
        if isinstance(n0, int) and not isinstance(n0, bool):
            went += max(n0, n)
            now += n
        wounded += int(_num(_d(q.get("power")).get("wounded")) or 0)
    if went and (went - now) >= went * float(cfg.get("fight_lost_share", 0.33)) and went - now > 0:
        return f"{went - now} of the {went} soldiers who went are lost"
    alive = sum(int(q.get("members") or 0) for q in squads if isinstance(q, dict))
    if alive and wounded >= alive * float(cfg.get("fight_wounded_share", 0.5)):
        return f"{wounded} of the {alive} soldiers out are wounded"
    return ""

# (0.105.54, the player: "fight back") A great beast is killed, not only hidden
# from. Its tactic, from what it brings (ai-threat-facts) and the squads:
#   melee   only when nothing it breathes or spins makes closing in suicidal,
#           and the squads are about even with it (fight_bar_of);
#   ranged  marksdwarves from behind fortifications (the crossbows' power
#           alone about even with it);
#   cage    a cage trap line (the lure pocket's cage traps): it doesn't avoid traps;
#   lure    the pocket's drawbridges shut it in (it avoids traps), then the crossbows.
# The fight tactics wait until the squads are ready; meanwhile the beast is
# kept sealed or lured, and what is missing is said.
TACTICS = ("melee", "ranged", "cage", "lure")
TACTIC_WORDS = {"melee": "the squads close in", "ranged": "crossbows from behind fortifications",
                "cage": "a cage trap line (the lure pocket)", "lure": "lured into the pocket and shut in, then shot"}


def melee_bar(t: dict) -> str:
    """Why closing in on this threat is suicidal ("" if it isn't): a breath of
    fire or dragonfire, poison gas, dust (a syndrome) or a deadly cloud, a
    web spray or spun webs. Never melee such a beast (the player)."""
    t = _d(t)
    br = set(_breath(t))
    if br & {"fire", "dragonfire"} or t.get("fire_breather") is True:
        return "it breathes fire"
    if "poison_gas" in br or "deadly" in br:
        return "its breath is a cloud that lays out soldiers"
    if "dust" in br:
        return "it breathes dust (a syndrome)"
    if "web" in br or t.get("webs"):
        return "its webs hold soldiers who close in"
    return ""


def shoots(q: dict) -> bool:
    """A squad that shoots: the AI's crossbow uniform, or more ranged power than melee."""
    from planner_core import is_ranged
    m, r = squad_split(_d(q))
    return is_ranged(_d(q)) or r > m


def ranged_only(squads: list) -> list:
    """The squads with only their ranged power counted (they shoot from a post)."""
    out = []
    for q in squads or []:
        if isinstance(q, dict):
            r = squad_split(q)[1]
            if r > 0:
                p = dict(_d(q.get("power")), power=r, melee_power=0.0, ranged_power=r)
                out.append(dict(q, power=p))
    return out


def fight_bar_of(s: dict, memory, cfg: dict) -> float:
    """The bar a matchup must reach: the general engagement bar's `fight_bar`
    (planner_military, when there is one), else `fight_ratio`."""
    try:
        import planner_military as PM
        fb = getattr(PM, "fight_bar", None)
        if callable(fb):
            for args in ((s, memory, cfg), (s, cfg), (cfg,)):
                try:
                    v = fb(*args)
                except TypeError:
                    continue
                if isinstance(v, tuple):
                    v = v[0]
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    return float(v)
                break
    except Exception:  # noqa: BLE001  (the bar as before)
        pass
    return float((cfg or {}).get("fight_ratio", 2.0))


def beast_plan(t: dict, squads: list, bar: float, factor=None, trap_avoid=None) -> dict:
    """How to kill one great beast: {tactic, ready, goal, why, no_melee,
    melee: (army, need), ranged: (army, need), missing: [words]}.
    `tactic` is what is done now (a ready fight, else the trap or lure that
    holds it); `goal` the fight built toward (melee or ranged). `trap_avoid`:
    traps don't take it (True), do (False), unknown (None: as its facts say)."""
    t = _d(t)
    able = [q for q in squads or [] if isinstance(q, dict)]
    nm = melee_bar(t)
    full = judge(t, able, factor)
    rng_sq = ranged_only([q for q in able if shoots(q)])
    rng = judge(t, rng_sq, factor)
    need = float(full["need"] or 0.0)
    avoid = t.get("trap_avoid") if trap_avoid is None else trap_avoid
    out = {"no_melee": nm, "melee": (round(full["army"], 1), round(need, 1)),
           "ranged": (round(rng["army"], 1), round(need, 1)), "missing": [], "bar": bar}
    shooters = sum(int(_d(q.get("power")).get("ranged") or 0) for q in rng_sq)
    if not nm and full["ratio"] >= bar:
        out.update(tactic="melee", goal="melee", ready=True,
                   why=f"the squads {full['army']:.0f} against its {need:.0f}: about even or better")
        return out
    if rng["ratio"] >= bar and shooters > 0:
        out.update(tactic="ranged", goal="ranged", ready=True,
                   why=f"the crossbows {rng['army']:.0f} against its {need:.0f}"
                       + (f" ({nm}: no melee)" if nm else ""))
        return out
    goal = "ranged" if nm else "melee"
    if not rng_sq:
        out["missing"].append("a crossbow squad")
    elif not shooters:
        out["missing"].append("bolts in the crossbow squad's quivers")
    else:
        out["missing"].append(f"more crossbows (ranged {rng['army']:.0f} of {bar * need:.0f} needed)")
    if not nm:
        out["missing"].append(f"stronger squads (all {full['army']:.0f} of {bar * need:.0f} needed)")
    tactic = "lure" if avoid else "cage"
    out.update(tactic=tactic, goal=goal, ready=False,
               why=(f"{nm}: no melee; " if nm else "") + f"the squads {full['army']:.0f}, the crossbows "
                   f"{rng['army']:.0f} against its {need:.0f}: not yet even")
    return out
