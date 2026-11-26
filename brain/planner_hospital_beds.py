"""planner_hospital_beds (item7): the hospitals' beds by the population.

The scorecard of 26 Nov 00:04: "hospital beds per 100 dwarves (peak)" A 4,
B 8, C 5.6, D 8.8, E 4, F 7.9 (Welfare's line failed: D, the Hermit hold
at 55 dwarves, came out on top). Every hospital zone held the 4-5 beds its
level was dug with (9x9 meeting halls, room for more), and beds came after
only as a whole new hospital level (planner_building_rooms.hospital_shortfall:
for the wounded lying on the floor, or, above Welfare 0, past 4 beds short in
settled times). E, the Deep mine, 97 dwarves, the most fights and wounded of
the six (34 deaths in the run): 4 beds.

Now the hospitals' zones are filled up to a target by the population and the
Welfare slider: ceil(citizens / 20 x f) + ceil(2 x f) beds, f = 2^(Welfare/100),
at least 4, never past hospital_beds_max (War-hold -40 at 100 dwarves: 6,
neutral: 7, Garden fort +40: 10, Monastery +80: 13). A free bed goes into the
hospital zone with the most free floor (place_in_zone what=bed; a zone the
bridge found full is booked full and passed over); with no free bed, beds are
ordered at the carpenter's. A bed placed counts at once (the bridge's
beds_planned: on the zone's tiles at any stage), so none is placed twice.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import AGENDA_THEMES, Proposal, _has_shop, abs_tick, queued

__all__ = ["hospital_bed_target", "hospital_beds_have", "hospital_beds_rule"]

AGENDA_THEMES["hospital_beds"] = "care for the injured"
BED_ORDER_MAX = 5          # beds ordered at a time
ZONE_SPOT_TILES = 3        # floor tiles a piece of furniture takes up, with the way past it


def hospital_bed_target(citizens: int, traits: dict, cfg: dict) -> int:
    """The beds the hospitals keep for `citizens` at this Welfare."""
    f = 2 ** ((traits.get("welfare", 0) or 0) / 100)
    want = math.ceil(max(0, citizens) / 20 * f) + math.ceil(2 * f)
    return max(4, min(int(cfg.get("hospital_beds_max", 30)), want))


def _zones(s: dict) -> list:
    return [z for h in _l(_d(s.get("health")).get("hospital")) for z in _l(_d(h).get("zones"))
            if isinstance(z, dict) and isinstance(z.get("id"), int)]


def _beds(z: dict) -> int:
    return max(int(z.get("beds") or 0), int(z.get("beds_planned") or 0))


def hospital_beds_have(s: dict) -> int:
    """The hospital zones' beds, built or placed."""
    return sum(_beds(z) for z in _zones(s))


def _free_floor(z: dict) -> int:
    try:
        area = (int(z["x2"]) - int(z["x1"]) + 1) * (int(z["y2"]) - int(z["y1"]) + 1)
    except (KeyError, TypeError, ValueError):
        area = 0
    used = _beds(z) + max(int(z.get("traction") or 0), int(z.get("traction_planned") or 0)) \
        + int(z.get("tables") or 0) + int(z.get("chests") or 0)
    return area - ZONE_SPOT_TILES * used


def hospital_beds_rule(s: dict, traits: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """A bed into a hospital zone (or beds ordered) while the hospitals hold
    fewer than hospital_bed_target. An older bridge (no supplies.beds) asks nothing."""
    if not _d(_d(s.get("locations")).get("count")).get("HOSPITAL"):
        return                              # the first hospital is the ladder's
    sup = _d(s.get("supplies"))
    if not isinstance(sup.get("beds"), int) or isinstance(sup.get("beds"), bool):
        return
    zones = _zones(s)
    if not zones:
        return
    cit = int(_d(s.get("dwarves")).get("total") or 0)
    want, have = hospital_bed_target(cit, traits, cfg), hospital_beds_have(s)
    if have >= want:
        return
    if memory is not None:
        from planner_core_refusals import zone_full_days
        try:
            now = abs_tick(s)
        except Exception:  # noqa: BLE001
            now = None
        if isinstance(now, int):
            zones = [z for z in zones if zone_full_days(memory, z["id"], now) is None]
    zones = [z for z in zones if _free_floor(z) > 0 or "x1" not in z]
    if not zones:
        notes.append(f"the hospitals have {have} beds for {cit} dwarves ({want} wanted) and no free floor "
                     "in their zones: more come with another hospital")
        return
    why = f"the hospitals have {have} beds for {cit} dwarves and the fort keeps {want}"
    if sup["beds"] > 0:
        zone = max(zones, key=lambda z: (_free_floor(z), -z["id"]))
        proposals.append(Proposal("hospital_beds", {"type": "place_in_zone", "zone_id": zone["id"], "what": "bed"},
                                  f"{why}: a free bed into the hospital", 4))
        return
    if queued(s, {"wooden_bed"}):
        return
    if not _has_shop(_d(s.get("buildings")), "Carpenters"):
        notes.append(f"{why}: beds wait for a Carpenter's workshop")
        return
    if int(_d(s.get("stocks")).get("wood") or 0) < 2:
        notes.append(f"{why}: beds wait for wood")
        return
    n = min(BED_ORDER_MAX, want - have)
    proposals.append(Proposal("hospital_beds", {"type": "work_order", "recipe": "wooden_bed", "amount": n},
                              f"{why} and no bed is free: make {n} at the carpenter's", 5, True))
