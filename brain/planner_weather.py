"""(0.105.40b) Evil weather: the fort's surface workers kept out of it.

An evil region's weather turns dwarves caught in it into thralls, husks or
worse: creeping clouds (gas, vapour, dust) that drift across the map, rain
of a syndrome material, rain of blood. Before this the AI sounded the alarm
only for a trailing cloud already near a dwarf out on the surface
(planner_threats.threat_alert), by which time the woodcutter was in it.

The bridge's `threats.weather` (lua/ai-threats.lua weather_report) says:
evil clouds on the map's surface (a flow with a guide, or any cloud whose
material carries a syndrome; `evil_cloud` tiles, `syndrome`, `effects`), DF's
own list of evil weather (`region`: a creeping cloud this close to the map's
edge and whether it drifts this way, DF's `announced` flag), evil or blood
rain on the fort's tile (`rain`), and while any of it is about the hostile
units standing out under the sky (`enemies_outside`).

The rule (_weather_rules):
  * an evil cloud on the map's surface, one of DF's clouds at or drifting
    toward the map's edge within `weather_edge_near` tiles, or evil rain (a
    syndrome) on the fort: the civilian alarm (the existing civ_alert action:
    citizens into the shelter burrow, so the gathering, wood cutting and
    hauling outside stop), or the AI's own shelter when there is no burrow;
    nothing else lowers it meanwhile (alarm_held holds the strategist's);
  * plain blood rain only stains: said, work goes on (Rules config
    `weather_blood_rain_alarm` to sound it);
  * lifted `weather_lift_hours` game hours after the weather has gone, by the
    AI only when the AI raised it for the weather and nothing else holds it;
  * held `weather_alarm_max_days` at most in one spell (said, then let be);
  * the player lowering it during the spell is obeyed: not sounded again
    until a new spell;
  * squads are not sent out at enemies standing in it (_weather_squad_filter),
    unless enemies are inside the fort (then the squads do what they must).
The gates are never touched here. Without a `threats.weather` section (an
older bridge, a fixture) nothing here proposes, notes or remembers anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, Proposal, TICKS_PER_DAY, abs_tick, reachable_threats, _traits

__all__ = ["weather_of", "weather_danger", "weather_held", "_weather_rules", "_weather_squad_filter", "weather_line"]

TICKS_PER_HOUR = 50


def _c(cfg: dict, k: str):
    return cfg.get(k, PLANNER_CONFIG[k])


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def weather_of(s: dict) -> dict:
    """The bridge's threats.weather ({} when absent or failed)."""
    w = _d(_d(s.get("threats")).get("weather"))
    return {} if w.get("error") else w


def _syn(x) -> str:
    return f" ({str(x)[:60]})" if x else ""


def weather_danger(s: dict, cfg: dict) -> str:
    """Why evil weather should keep the dwarves in this cycle ("" if none)."""
    w = weather_of(s)
    if not w:
        return ""
    n = w.get("evil_cloud")
    if _num(n) and n > 0:
        mat = w.get("material")
        return (f"an evil cloud{' of ' + str(mat)[:60] if mat else ''} on the map's surface ({int(n)} tiles of it)"
                f"{_syn(w.get('syndrome'))}")
    reg = _d(w.get("region"))
    edge = reg.get("cloud_edge")
    if _num(edge) and edge <= _c(cfg, "weather_edge_near") and (edge <= 0 or reg.get("approaching")):
        mat = reg.get("cloud_material")
        where = "over the map" if edge <= 0 else f"{int(edge)} tiles from the map's edge, drifting this way"
        return (f"DF's evil cloud{' of ' + str(mat)[:60] if mat else ''} {where}"
                f"{' (announced)' if reg.get('announced') else ''}{_syn(reg.get('cloud_syndrome'))}")
    rain = w.get("rain")
    mat = w.get("rain_material")
    if rain == "evil":
        return f"evil rain{' of ' + str(mat)[:60] if mat else ''} falling on the fort{_syn(w.get('rain_syndrome'))}"
    if rain == "blood" and _c(cfg, "weather_blood_rain_alarm"):
        return f"blood rain{' of ' + str(mat)[:60] if mat else ''} falling on the fort"
    return ""


def _spell(memory) -> dict:
    wa = getattr(memory, "weather_alarm", None) if memory is not None else None
    return dict(wa) if isinstance(wa, dict) else {}


def weather_held(s: dict, memory, cfg: dict) -> str:
    """Why the evil weather's spell holds the alarm now ("" if not): seen
    within `weather_lift_hours`, not past its cap, not lowered by the player.
    Reads memory only (alarm_held asks it)."""
    wa = _spell(memory)
    seen, since, now = wa.get("seen"), wa.get("since"), abs_tick(s)
    if not (isinstance(seen, int) and isinstance(now, int)) or wa.get("cleared") or wa.get("capped"):
        return ""
    if not 0 <= now - seen < _c(cfg, "weather_lift_hours") * TICKS_PER_HOUR and seen != now:
        return ""
    if isinstance(since, int) and (now - since) // TICKS_PER_DAY >= _c(cfg, "weather_alarm_max_days"):
        return ""
    return str(wa.get("why") or "evil weather")[:160]


def _weather_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """The alarm for evil weather, held while it lasts and `weather_lift_hours`
    after; lifted by the AI when it raised it for the weather."""
    w = weather_of(s)
    if not w or memory is None:
        return
    now = abs_tick(s)
    if not isinstance(now, int):
        return
    why = weather_danger(s, cfg)
    wa = _spell(memory)
    lift = _c(cfg, "weather_lift_hours")
    alert_on = bool(s.get("civ_alert"))
    if not why and w.get("rain") == "blood":
        notes.append(f"blood rain{' of ' + str(w.get('rain_material'))[:60] if w.get('rain_material') else ''} "
                     "falls on the fort: it only stains (no syndrome), so surface work goes on")
    if why:
        if not isinstance(wa.get("since"), int) or wa["since"] > now:
            wa = {"since": now}
        wa["seen"], wa["why"] = now, why[:160]
    elif isinstance(wa.get("seen"), int):
        gone = now - wa["seen"]
        if gone < 0 or gone >= lift * TICKS_PER_HOUR:
            memory.weather_alarm = {}
            from planner_threats import alarm_held, unseen_intrusion
            ours = wa.get("was_off") and wa.get("on_seen") and not wa.get("cleared")
            if (ours and alert_on and getattr(memory, "ai_alert_raised", False)
                    and not alarm_held(s, memory, cfg) and not unseen_intrusion(s, memory, cfg)
                    and not any(p.action == {"type": "civ_alert", "on": False} for p in proposals)
                    and not any(p.action == {"type": "civ_alert", "on": True} for p in proposals)):
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                          f"the evil weather ({wa.get('why') or 'cloud or rain'}) has been gone "
                                          f"{max(0, gone) // TICKS_PER_HOUR} game hour(s): the alarm comes down and "
                                          "the dwarves go back to work outside", 0))
            return
        why = f"{wa.get('why') or 'evil weather'}, gone {gone // TICKS_PER_HOUR} game hour(s) ago (held {lift} after)"
    else:
        memory.weather_alarm = {}
        return
    days = (now - wa["since"]) // TICKS_PER_DAY
    if days >= _c(cfg, "weather_alarm_max_days"):
        if not wa.get("capped"):
            notes.append(f"{why}: the alarm has been held {days} days for it; the AI no longer holds it (the fort "
                         "can't stay indoors for ever); the weather is still watched")
        wa["capped"] = True
        memory.weather_alarm = wa
        return
    if alert_on:
        wa["on_seen"] = True
    elif wa.get("on_seen") and not wa.get("cleared"):
        wa["cleared"] = True
        notes.append(f"{why}: the alarm was lowered during it; the AI leaves it down for this spell "
                     "(new evil weather sounds it again)")
    else:
        wa["was_off"] = True
    memory.weather_alarm = wa
    if wa.get("cleared"):
        return
    held = [p for p in proposals if p.action == {"type": "civ_alert", "on": False}]
    if held:
        proposals[:] = [p for p in proposals if p not in held]
    if alert_on:
        notes.append(f"the alarm stays up for {why}: the citizens stay in the shelter, no work outside")
    elif weather_danger(s, cfg):
        if not any(p.action == {"type": "civ_alert", "on": True} for p in proposals):
            if s.get("civ_alert_ready") is True:
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                          f"{why}: sound the alarm (everyone inside, the gathering, wood cutting "
                                          "and hauling outside stop until it has gone)", 0))
            else:
                from planner_military import no_shelter
                no_shelter(s, memory, f"evil weather: {why}", proposals, notes)


def _weather_squad_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """No squad sent out at enemies standing under evil weather, unless
    enemies are inside the fort (then the squads do what they must)."""
    w = weather_of(s)
    if not w or not weather_danger(s, cfg):
        return proposals
    outside = {i for i in _l(w.get("enemies_outside")) if isinstance(i, int) and not isinstance(i, bool)}
    if not outside:
        return proposals
    try:
        reach = reachable_threats(s, _traits(s), cfg) if isinstance(s.get("others_on_map"), dict) else []
    except Exception:  # noqa: BLE001  (an odd report: the squads are left as they are)
        return proposals
    if any(i not in outside for i in reach):
        return proposals
    out, held = [], 0
    for p in proposals:
        a = p.action
        kill = a.get("kill") if a.get("type") == "squad_orders" else None
        if isinstance(kill, list) and kill:
            left = [i for i in kill if i not in outside]
            if not left:
                held += 1
                continue
            if len(left) < len(kill):
                p.action = dict(a, kill=left)
                held += 1
        out.append(p)
    if held:
        notes.append(f"{held} squad order(s) not sent out at enemies standing in the evil weather "
                     f"({weather_danger(s, cfg)[:80]}); the squads wait for them inside")
    return out


def weather_line(s: dict) -> str:
    """The digest's word on evil weather ("" when none)."""
    w = weather_of(s)
    if not w:
        return ""
    parts = []
    if _num(w.get("evil_cloud")) and w["evil_cloud"] > 0:
        parts.append(f"evil_cloud_tiles:{int(w['evil_cloud'])}")
    reg = _d(w.get("region"))
    if _num(reg.get("cloud_edge")):
        parts.append(f"evil_cloud_from_map_edge:{int(reg['cloud_edge'])}" + ("(approaching)" if reg.get("approaching") else ""))
    if w.get("rain") in ("evil", "blood"):
        parts.append(f"{w['rain']}_rain")
    if parts and w.get("syndrome"):
        parts.append(f"syndrome:{str(w['syndrome'])[:40]}")
    return " ".join(parts)
