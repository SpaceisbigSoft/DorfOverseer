"""(0.105.41, item 7) Environment hazards: spilt magma, cave-ins, frost and heat.

The bridge's `env_hazards` section (lua/ai-hazards.lua report, in the pulse
too) says where magma lies that is no part of the map's own magma, the AI's
magma works or a magma workshop's pit (`magma`: the spots, how near the
dwarves, the AI magma work beside each, whether it spreads, dwarves standing
in it, the spots that cooled and the walls they left); the game's cave-in
announcements of the last days with the citizens hurt or cut off near each
(`cave_ins`); the surface's temperature, each well's and the AI's water
zones' water, the AI's moat, dwarves on ice (`frost`); and what burns or
melts by the magma workshops, the AI's magma works with a floodgate that
isn't magma-safe, dwarves burning or hot near magma (`heat`); the channels
the cave-in check refused (`channel_guard`).

The rules (_hazards_rule):
  * spilt magma near the dwarves: traffic restricted round it and the jobs
    beside it taken off (magma_guard); the AI's own magma work beside it
    shut (water_work shut); while it spreads near the dwarves the civilian
    alarm (magma_alarm, read by planner_military.hazard_alert, so the alarm
    stays up meanwhile and comes down after); said, with the dwarves in it;
  * once cooled `magma_cool_days`: the paths opened again and, with the
    Rules switch `magma_reclaim` (on by default), the walls it left where
    the dwarves walked dug out (magma_reclaim; never one beside liquid);
  * a cave-in: said with who is hurt (the Recover wounded labour fetches
    them: planner_threats' rescue rule puts dwarves on it) and who is cut
    off; cut off `cave_in_trapped_hours`, no way in being dug and no enemy
    able to reach the dwarves: a way dug to them (dig_way_in);
  * frost: every well frozen and none drawing water: a well inside the fort
    (place_well inside_only); the AI's water zones frozen while the injured
    or parched wait or drink is short: a water zone at underground water
    (water_zone); a frozen moat, dwarves on ice as it thaws: said. (Cold
    itself hurts no dwarf in DF: no outside work is paused for it.)
  * heat: what burns or melts by a magma workshop, a burning or hot dwarf,
    an AI floodgate that would melt: said (the player's items are never
    moved; the fire guard handles a fire).
Without the section (an older bridge, a fixture) nothing here proposes,
notes or remembers anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, PLANNER_CONFIG, Proposal, STEER_PROTECTED, TICKS_PER_DAY,
                          abs_tick)

__all__ = ["HAZARD_CONFIG", "env_of", "magma_alarm", "_hazards_rule"]

TICKS_PER_HOUR = 50

HAZARD_CONFIG = {
    "magma_alarm_near": 6,                   # spilt magma spreading this close to a dwarf (levels count 3): the alarm
    "magma_spread_hold_ticks": 150,          # "spreading" this long after the last new tile (3 game hours)
    "magma_guard_near": 6,                   # spilt magma this close to a dwarf is guarded (lua/ai-hazards.lua MAGMA_NEAR)
    "magma_guard_radius": 3,                 # tiles round the spilt magma restricted
    "magma_guard_jobs": 40,                  # jobs beside it taken off at most each time
    "magma_guard_cooldown_ticks": 100,
    "magma_shut_near": 20,                   # the AI's magma work this close to spilt magma: its floodgate shut
    "magma_shut_cooldown_ticks": 300,
    "magma_cool_days": 3,                    # no magma on a spilt tile this long: cooled, reclaimed
    "magma_reclaim_cooldown_ticks": 1200,
    "cave_in_trapped_hours": 6,              # cut off by a cave-in this long: a way dug to them
    "cave_in_dig_out_cooldown_ticks": 2 * 1200,
    "frost_well_cooldown_ticks": 14 * 1200,
    "frost_water_zone_cooldown_ticks": 3 * 1200,
}
PLANNER_CONFIG.update({k: v for k, v in HAZARD_CONFIG.items() if k not in PLANNER_CONFIG})

# the magma guard and the floodgate shut wait for no action slot, and the strategist never holds them
LIMIT_EXEMPT.update({"magma_guard", "magma_shut"})
STEER_PROTECTED.update({"magma_guard", "magma_shut"})
AGENDA_THEMES.update({"magma_guard": "keep the dwarves away from spilt magma",
                      "magma_shut": "shut the magma works by spilt magma",
                      "magma_reclaim": "reclaim the ground spilt magma left",
                      "cave_in_dig_out": "dig out the dwarves a cave-in cut off",
                      "frost_well": "a well inside the fort while the surface water is frozen",
                      "frost_water_zone": "water from underground while the surface water is frozen"})


def _c(cfg: dict, k: str):
    return cfg.get(k, PLANNER_CONFIG[k])


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _where(r: dict) -> str:
    return f"x{r.get('x')} y{r.get('y')} z{r.get('z')}"


def _names(rows: list, n: int = 3) -> str:
    rows = [r for r in rows if isinstance(r, dict)]
    out = ", ".join(str(r.get("name") or "a dwarf") for r in rows[:n])
    return out + (f" and {len(rows) - n} more" if len(rows) > n else "")


def env_of(s: dict) -> dict:
    """The env_hazards section; {} when absent or failed."""
    e = _d(s.get("env_hazards"))
    return {} if e.get("error") or "env_hazards" in _d(s.get("_errors")) else e


def _part(e: dict, name: str) -> dict:
    p = _d(e.get(name))
    return {} if p.get("error") else p


def magma_alarm(s: dict, cfg: dict) -> str:
    """Why spilt magma keeps the civilian alarm up ("" if not): it spreads
    (a new tile within `magma_spread_hold_ticks`) within `magma_alarm_near`
    of a dwarf. Read by planner_military.hazard_alert."""
    m = _part(env_of(s), "magma")
    ago = m.get("grew_ago")
    if not (_int(ago) and ago <= _c(cfg, "magma_spread_hold_ticks")):
        return ""
    near = [c for c in _l(m.get("cells")) if isinstance(c, dict) and _int(c.get("near"))
            and c["near"] <= _c(cfg, "magma_alarm_near")]
    if not near:
        return ""
    c = min(near, key=lambda c: c["near"])
    return f"spilt magma spreading {c['near']} tiles from the dwarves at {_where(c)}"


def _magma(s, cfg, e, memory, proposals, notes):
    m = _part(e, "magma")
    if not m:
        return
    cells = [c for c in _l(m.get("cells")) if isinstance(c, dict)]
    loose = int(m.get("loose") or 0)
    burning = [b for b in _l(m.get("burning")) if isinstance(b, dict)]
    if burning:
        notes.append(f"{len(burning)} dwarf(s) stand in magma: {_names(burning)}")
    if loose > 0:
        spread = _int(m.get("grew_ago")) and m["grew_ago"] <= _c(cfg, "magma_spread_hold_ticks")
        where = "; ".join(f"{_where(c)} ({c.get('n')} tile(s)"
                          + (f", {c['near']} tiles from a dwarf" if _int(c.get("near")) else "") + ")"
                          for c in cells[:3])
        notes.append(f"spilt magma: {loose} tile(s) where no magma belongs"
                     + (" and spreading" if spread else "") + f": {where}")
        near = [c for c in cells if _int(c.get("near")) and c["near"] <= _c(cfg, "magma_guard_near")]
        if near:
            proposals.append(Proposal("magma_guard", {"type": "magma_guard",
                                                      "radius": _c(cfg, "magma_guard_radius"),
                                                      "max_jobs": _c(cfg, "magma_guard_jobs")},
                                      f"spilt magma {near[0]['near']} tiles from the dwarves at {_where(near[0])}: "
                                      "paths round it restricted, the work beside it called off", 0))
        works = _d(_d(s.get("waterworks")).get("works"))
        done = set()
        for c in cells:
            wid = c.get("work")
            if not wid or wid in done or not (_int(c.get("work_d")) and c["work_d"] <= _c(cfg, "magma_shut_near")):
                continue
            done.add(wid)
            row = _d(works.get(wid))
            shop = c.get("work_shop") or row.get("shop") or str(wid).split(":")[-1]
            if row.get("gate") == "open":
                proposals.append(Proposal("magma_shut", {"type": "water_work", "kind": "magma", "shop": shop,
                                                         "shut": True, "why": "spilt magma near it"},
                                          f"spilt magma {c['work_d']} tiles from the AI's magma works ({shop}): "
                                          "its floodgate shut", 0))
            elif row.get("gate") == "shut":
                notes.append(f"spilt magma near the AI's magma works ({shop}): its floodgate is shut")
    # cooled: the paths opened again, the walls it left dug out (the Rules switch)
    cool = _c(cfg, "magma_cool_days") * TICKS_PER_DAY
    settled = [c for c in _l(m.get("settled")) if isinstance(c, dict)]
    ready = [c for c in settled if _int(c.get("dry")) and c["dry"] >= cool]
    waiting = [c for c in settled if _int(c.get("dry")) and c["dry"] < cool]
    restricted = int(m.get("restricted") or 0)
    if ready or (loose == 0 and restricted > 0 and not waiting):
        dig = _d(s.get("settings")).get("magma_reclaim") is not False
        walls = sum(int(c.get("walls") or 0) for c in ready)
        proposals.append(Proposal("magma_reclaim", {"type": "magma_reclaim", "cool_ticks": cool, "dig": dig},
                                  (f"spilt magma cooled at {_where(ready[0])} ({ready[0].get('n')} tile(s), dry "
                                   f"{ready[0]['dry'] // TICKS_PER_DAY} day(s)): " if ready else
                                   "the spilt magma is gone: ")
                                  + "the paths opened again"
                                  + (f", the {walls} wall(s) it left dug out" if dig and walls else
                                     " (the Rules leave what it left alone)" if not dig and walls else ""), 4))
    elif waiting:
        c = waiting[0]
        notes.append(f"spilt magma at {_where(c)} has cooled for {c['dry'] // TICKS_PER_HOUR} hour(s): "
                     f"reclaimed after {_c(cfg, 'magma_cool_days')} day(s)")


def _cave_ins(s, cfg, e, memory, proposals, notes):
    cv = _part(e, "cave_ins")
    spots = [c for c in _l(cv.get("list")) if isinstance(c, dict)]
    if not spots:
        return
    rescue = _d(_d(s.get("threats")).get("rescue"))
    holders = rescue.get("holders")
    trapped_all = []
    for c in spots:
        hurt = [h for h in _l(c.get("hurt")) if isinstance(h, dict)]
        trapped = [t for t in _l(c.get("trapped")) if isinstance(t, dict)
                   and all(_int(t.get(k)) for k in ("x", "y", "z"))]
        ago = c.get("ago") if _int(c.get("ago")) else 0
        bits = [f"a cave-in {ago // TICKS_PER_HOUR} hour(s) ago" + (f" at {_where(c)}" if _int(c.get("x")) else "")]
        if hurt:
            bits.append(f"{len(hurt)} hurt near it ({_names(hurt)}): "
                        + ("nobody has the Recover wounded labour yet, 2 are put on it" if holders == 0 else
                           f"{holders} dwarf(s) may fetch them" if _int(holders) else "they are fetched to bed"))
        if trapped:
            bits.append(f"{len(trapped)} cut off by it ({_names(trapped)})")
            trapped_all.append((ago, trapped))
        notes.append("; ".join(bits))
    if not trapped_all:
        return
    after = _c(cfg, "cave_in_trapped_hours") * TICKS_PER_HOUR
    old = [(a, t) for a, t in trapped_all if a >= after]
    if not old:
        notes.append(f"the dwarves cut off by the cave-in may dig or find their own way out: a way is dug to them "
                     f"after {_c(cfg, 'cave_in_trapped_hours')} hour(s)")
        return
    reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
    if reach > 0:
        notes.append(f"dwarves cut off by a cave-in, but {reach} enemy(ies) can reach the dwarves: no way is dug to "
                     "them until that is over")
        return
    from planner_gates import _way_in_doing
    doing = _way_in_doing(s, memory, second=False)
    if doing:
        notes.append(f"a way is being dug to the dwarves cut off by the cave-in ({doing})")
        return
    rows = old[0][1]
    import statistics
    x, y, z = (int(statistics.median_low([r[k] for r in rows])) for k in ("x", "y", "z"))
    proposals.append(Proposal("cave_in_dig_out", {"type": "dig_way_in", "x": x, "y": y, "z": z},
                              f"{len(rows)} dwarf(s) cut off by a cave-in for {old[0][0] // TICKS_PER_HOUR} hour(s) "
                              f"({_names(rows)}): dig a way to them from x{x} y{y} z{z}", 1))


def _need_water(s: dict, cfg: dict) -> str:
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    parched = int(_d(s.get("society")).get("parched") or 0)
    citizens = max(1, int(_d(s.get("dwarves")).get("total") or 1))
    drink = _d(s.get("stocks")).get("drink")
    dry = isinstance(drink, (int, float)) and drink < citizens * _c(cfg, "urgent_drink_per_dwarf")
    return " and ".join(x for x in (f"{patients} injured" if patients else "", f"{parched} parched" if parched else "",
                                    f"drink short ({drink} for {citizens})" if dry else "") if x)


def _frost(s, cfg, e, memory, proposals, notes):
    f = _part(e, "frost")
    if not f:
        return
    wells = [w for w in _l(f.get("wells")) if isinstance(w, dict)]
    good = [w for w in wells if w.get("water") == "water"]
    frozen = [w for w in wells if w.get("water") == "ice"]
    open_ = [p for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)]
    if frozen and not good:
        need = _need_water(s, cfg)
        if any(p.get("kind") == "well" for p in open_):
            notes.append(f"{len(frozen)} well(s) frozen: a new well is being dug")
        else:
            act = {"type": "place_well", "inside_only": True}
            if need:
                act["urgent"] = True
            proposals.append(Proposal("frost_well", act,
                                      f"{len(frozen)} well(s) draw only ice now" + (f" ({need})" if need else "")
                                      + ": a well inside the fort, over water that doesn't freeze", 2 if need else 4))
    elif frozen:
        notes.append(f"{len(frozen)} of {len(wells)} well(s) frozen; {len(good)} still draw water")
    zones = [z for z in _l(f.get("zones")) if isinstance(z, dict)]
    if zones and not good and all(z.get("water") != "water" for z in zones):
        need = _need_water(s, cfg)
        if need:
            from planner_wells import cavern_danger
            danger = cavern_danger(s)
            far = cfg.get("water_zone_max_d", 120)
            bodies = [b for b in _l(_d(s.get("water")).get("bodies"))
                      if isinstance(b, dict) and isinstance(b.get("nearest"), dict)
                      and (b.get("underground") or b.get("kind") == "cavern")
                      and not (danger and b.get("kind") == "cavern")
                      and b.get("kind") not in ("ice", "magma", "aquifer")
                      and (b.get("salt_share") or 0) < 50 and (b["nearest"].get("d") or 999) <= far]
            bodies.sort(key=lambda b: (b.get("kind") == "cavern", b["nearest"].get("d") or 999))
            points = [{k: b["nearest"].get(k) for k in ("x", "y", "z")} for b in bodies[:6]
                      if all(_int(b["nearest"].get(k)) for k in ("x", "y", "z"))]
            if points:
                proposals.append(Proposal("frost_water_zone", {"type": "water_zone", "points": points},
                                          f"the water zones' water is frozen and {need}: a water zone at "
                                          "underground water, which doesn't freeze", 1))
            else:
                notes.append(f"the water zones' water is frozen and {need}, and no underground water is known near "
                             "the fort: the dwarves drink what's brewed")
    moat = _d(f.get("moat"))
    if moat.get("frozen"):
        notes.append("the AI's moat is frozen: enemies can walk across it until the thaw (the gates still close)")
    on_ice = [u for u in _l(f.get("on_ice")) if isinstance(u, dict)]
    season = _d(s.get("date")).get("season")
    if on_ice and (season == "spring" or f.get("freezing") is False):
        notes.append(f"{len(on_ice)} dwarf(s) stand on ice as it thaws ({_names(on_ice)}): ice melting under a "
                     "dwarf drops them in the water")


def _heat(s, cfg, e, proposals, notes):
    h = _part(e, "heat")
    if not h:
        return
    for sh in [x for x in _l(h.get("shops")) if isinstance(x, dict)]:
        b, mlt, fire = int(sh.get("burns") or 0), int(sh.get("melts") or 0), int(sh.get("on_fire") or 0)
        if fire:
            notes.append(f"{fire} thing(s) burn beside the {sh.get('kind')} at {_where(sh)}")
        elif b or mlt:
            notes.append(f"beside the {sh.get('kind')} at {_where(sh)}: "
                         + " and ".join(x for x in (f"{b} thing(s) that burn" if b else "",
                                                    f"{mlt} that melt" if mlt else "") if x)
                         + " at magma's heat (left where they lie: the haulers take them to their piles)")
    for w in [x for x in _l(h.get("works")) if isinstance(x, dict)]:
        notes.append(f"the AI's magma works ({w.get('shop') or w.get('id')}) has a floodgate that isn't magma-safe: "
                     "it would melt; the works aren't opened to the magma with it")
    burning = [u for u in _l(h.get("burning")) if isinstance(u, dict)]
    if burning:
        notes.append(f"{len(burning)} dwarf(s) on fire by the magma: {_names(burning)} (they run for water; the "
                     "fire guard keeps the others away from the flames)")
    hot = [u for u in _l(h.get("hot")) if isinstance(u, dict)]
    if hot:
        notes.append(f"{len(hot)} dwarf(s) overheating by the magma: {_names(hot)}")


def _channels(s, cfg, e, notes):
    g = _d(e.get("channel_guard"))
    n = g.get("refused")
    last = _d(g.get("last"))
    if _int(n) and n > 0 and last:
        ago = abs_tick(s) - last["tick"] if _int(last.get("tick")) else None
        if ago is not None and 0 <= ago <= TICKS_PER_DAY:
            notes.append(f"{n} channel(s) refused since the map loaded (a cave-in): the last at {_where(last)}: "
                         f"{last.get('why')}")


def _hazards_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Spilt magma, cave-ins, frost and heat (see the module's words)."""
    e = env_of(s)
    if not e:
        return
    for name, fn, args in (("magma", _magma, (s, cfg, e, memory, proposals, notes)),
                           ("cave_ins", _cave_ins, (s, cfg, e, memory, proposals, notes)),
                           ("frost", _frost, (s, cfg, e, memory, proposals, notes)),
                           ("heat", _heat, (s, cfg, e, proposals, notes)),
                           ("channels", _channels, (s, cfg, e, notes))):
        try:
            fn(*args)
        except Exception as ex:  # noqa: BLE001  (one part failing leaves the others)
            notes.append(f"hazard rule {name} failed ({type(ex).__name__}: {str(ex)[:100]})")

