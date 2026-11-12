"""(0.105.41, phase 13e) Traffic zones on the AI's own levels, for the
dwarves' paths and the game's speed.

The `traffic` report (lua/ai-traffic.lua) reads only the project records:
the finished AI levels still waiting for their traffic (`pending`, the
first few; `pending_total`), the one being painted (`cursor`), how many are
painted and how many became the player's (`hands_off`), and the painted
level checked longest ago (`audit_next`, with its age in days).

  * traffic_paint: while a level waits (or one is half done), one slice a
    cycle: `paint_traffic` with traffic_slice_tiles tiles and
    traffic_budget_ms at most. High on the stairs, corridors and avenues the
    AI dug, the way in and the deep depot's road; Low on its bedrooms,
    suites, tombs, hospital and farm levels. Only tiles at Normal change.
    While the game runs slowly it comes a little sooner (the paths are part
    of the cost).
  * traffic_audit: a painted level rechecked once it is traffic_recheck_days
    old (one level a call): a level the player changed by hand is left to
    him from then on; the few tiles back at Normal (a fire guard lifted)
    are painted again.

The Rules switch `traffic` (on by default); no rule while a threat can
reach the dwarves or a siege is on, and nothing without a `traffic`
section (an older bridge). With brain/perf.py's 13e work: a slice is
bounded in tiles and ms (the call's own `ms` comes back with the result),
the report section reads no tile, and a slow game paints sooner.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, player_rules

__all__ = ["traffic_report", "_traffic_rule", "traffic_line"]


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def traffic_report(s: dict) -> dict | None:
    """The bridge's traffic section, or None (an older bridge, a failed one)."""
    t = s.get("traffic")
    if not isinstance(t, dict) or not t or "error" in t:
        return None
    if not isinstance(t.get("pending"), list):
        return None
    return t


def _danger_near(s: dict) -> bool:
    """A threat that can reach the dwarves, or a siege now: the bridge's time
    goes to the safety rules (a great beast deep in a cavern or the
    underworld, there for years, doesn't hold the paint)."""
    o = _d(s.get("others_on_map"))
    n = o.get("threats_that_can_reach_dwarves")
    if isinstance(n, int) and n > 0:
        return True
    if any(isinstance(t, dict) and t.get("can_reach_dwarves") is True for t in _l(o.get("threats"))):
        return True
    return any(isinstance(e, dict) and e.get("active") for e in _l(_d(s.get("world")).get("sieges")))


def _traffic_rule(s: dict, cfg: dict, proposals: list, rules: dict | None = None) -> None:
    """(0.105.41) Paint a finished level's traffic a slice a cycle; recheck
    an old one now and then (see the module)."""
    t = traffic_report(s)
    if t is None or t.get("enabled") is False:
        return
    rules = rules or player_rules(s)
    if rules.get("traffic") is False:
        return
    if s.get("halted") is True or _danger_near(s):
        return
    slow = bool(s.get("fps_low"))
    base = {"max": int(cfg["traffic_slice_tiles"]), "budget_ms": int(cfg["traffic_budget_ms"])}
    cur = _d(t.get("cursor"))
    pending = [p for p in _l(t.get("pending")) if isinstance(p, dict) and isinstance(p.get("key"), str)]
    if cur.get("key") or pending:
        what = cur.get("key") or pending[0]["key"]
        kind = next((p.get("kind") for p in pending if p.get("key") == what), None)
        n = max(_int(t.get("pending_total")), len(pending))
        proposals.append(Proposal(
            "traffic_paint", {"type": "paint_traffic", **base},
            f"traffic on the AI's finished {kind or 'level'}"
            + (f" (and {n - 1} more waiting)" if n > 1 else "")
            + ": high on its stairs and corridors, low on rooms and fields, so paths keep to the main ways",
            cfg["traffic_priority_slow"] if slow else cfg["traffic_priority"]))
        return
    a = _d(t.get("audit_next"))
    if isinstance(a.get("key"), str) and _int(a.get("days")) >= cfg["traffic_recheck_days"]:
        proposals.append(Proposal(
            "traffic_audit", {"type": "paint_traffic", "key": a["key"], "audit": True, **base},
            f"recheck the traffic on the AI's {a.get('kind') or 'level'} ({_int(a.get('days'))} days since): "
            "left to you if you changed it, else the lost tiles painted again",
            cfg["traffic_priority"]))


def traffic_line(s: dict) -> str:
    """TRAFFIC painted N | waiting N | yours N; "" without a section."""
    t = traffic_report(s)
    if t is None:
        return ""
    return (f"TRAFFIC painted {_int(t.get('painted'))} levels ({_int(t.get('tiles'))} tiles)"
            f" | waiting {_int(t.get('pending_total'))}"
            + (" (one in progress)" if _d(t.get("cursor")).get("key") else "")
            + (f" | yours {_int(t.get('hands_off'))}" if _int(t.get("hands_off")) else "")
            + (" | off" if t.get("enabled") is False else ""))
