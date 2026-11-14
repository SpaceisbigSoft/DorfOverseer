"""(0.105.47) Traps by Fortification: which gates get traps, and how many.

The 14 Nov scorecard ran the traps line backwards against its slider: the
War-hold (Fortification 120) had 16 traps, the Deep mine (Fortification 0)
20, the Merchant city 7. Every rule that sets traps put them behind EVERY
gated entrance, whatever the slider (planner_gates._trap_rule, the thieves'
cage traps in planner_threats), so the count followed how many ways in a fort
had, not how fortified it meant to be: the Deep mine's many cavern openings
each got doors (the safety rules: they stay) and then traps behind them.

Now Fortification picks the gates (the doors and walls that close an
entrance are the safety rules' and stay whatever the slider):

  * Fortification `trap_every_fortification`+ (or a closed fort, Outsiders
    `killzone_closed_outsiders` or lower: the Hermit hold): traps behind
    every gate, surface and cavern;
  * from `trap_surface_fortification`: the surface gates, and any gate
    enemies came through (the atlas' per-entrance record: threats seen at
    it, deaths by it);
  * below: only the gates enemies came through (minimal).

How many a gate is defence.trap_count (Fortification weighs most).

Kill zones (planner_killzone) follow the same slider: every entrance at
Fortification `killzone_all_slider`+ or in a closed fort (Caution no longer
counts for "every"), `killzone_traps_high` traps a zone there; below
`trap_surface_fortification` a way needs `killzone_used_min_low` threats (or
a death) before its zone, with `killzone_traps_low` traps. A siege's gate and
a great beast's cavern stay as they were (dangers, not leanings).
"""

from __future__ import annotations

from digest import _d
from planner_core import PLANNER_CONFIG

__all__ = ["TRAPLEAN_CONFIG", "fortification", "trap_tier", "gate_used", "trap_gate_why"]

TRAPLEAN_CONFIG = {
    "traps_by_fortification": True,     # (0.105.47) off: every gate as before 0.105.47 (tests compare main's plan)
    "trap_every_fortification": 50,     # (0.105.47) traps behind every gate from this Fortification
    "trap_surface_fortification": -30,  # ...the surface gates and the used ones from this; below, the used ones only
    "trap_used_min": 1,                 # threats seen at a gate (the atlas' record) before it counts as used
    "killzone_used_min_low": 3,         # below trap_surface_fortification: threats at a way before its kill zone
    "killzone_traps_low": 3,            # ...and the traps a zone there
}
PLANNER_CONFIG.update({k: v for k, v in TRAPLEAN_CONFIG.items() if k not in PLANNER_CONFIG})


def _c(cfg: dict, k: str):
    return (cfg or {}).get(k, PLANNER_CONFIG[k])


def _num(traits: dict, k: str) -> float:
    try:
        return float((traits or {}).get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def fortification(traits: dict) -> float:
    return _num(traits, "fortification")


def trap_tier(traits: dict, cfg: dict | None = None) -> str:
    """'every', 'surface' or 'used': which gates this fort sets traps behind."""
    if not _c(cfg, "traps_by_fortification"):
        return "every"
    closed = _num(traits, "outsiders") <= _c(cfg, "killzone_closed_outsiders")
    f = fortification(traits)
    if f >= _c(cfg, "trap_every_fortification") or closed:
        return "every"
    if f >= _c(cfg, "trap_surface_fortification"):
        return "surface"
    return "used"


def gate_used(memory, e: dict, cfg: dict | None = None) -> tuple[int, int]:
    """(threats seen, deaths) at this entrance in the atlas' record; (0, 0) when none."""
    if not all(isinstance(e.get(k), int) for k in ("x", "y", "z")):
        return 0, 0
    from planner_killzone import entrance_records
    rec = entrance_records(memory, e) if memory is not None else {}
    try:
        return int(_d(rec).get("threats") or 0), int(_d(rec).get("deaths") or 0)
    except (TypeError, ValueError):
        return 0, 0


def trap_gate_why(e: dict, traits: dict, memory, cfg: dict | None = None) -> str:
    """Why this gate gets traps at the fort's Fortification ("" = not at
    this Fortification: the gate itself still stands)."""
    tier = trap_tier(traits, cfg)
    f = int(fortification(traits))
    if tier == "every":
        return f"Fortification {f:+d}: traps behind every gate"
    seen, deaths = gate_used(memory, e, cfg)
    if seen >= _c(cfg, "trap_used_min") or deaths:
        return f"enemies came this way {seen} time(s)" + (f", {deaths} died by it" if deaths else "")
    if tier == "surface" and e.get("kind") != "cavern":
        return f"Fortification {f:+d}: traps behind the surface gates"
    return ""
