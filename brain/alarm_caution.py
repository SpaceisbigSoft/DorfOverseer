"""(0.105.47) Alarms by Caution: the alarm's thresholds set by the slider.

The 14 Nov scorecard ran the alarms line backwards: the Merchant city
(Caution 0) raised 167, the Garden fort 130, the War-hold and the Hermit hold
(Caution 60) 34 and 20. The alarm's thresholds were the same for every fort,
so the count followed what happened near each (C's fire, F's cavern beasts),
not how careful a fort meant to be. 0.105.44's governor (planner_alarm)
since holds the flapping; here Caution sets its numbers and the distances,
so a careful fort raises earlier and more, a bold one later and fewer:

  * how near: fire sounds it within `fire_alarm_near` + Caution/20 tiles
    (4 to hazard_near), a gas cloud within hazard_near + Caution/10 (10-30);
    the walking dead, an evil cloud on the surface and a great beast near
    those out there farther with Caution above 0 (never nearer below it:
    real dangers);
  * which causes: below `alarm_intruder_caution` DF's record of a lone
    intruder nobody has seen sounds nothing (the alarm comes when one is
    seen, as every enemy in reach does); from `cautious_alert_caution`
    threats whose reach DF can't tell, near the dwarves, count as in reach
    (planner_core.reachable_threats, `cautious_alert_levels` scaled);
  * cooldowns: the same governed cause waits `alarm_cause_cooldown_ticks`
    x (1 - Caution/120) (half a day to 4 days) after a lowering, and the
    month's cap is `alarm_month_cap` + Caution/20 (1 to 10).

Enemies that can reach the dwarves, the walking dead near them, a berserk
dwarf, spilt magma and a great beast on the surface always sound it, as
before: Caution only moves when the governed causes do.
"""

from __future__ import annotations

from planner_core import PLANNER_CONFIG, TICKS_PER_DAY

__all__ = ["CAUTION_ALARM_CONFIG", "caution", "alarm_settings", "near_for", "cautious_levels"]

CAUTION_ALARM_CONFIG = {
    "alarms_by_caution": True,         # (0.105.47) off: the alarm's numbers as before 0.105.47 (tests compare main's plan)
    "alarm_intruder_caution": -30,     # (0.105.47) below this Caution an unseen lone intruder sounds nothing
    "cautious_alert_caution": 50,      # ...from this Caution unknown-reach threats near the dwarves count as in reach
}
PLANNER_CONFIG.update({k: v for k, v in CAUTION_ALARM_CONFIG.items() if k not in PLANNER_CONFIG})


# (r6 c2) kept local: unlike util's helpers (None falls back, `default`)
def _c(cfg: dict, k: str, default=None):
    v = (cfg or {}).get(k)
    if v is None:
        v = PLANNER_CONFIG.get(k, default)
    return v


from util import clamp as _clamp  # noqa: E402  (r6 c2) was a copy here


def caution(traits) -> float:
    try:
        return float(_clamp(float((traits or {}).get("caution", 0) or 0), -200, 200))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _traits_of(s) -> dict:
    st = s.get("settings") if isinstance(s, dict) else None
    t = st.get("traits") if isinstance(st, dict) else None
    return t if isinstance(t, dict) else {}


def alarm_settings(traits, cfg: dict | None = None) -> dict:
    """The alarm's numbers at this Caution (at 0 they are the config's own)."""
    c = caution(traits) if _c(cfg, "alarms_by_caution", True) else 0.0
    hazard = int(_c(cfg, "hazard_near", 20))
    fire = int(_clamp(round(int(_c(cfg, "fire_alarm_near", 8)) + c / 20), 4, hazard))
    cloud = int(_clamp(round(hazard + c / 10), 10, 30))
    cool = int(_c(cfg, "alarm_cause_cooldown_ticks", 2 * TICKS_PER_DAY))
    cool = int(_clamp(round(cool * (1 - c / 120)), TICKS_PER_DAY // 2, 4 * TICKS_PER_DAY))
    cap = int(_clamp(round(int(_c(cfg, "alarm_month_cap", 4)) + c / 20), 1, 10))
    return {"caution": int(c), "fire_near": fire, "cloud_near": cloud,
            "fire_hold": max(hazard, fire), "cloud_hold": max(hazard, cloud),
            "cooldown_ticks": cool, "month_cap": cap,
            "intruder": c >= _c(cfg, "alarm_intruder_caution", -30)}


def near_for(s: dict, cfg: dict, key: str, default: int) -> int:
    """A real danger's distance (undead_near, evil_cloud_near,
    surface_danger_near) at the fort's Caution: farther above 0 (x1.5 at
    +100), never nearer below 0."""
    base = _c(cfg, key, default)
    try:
        base = int(base)
    except (TypeError, ValueError):
        base = default
    c = caution(_traits_of(s)) if _c(cfg, "alarms_by_caution", True) else 0.0
    return int(round(base * (1 + max(0.0, c) / 200)))


def cautious_levels(traits, cfg: dict) -> int | None:
    """How many levels off an unknown-reach threat counts as in reach (None:
    not at this Caution). `cautious_alert_levels` at +100, fewer down to
    `cautious_alert_caution`."""
    c = caution(traits)
    if not _c(cfg, "alarms_by_caution", True):
        return int(_c(cfg, "cautious_alert_levels", 10)) if c >= 100 else None
    if c < _c(cfg, "cautious_alert_caution", 50):
        return None
    lv = int(_c(cfg, "cautious_alert_levels", 10))
    return max(1, int(round(lv * min(1.0, c / 100))))
