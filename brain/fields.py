"""(0.105.47) The fort's fields above ground, for the Garden fort's customs.

The run of 14 Nov: the Garden fort (F) had 12 farm plots under the sky and
its `field_hall` / `field_kitchens` customs never fired ("halls and kitchens
by the fields" read 0): the masterplan only moved a level to the farms when
the soil lay 3 or more levels underground. The surface fields are read here
once a plan (plan() calls `note(state)`) from the report's farm plots, and
masterplan.hint reads `current()` for the band just under them.

    fields.note(state)      -> the surface fields of this report (kept until the next plan)
    fields.current()        -> {"n", "elevation", "x", "y", "z"} or None
    fields.set_fields(info) -> (tests) set them by hand; None clears
    fields.toward(spine, f) -> the direction from the spine to the fields, or None

No game access, no planner imports (masterplan imports this module).
"""
from __future__ import annotations

from collections import Counter

# (0.105.47) the levels under the surface fields a field hall or kitchen may
# take: the one just under them first, then the next
SURFACE_DEPTH = 2
SURFACE_FIRST = 50      # Surface this high: under the surface fields before the deep farms
NEAR_SPINE = 2          # fields this near the spine (across) give no direction

_FIELDS: dict | None = None
_ON = True              # (planner_config garden_fort) off: no surface fields, no gardens in the soil


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def read(state: dict | None) -> dict | None:
    """The surface fields in a report: the plots under the sky (farms.plot_list
    with underground false), on their most common elevation (a tie: the
    higher), their centre there; None with none. A report with only the
    count (plots_surface, no list) gives {"n"} alone."""
    farms = (state or {}).get("farms") if isinstance(state, dict) else None
    if not isinstance(farms, dict):
        return None
    off = _int(((state or {}).get("map") or {}).get("elevation_offset")) if isinstance(
        (state or {}).get("map"), dict) else None
    plots = [p for p in (farms.get("plot_list") or []) if isinstance(p, dict) and p.get("underground") is False
             and _int(p.get("x")) is not None and _int(p.get("y")) is not None and _int(p.get("elevation")) is not None]
    if not plots:
        n = _int(farms.get("plots_surface")) or 0
        return {"n": n} if n > 0 else None
    by = Counter(p["elevation"] for p in plots)
    top = max(by.values())
    e = max(k for k, v in by.items() if v == top)
    at = [p for p in plots if p["elevation"] == e]
    x = round(sum(p["x"] for p in at) / len(at))
    y = round(sum(p["y"] for p in at) / len(at))
    out = {"n": max(len(plots), _int(farms.get("plots_surface")) or 0), "elevation": e, "x": x, "y": y}
    if off is not None:
        out["z"] = e - off
    return out


def note(state: dict | None, on: bool = True) -> dict | None:
    """Keep this report's surface fields for masterplan.hint (one plan).
    on False (planner_config garden_fort off): none, and enabled() False."""
    global _FIELDS, _ON
    _ON = on is not False
    _FIELDS = read(state) if _ON else None
    return _FIELDS


def enabled() -> bool:
    return _ON


def set_fields(info: dict | None, on: bool = True) -> None:
    global _FIELDS, _ON
    _FIELDS = dict(info) if isinstance(info, dict) else None
    _ON = on is not False


def current() -> dict | None:
    return dict(_FIELDS) if isinstance(_FIELDS, dict) and (_FIELDS.get("n") or 0) > 0 else None


def toward(spine: dict | None, f: dict | None) -> str | None:
    """north/east/south/west from the spine to the fields' centre (None: no
    position known, or the fields lie round the spine)."""
    if not (isinstance(spine, dict) and isinstance(f, dict)):
        return None
    sx, sy, fx, fy = _int(spine.get("x")), _int(spine.get("y")), _int(f.get("x")), _int(f.get("y"))
    if None in (sx, sy, fx, fy):
        return None
    dx, dy = fx - sx, fy - sy
    if max(abs(dx), abs(dy)) <= NEAR_SPINE:
        return None
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "south" if dy >= 0 else "north"
