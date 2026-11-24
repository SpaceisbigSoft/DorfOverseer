"""planner_defence_floor: a defence floor by threat (0.105.54, the player, 15 Nov: "fight back").

Every fort keeps enough soldiers to win a roughly even fight against the
biggest threat it has faced or sees now, whatever its Militarism; the
slider only adds above it (its share stays the target when larger).

- The threat now: the invaders on the map summed (a siege is one fight),
  each great danger alone (a forgotten beast, a titan...), by
  planner_military.threat_power, a great danger times what the fort
  learned of its kind (memory.fight_factor, capped).
- The threat remembered: the biggest seen (memory.defence_floor["peak"]),
  halving every `floor_half_life_days` once it has gone, down to
  `floor_keep_share` of it (the fort is a known target).
- The likely threat from history without a record (a fort from before
  this): sieges on record (culture, the world report) and great dangers
  seen (slain beasts, fights, memory.last_great_tick) at nominal powers.
- Squad power wanted: the largest of these times `floor_fight_ratio`
  (about even); soldiers: that over the fort's average soldier power (the
  squads' `power` per member), capped at `floor_max_share` of the adults
  (and, in soldiers_wanted, the civilian cap). The bridge's fill never
  drafts the last farmer or brewer outside the squads (lua/ai-military.lua).
- (0.105.97) The floor follows the fort's character and lets go: with no
  threat on the map now the cap falls with Militarism below 0 (a third at 0,
  `floor_max_share_peaceful` at -50 and below); a threat here now keeps the
  full third (survival first). The remembered threat and the history keep
  `floor_keep_share` only for `floor_keep_days` (two years), then halve every
  `floor_fade_half_life_days` and are forgotten below `floor_forget_share`:
  one beast gives no floor for ever. B, 23 Nov (Militarism -60): Stuxul's
  184.3, a year gone, kept 46 for good; the soldiers being weak, the floor
  asked the 33% cap (35-44 soldiers of ~88 adults for years; the slider wants
  ~12-15), the soldiers missing friends and drink.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import TICKS_PER_DAY, abs_tick, wildlife_threat

__all__ = ["defence_floor", "note_defence_floor", "floor_note", "present_threat", "soldier_power_avg",
           "history_threat", "peaceful_ranged", "floor_cap_share"]

# the kinds whose learned factor (memory.fight_factor) a nominal beast takes
BEAST_KEYS = ("ForgottenBeast", "Titan", "Megabeast", "Demon", "SemiMegabeast")


from util import num_or_none as _num  # noqa: E402  (r6 c2) was a copy here


def _great(t: dict) -> bool:
    return bool(t.get("great_danger") or set(_l(t.get("kinds"))) & set(BEAST_KEYS))


def present_threat(s: dict, memory, cfg: dict) -> tuple[float, str]:
    """The biggest fight on the map now: (power, words). The invaders
    together, or the strongest great danger alone. Wildlife is not counted."""
    from planner_military import fight_key, threat_power
    rows = [t for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and not wildlife_threat(t, cfg)]
    ff = _d(getattr(memory, "fight_factor", None)) if memory is not None else {}
    cap = float(cfg.get("floor_learned_max", 4.0))

    def learned(t):
        return min(cap, max(1.0, float(_num(ff.get(fight_key(t))) or 1.0)))
    inv = [t for t in rows if t.get("invader")]
    siege = sum(threat_power(t) * (learned(t) if _great(t) else 1.0) for t in inv)
    beasts = [(threat_power(t) * learned(t), t) for t in rows if not t.get("invader") and _great(t)]
    best_b = max(beasts, key=lambda x: x[0]) if beasts else (0.0, None)
    if siege <= 0 and best_b[0] <= 0:
        return 0.0, ""
    if siege >= best_b[0]:
        return siege, f"{len(inv)} invader(s) on the map (strength {siege:.0f})"
    t = best_b[1]
    name = str(t.get("name") or "a great danger").split(",")[0][:40]
    return best_b[0], f"{name} on the map (strength {best_b[0]:.0f})"


def _fade(age_days, cfg: dict) -> float:
    """(0.105.97) What is still kept of a threat gone `age_days`: all of it
    for `floor_keep_days`, then halving every `floor_fade_half_life_days`,
    nothing once below `floor_forget_share`. 1.0 when the age is unknown."""
    if age_days is None:
        return 1.0
    keep = float(cfg.get("floor_keep_days", 672))
    if age_days <= keep:
        return 1.0
    half = max(1.0, float(cfg.get("floor_fade_half_life_days", 84)))
    f = 0.5 ** ((age_days - keep) / half)
    return 0.0 if f < float(cfg.get("floor_forget_share", 0.08)) else f


def _year_now(s: dict):
    y = _num(_d(s.get("date")).get("year"))
    return int(y) if y is not None else None


def _last_siege_year(s: dict, memory):
    culture = _d(getattr(memory, "culture", None)) if memory is not None else {}
    ys = [_num(culture.get("last_siege_year"))] + [_num(_d(e).get("last_year"))
                                                   for e in _l(_d(s.get("world")).get("sieges"))]
    ys = [int(y) for y in ys if y is not None]
    return max(ys) if ys else None


def _sieges(s: dict, memory) -> int:
    culture = _d(getattr(memory, "culture", None)) if memory is not None else {}
    world = sum(int(_num(_d(e).get("n")) or 0) for e in _l(_d(s.get("world")).get("sieges")))
    return max(int(_num(culture.get("sieges")) or 0), world)


def history_threat(s: dict, memory, cfg: dict) -> tuple[float, str]:
    """The likely threat from what the fort has lived through, at nominal
    strengths: (power, words). The fort is a known target: it is kept whole
    for `floor_keep_days` after the last siege (by the game year:
    culture.last_siege_year, the world report's last_year) or the last great
    danger seen (memory.last_great_tick), then fades as the remembered peak
    does (0.105.97); an age not known doesn't fade."""
    out, why = 0.0, ""
    n = _sieges(s, memory)
    if n > 0:
        p = float(cfg.get("floor_siege_power", 40)) * min(2.0, 1 + 0.25 * (n - 1))
        ly, ny = _last_siege_year(s, memory), _year_now(s)
        age = (ny - ly) * float(cfg.get("floor_days_per_year", 336)) if ly is not None and ny is not None else None
        f = _fade(age, cfg)
        if f < 1.0:
            out, why = p * f, f"{n} siege(s) on record (the last y{ly}, fading)"
        else:
            out, why = p, f"{n} siege(s) on record"
    if memory is not None:
        culture = _d(getattr(memory, "culture", None))
        slain = len(_l(culture.get("beasts_slain")))
        fights = len(_l(getattr(memory, "fights", None)))
        seen = slain or fights or int(_num(getattr(memory, "last_great_tick", 0)) or 0) > 0
        if seen:
            ff = _d(getattr(memory, "fight_factor", None))
            learned = max([float(_num(ff.get(k)) or 1.0) for k in BEAST_KEYS] + [1.0])
            p = float(cfg.get("floor_beast_power", 30)) * min(float(cfg.get("floor_learned_max", 4.0)), learned)
            lt = _num(getattr(memory, "last_great_tick", None))
            age = (abs_tick(s) - lt) / TICKS_PER_DAY if lt and lt > 0 else None
            f = _fade(max(0.0, age) if age is not None else None, cfg)
            p *= f
            if p > out:
                out = p
                why = ("great dangers seen" + (f" ({slain} slain)" if slain else "")
                       + (f", learned {learned:g}x stronger than they look" if learned > 1 else "")
                       + (", fading" if f < 1.0 else ""))
    return out, why


def soldier_power_avg(s: dict, cfg: dict) -> tuple[float, bool]:
    """The fort's average soldier's power (squads' power per member), within
    bounds; (value, known). The nominal `floor_soldier_power` when unknown."""
    tot, n = 0.0, 0
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("training_squad"):
            continue
        p, m = _num(_d(q.get("power")).get("power")), _num(q.get("members"))
        if p is not None and m and m > 0:
            tot, n = tot + float(p), n + int(m)
    if n <= 0 or tot <= 0:
        return float(cfg.get("floor_soldier_power", 4.0)), False
    return max(float(cfg.get("floor_soldier_power_min", 1.5)),
               min(float(cfg.get("floor_soldier_power_max", 15.0)), tot / n)), True


def _peak_age(peak: dict, now: int):
    t = _num(_d(peak).get("tick"))
    return None if t is None else max(0.0, (now - t) / TICKS_PER_DAY)


def _decayed(peak: dict, now: int, cfg: dict) -> float:
    """The remembered peak now: halving every `floor_half_life_days`, kept at
    `floor_keep_share` of it for `floor_keep_days`; (0.105.97) after that the
    kept share halves too (_fade), down to nothing."""
    p = float(_num(_d(peak).get("power")) or 0)
    age_days = _peak_age(peak, now)
    if p <= 0 or age_days is None:
        return 0.0
    half = max(1.0, float(cfg.get("floor_half_life_days", 168)))
    v = max(p * 0.5 ** (age_days / half), p * float(cfg.get("floor_keep_share", 0.25)) * _fade(age_days, cfg))
    return 0.0 if v < p * float(cfg.get("floor_forget_share", 0.08)) * float(cfg.get("floor_keep_share", 0.25)) else v


def floor_cap_share(s: dict, cfg: dict, present: float) -> float:
    """(0.105.97) The floor's cap as a share of the adults: `floor_max_share`
    while a threat is on the map now or at Militarism 0 and above; below 0 it
    falls in a straight line to `floor_max_share_peaceful` at -50 and below
    (B at -60: 12%, not a third, of the adults for a beast long gone)."""
    hi = float(cfg.get("floor_max_share", 0.33))
    if present > 0:
        return hi
    lo = min(hi, float(cfg.get("floor_max_share_peaceful", 0.12)))
    traits = _d(_d(s.get("settings")).get("traits"))
    mil = float(_num(traits.get("militarism")) or 0)
    if mil >= 0:
        return hi
    t = min(1.0, -mil / 50.0)
    return hi + (lo - hi) * t


def defence_floor(s: dict, memory, cfg: dict, citizens: int | None = None) -> dict:
    """The defence floor: {soldiers, power (wanted), threat, why, per_soldier,
    present, cap}. soldiers 0 when the fort has met no threat."""
    now = abs_tick(s)
    pres, pwhy = present_threat(s, memory, cfg)
    peak = _d(_d(getattr(memory, "defence_floor", None)).get("peak")) if memory is not None else {}
    mem = _decayed(peak, now, cfg)
    hist, hwhy = history_threat(s, memory, cfg)
    age = _peak_age(peak, now)
    keep_d = float(cfg.get("floor_keep_days", 672))
    fade_w = ""
    if mem < float(_num(peak.get("power")) or 0) - 0.5:
        fade_w = f" (fading from {float(peak.get('power') or 0):.0f}"
        if age is not None:
            # (0.105.97) the note says when the kept share starts to go
            fade_w += (f", {age:.0f} days ago; let go after {keep_d:.0f} days)" if age <= keep_d
                       else f", {age:.0f} days ago: being forgotten)")
        else:
            fade_w += ")"
    cands = [(pres, pwhy), (mem, (f"{peak.get('why')}, remembered" if peak.get("why") else "a past threat")
                            + fade_w),
             (hist, hwhy)]
    threat, why = max(cands, key=lambda c: c[0])
    out = {"soldiers": 0, "power": 0.0, "threat": round(threat, 1), "why": why, "present": round(pres, 1),
           "per_soldier": 0.0, "cap": None}
    if threat <= 0:
        return out
    per, known = soldier_power_avg(s, cfg)
    need = threat * float(cfg.get("floor_fight_ratio", 1.0))
    n = math.ceil(need / per - 1e-9)
    adults = _d(s.get("dwarves")).get("adults")
    if not isinstance(adults, int) or isinstance(adults, bool):
        adults = citizens if isinstance(citizens, int) else _d(s.get("dwarves")).get("total")
    adults = int(adults or 0)
    if isinstance(citizens, int) and citizens > 0:
        adults = min(adults, citizens) if adults else citizens
    share = floor_cap_share(s, cfg, pres)          # (0.105.97) by Militarism with no threat here now
    cap = int(adults * share)
    # (as soldiers_wanted) a handful of dwarves keep to their work unless a threat is on the map now
    if (citizens or adults) < cfg.get("squad_min_citizens", 0) and pres <= 0:
        cap = 0
    out.update({"soldiers": max(0, min(n, cap)), "wanted": n, "power": round(need, 1), "per_soldier": round(per, 1),
                "per_known": known, "cap": cap, "cap_share": round(share, 3),
                "militarism": int(float(_num(_d(_d(s.get("settings")).get("traits")).get("militarism")) or 0))})
    return out


def note_defence_floor(s: dict, memory, cfg: dict) -> None:
    """Remember the threat seen now when it is the biggest yet (as it fades):
    the floor rises at once and decays over seasons after."""
    if memory is None:
        return
    pres, why = present_threat(s, memory, cfg)
    if pres <= 0:
        return
    d = getattr(memory, "defence_floor", None)
    d = d if isinstance(d, dict) else {}
    now = abs_tick(s)
    if pres >= _decayed(_d(d.get("peak")), now, cfg) - 1e-9:
        d["peak"] = {"power": round(pres, 1), "tick": now, "why": why.split(" (strength")[0]}
    memory.defence_floor = d


def floor_note(f: dict, have: int, militarism_want: int) -> str:
    """The note line: the floor, why, and the current soldiers."""
    if not f or f.get("threat", 0) <= 0:
        return ""
    extra = f" (cap; {f.get('wanted')} to match)" if f.get("wanted", 0) > f.get("soldiers", 0) else ""
    # (0.105.97) the cap said: a third while a threat is here, less in a peaceful fort
    sh = f.get("cap_share")
    if extra and isinstance(sh, (int, float)):
        extra = (f" (cap {f.get('cap')} = {sh * 100:.0f}% of the adults"
                 + (" while a threat is on the map" if f.get("present", 0) > 0 else
                    f" at Militarism {f.get('militarism', 0):+d}" if sh < 0.33 - 1e-6 else "")
                 + f"; {f.get('wanted')} to match)")
    by = "" if f.get("per_known") else "?"
    return (f"Defence floor {f['soldiers']}{extra}: {f.get('why')}; even fight {f.get('power', 0):.0f} at "
            f"{f.get('per_soldier', 0):g}{by}/soldier; Militarism {militarism_want}; soldiers {have}")


def peaceful_ranged(s: dict, traits: dict) -> bool:
    """(0.105.54) A peaceful fort (Militarism below 0) leans to crossbows:
    its squads shoot, where bolts can be made (a bowyer's, wood, or a forge)."""
    if float(_num(_d(traits).get("militarism")) or 0) >= 0:
        return False
    g = _d(_d(s.get("military")).get("gear"))
    from planner_core import _has_shop
    wood = int(_num(_d(s.get("stocks")).get("wood")) or 0)
    return bool(_has_shop(s.get("buildings") or {}, "Bowyers") or wood > 0 or g.get("forges"))
