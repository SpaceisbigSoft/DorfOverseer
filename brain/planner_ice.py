"""(0.105.47, I7d 2f) Ice: the surface water left alone before it freezes.

Why (E, 13 Nov): Tekkud and Erith drowned in the surface pond at 64,124 on the
first day of winter, at the AI's water zone (66,123, bank 67,123) and its
shore-well spot. At the same tick the AI noted "the water zones' water is
frozen" and tried a cavern water zone; the traffic over the frozen water was
restricted only the next day (planner_wells' water_traffic, once a month at
priority 6). The frost guard (planner_hazards, 0.105.41) acts only once the
water *is* ice.

`ice_season(s, memory, cfg)`: whether surface water counts as freezing now,
by the season and the biome's temperature (the env_hazards section's frost
part: surface_temp in Urist degrees, 10000 is the freezing point; freezing;
without that part, never: an older bridge keeps the old winter rules):
  * the surface freezing now, or within `ice_temp_margin` of it: yes, any month
    (a cold biome freezes in autumn, a glacier all year);
  * from `ice_late_autumn_tick` (the last half-month of autumn) through winter:
    yes, unless the surface is still `ice_warm_margin` over freezing and the AI
    never saw ice at this fort (memory.climate_freezes): a warm biome;
  * otherwise no.

While it is ice season (`_ice_rule`):
  * ice_zones: the AI's water source zones on surface water are taken down
    (bridge `retire_water_zones`, outside_only; lua/ai-ice.lua): the injured's
    water comes from a well or underground water (planner_wells'
    _water_zone_rule takes only underground or cavern water then; the frost
    guard's frost_water_zone did already);
  * ice_traffic: the tiles over the surface water get restricted traffic now,
    at priority 2 (the same restrict_water as planner_wells' water_traffic,
    whose monthly proposal is dropped in the same cycle);
  * ice_shore_well: a well project still being dug on a shore (its summary's
    `shore`) is cancelled; a new well goes inside only (planner_wells reads
    ice_season for its inside_only).
Nothing here touches a zone the player made: only the AI's own (its site
record), and only those on outside tiles.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, Proposal

__all__ = ["FREEZE", "ice_season", "_ice_rule"]

FREEZE = 10000          # DF's freezing point (Urist degrees)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _frost(s: dict) -> dict:
    e = _d(s.get("env_hazards"))
    if e.get("error") or "env_hazards" in _d(s.get("_errors")):
        return {}
    f = _d(e.get("frost"))
    return {} if f.get("error") else f


def ice_season(s: dict, memory=None, cfg: dict | None = None) -> tuple[bool, str]:
    """(on, why): does surface water count as freezing now? (see the module)"""
    cfg = PLANNER_CONFIG if cfg is None else cfg
    f = _frost(s)
    if not f:
        return False, ""        # no frost reading (an older bridge, a failed section): nothing said here
    temp = _num(f.get("surface_temp"))
    if f.get("freezing") is True:
        return True, "the surface is freezing"
    if temp is not None and temp <= FREEZE + cfg.get("ice_temp_margin", 15):
        return True, f"the surface is {int(temp - FREEZE)} degree(s) over freezing"
    date = _d(s.get("date"))
    yt = _num(date.get("tick"))
    late = date.get("season") == "winter" or (yt is not None and yt >= cfg.get("ice_late_autumn_tick", 285600)
                                              and date.get("season") == "autumn")
    if not late:
        return False, ""
    freezes = bool(memory is not None and getattr(memory, "climate_freezes", False))
    if temp is not None and temp > FREEZE + cfg.get("ice_warm_margin", 40) and not freezes:
        return False, ""
    return True, ("winter" if date.get("season") == "winter" else "the last half-month of autumn")


def _water_zone_rows(f: dict) -> list:
    return [z for z in _l(f.get("zones")) if isinstance(z, dict) and z.get("outside") is True
            and z.get("water") != "gone"]


def _ice_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    on, why = ice_season(s, memory, cfg)
    if not on:
        return
    # the AI's water zones on surface water: taken down before the ice
    zones = _water_zone_rows(_frost(s))
    if zones:
        where = ", ".join(f"x{z.get('x')} y{z.get('y')}" for z in zones[:3])
        proposals.append(Proposal("ice_zones", {"type": "retire_water_zones", "outside_only": True},
                                  f"{why}: the AI's water zone(s) on surface water ({where}) are taken down "
                                  "before the ice (E: two drowned at one on the first day of winter)", 2))
    # the traffic over the surface water restricted now, not a month later
    from planner_wells import _water_traffic_rule
    tmp: list = []
    _water_traffic_rule(s, tmp)
    if tmp:
        act = dict(tmp[0].action)
        proposals[:] = [p for p in proposals if p.rule != "water_traffic"]
        proposals.append(Proposal("ice_traffic", act,
                                  f"{why}: the water near the surface freezes soon: restrict traffic over it "
                                  "now, so the dwarves' paths go round the ice", 2))
    # a shore well still being dug: given up (a new one goes inside)
    for p in _l(_d(s.get("projects")).get("open")):
        if (isinstance(p, dict) and p.get("kind") == "well" and p.get("phase") == "dig"
                and _d(p.get("summary")).get("shore") and isinstance(p.get("id"), int)):
            proposals.append(Proposal("ice_shore_well", {"type": "cancel_project", "project_id": p["id"]},
                                      f"{why}: the well being dug on the shore (project {p['id']}) is given up "
                                      "before the water freezes; a well inside the fort instead", 3))
            break
