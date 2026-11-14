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

__all__ = ["BREATH_WEIGHT", "facts_mult", "squad_weights", "squad_split", "judge", "matchup"]

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
    squads go at fight_ratio (PLANNER_CONFIG) or better."""
    j = judge(t, squads, factor)
    return j["ratio"], j["reasons"]
