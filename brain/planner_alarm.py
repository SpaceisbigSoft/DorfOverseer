"""(item4) The civilian alarm kept from flapping.

One run (13 Nov) raised the alarm 153 times in C, 121 in F, 41 in B: a fire
9-14 tiles from a dwarf (122 of C's), a forgotten beast in the caverns while
a fisherdwarf was down there (110 of F's), an evil cloud on the surface, DF's
record of an intruder nobody had seen. Each was lifted three cycles later
("no threat has been able to reach the dwarves for 3 cycles and 3+ days":
the rule that lowers it counts enemies only, and fire or a beast far below
is none) and raised again minutes later. Every raise sent everyone into the
shelter, stopped the work and drew the shelter burrow again.

The governor runs once after every alarm rule (plan()), on the proposals:

  * a minimum time on: an alarm the AI raised stays up `alarm_min_on_ticks`
    (half a game day) before any of the AI's own rules may lower it;
  * a cooldown for the same cause: after the AI lowered an alarm raised for
    fire, a gas cloud, a cavern beast (each beast its own), an unseen
    intruder or evil weather, that cause doesn't raise it again for
    `alarm_cause_cooldown_ticks` (two game days);
  * a cap a game month: those causes raise it `alarm_month_cap` times a game
    month at most (counted when the alarm actually went up);
  * never for a real danger: enemies that can reach the dwarves (a siege),
    the walking dead, a necromancer siege, a berserk dwarf, a great beast on
    the surface, spilt magma, anything it doesn't know: always raised,
    whatever the counts (they are still counted). Nothing waits for the
    player: what is held back is said in the notes, and the danger's own
    answers (the fire guard, the cavern seal, the gates, the squads) go on.

(0.105.47) Caution sets the cooldown, the cap and which causes count (an
unseen lone intruder sounds nothing below `alarm_intruder_caution`), and how
near fire and clouds sound it: brain/alarm_caution.py. At Caution 0 the
numbers above are as they were.

Evil weather keeps the civilians in without the alarm (planner_weather: the
`weather_burrow` action); fire sounds it only this close (`fire_alarm_near`)
and is held while within `hazard_near` (planner_military.hazard_alert).
"""

from __future__ import annotations

from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick

__all__ = ["ALARM_CONFIG", "alarm_cause", "govern_alarm", "note_alarm_change", "GOVERNED", "REACH_CAP_WHY",
           "reach_near", "reach_alarm_over", "reach_raise_held"]

ALARM_CONFIG = {
    "alarm_min_on_ticks": TICKS_PER_DAY // 2,       # an AI alarm stays up this long before the AI lowers it
    "alarm_cause_cooldown_ticks": 2 * TICKS_PER_DAY,  # the same cause doesn't raise it again this soon after
    "alarm_month_cap": 4,                           # governed raises a game month at most
    "fire_alarm_near": 8,                           # fire this close (tiles; levels count 3) sounds the alarm
}
PLANNER_CONFIG.update({k: v for k, v in ALARM_CONFIG.items() if k not in PLANNER_CONFIG})

TICKS_PER_MONTH = 28 * TICKS_PER_DAY
GOVERNED = ("fire", "cloud", "cavern", "intruder", "weather")
ON = {"type": "civ_alert", "on": True}
OFF = {"type": "civ_alert", "on": False}


def _c(cfg: dict, k: str):
    return cfg.get(k, PLANNER_CONFIG[k])


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def alarm_cause(reason: str) -> tuple[str, str]:
    """(cause, key) of an alarm raise from its reason. The key is what the
    cooldown is kept by: each cavern beast its own."""
    r = str(reason or "")
    if "threat(s) can reach the dwarves" in r:
        return "reach", "reach"
    if r.startswith("DF reports"):
        return "intruder", "intruder"
    if r.startswith("fire ") and "tiles from the dwarves" in r:
        return "fire", "fire"
    if r.startswith("a cloud (gas or vapour)"):
        return "cloud", "cloud"
    if "citizen(s) are in the caverns" in r:
        who = r.split(" is about", 1)[0].strip()[:60]
        return "cavern", "cavern:" + who
    if "evil cloud" in r or "evil rain" in r or "blood rain" in r:
        return "weather", "weather"
    return "other", r[:40]


def _gov(memory) -> dict:
    g = getattr(memory, "alarm_gov", None)
    return g if isinstance(g, dict) else {}


def _month_count(g: dict, now: int) -> int:
    m = g.get("month")
    if isinstance(m, dict) and m.get("m") == now // TICKS_PER_MONTH and _int(m.get("n")):
        return m["n"]
    return 0


def govern_alarm(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Hold back an AI lowering inside the minimum time on, and a raise for a
    governed cause inside its cooldown or past the month's cap (in place)."""
    if memory is None:
        return
    now = abs_tick(s)
    if not _int(now):
        return
    g = _gov(memory)
    on = g.get("on") if isinstance(g.get("on"), dict) else {}
    alert_on = s.get("civ_alert") is True
    # 1. the minimum time on
    offs = [p for p in proposals if p.action == OFF]
    if offs and alert_on and getattr(memory, "ai_alert_raised", False) and _int(on.get("tick")):
        age = now - on["tick"]
        least = _c(cfg, "alarm_min_on_ticks")
        if 0 <= age < least:
            proposals[:] = [p for p in proposals if p not in offs]
            notes.append(f"the alarm stays up a while yet: raised {age // 50} game hour(s) ago "
                         f"({str(on.get('why') or on.get('cause') or '')[:80]}), held {least // 50} at least "
                         f"(it would have come down: {offs[0].reason[:80]})")
    # 2. raises for a governed cause: the cooldown and the month's cap
    ons = [p for p in proposals if p.action == ON]
    if not ons or alert_on:
        return
    # (0.105.47) Caution sets the cooldown, the month's cap and which causes count (brain/alarm_caution.py)
    from alarm_caution import alarm_settings
    st = s.get("settings") if isinstance(s.get("settings"), dict) else {}
    lean = alarm_settings(st.get("traits") if isinstance(st.get("traits"), dict) else {}, cfg)
    keep, dropped = [], []
    for p in ons:
        cause, key = alarm_cause(p.reason)
        if cause not in GOVERNED:
            keep.append(p)
            continue
        if cause == "intruder" and not lean["intruder"] and str(p.reason).startswith("DF reports an intruder"):
            dropped.append((p, f"a bold fort (Caution {lean['caution']:+d}) waits until a lone intruder is seen "
                               "(the alarm sounds then, as for every enemy in reach)"))
            continue
        last = (g.get("off") or {}).get(key) if isinstance(g.get("off"), dict) else None
        cool = lean["cooldown_ticks"]
        if _int(last) and 0 <= now - last < cool:
            dropped.append((p, f"it was lowered {(now - last) // 50} game hour(s) ago for the same cause; "
                               f"not raised again for it within {cool // 50}"))
            continue
        cap = lean["month_cap"]
        n = _month_count(g, now)
        if n >= cap:
            dropped.append((p, f"raised {n} time(s) this game month already for fire, clouds, cavern beasts, "
                               f"unseen intruders or weather (at most {cap})"))
            continue
        keep.append(p)
    if not dropped:
        return
    proposals[:] = [p for p in proposals if p.action != ON or p in keep]
    if not keep:
        p, why = dropped[0]
        notes.append(f"no alarm for {p.reason.split(':')[0][:120]}: {why}; the danger's own answer goes on "
                     "(fire guarded, the caverns locked, the gates and squads as ever) and enemies that can "
                     "reach the dwarves still sound it")


# --- (0.105.48, K1) the "can reach" alarm's maximum time -------------------------------
# War-hold (audit A6, finding 3): a falcon in reach kept the alarm up 30 game
# days; with 1-2 ordinary enemies the alarm comes down after half a day
# (few_ordinary), with anything else only when nothing reaches. Now any AI
# alarm with enemies in reach comes down after `reach_alarm_max_days` when
# none of them is near a dwarf or inside the fort; it is not raised again for
# the same enemies until one comes near or a new one comes.
REACH_CAP_WHY = "the alarm has been up"


def reach_near(s: dict, cfg: dict, ids) -> list:
    """The names of these enemies that are near a dwarf
    (`reach_alarm_near_tiles`; `reach_alarm_near_tiles_fast` for a great
    danger or a flier) or inside the fort. A stand-in id (unlisted) is never near."""
    want = set(ids)
    inside = {x for x in (s.get("entrances") or {}).get("intruders_inside") or [] if _int(x)} \
        if isinstance(s.get("entrances"), dict) else set()
    o = s.get("others_on_map") if isinstance(s.get("others_on_map"), dict) else {}
    out = []
    for t in o.get("threats") or []:
        if not isinstance(t, dict) or t.get("id") not in want:
            continue
        lim = _c(cfg, "reach_alarm_near_tiles_fast" if (t.get("great_danger") or t.get("flier"))
                 else "reach_alarm_near_tiles")
        d = t.get("distance_to_nearest_dwarf")
        if t.get("id") in inside or (isinstance(d, (int, float)) and not isinstance(d, bool) and d <= lim):
            out.append(str(t.get("name") or "an enemy"))
    return out


def reach_alarm_over(s: dict, memory, cfg: dict, ids) -> str:
    """Why the AI's alarm comes down for its maximum time ("" if not): up
    `reach_alarm_max_days` or more, enemies in reach, none near."""
    if memory is None or not ids or s.get("civ_alert") is not True or not getattr(memory, "ai_alert_raised", False):
        return ""
    now, on = abs_tick(s), _gov(memory).get("on")
    if not _int(now) or not isinstance(on, dict) or not _int(on.get("tick")):
        return ""
    days = (now - on["tick"]) // TICKS_PER_DAY
    if days < _c(cfg, "reach_alarm_max_days") or reach_near(s, cfg, ids):
        return ""
    return (f"{REACH_CAP_WHY} {days} days and none of the {len(ids)} enemy/enemies that can reach the dwarves "
            f"has come within {_c(cfg, 'reach_alarm_near_tiles')} tiles of one or into the fort: it comes down "
            "(the gates still close when one comes near; it sounds again for one that comes near or a new one)")


def reach_raise_held(s: dict, memory, cfg: dict, ids) -> str:
    """Why the alarm isn't raised again for enemies in reach ("" if it may
    be): the AI lowered it for its maximum time, no new enemy came since, and
    none of them is near."""
    if memory is None or not ids:
        return ""
    capped = _gov(memory).get("reach_capped")
    if not _int(capped):
        return ""
    from planner_gates import _lockdown
    new = _lockdown(memory).get("new")
    if not _int(new) or new > capped or reach_near(s, cfg, ids):
        return ""
    return (f"{len(ids)} threat(s) can reach the dwarves, none near them and none new since the alarm came down "
            f"for its maximum time: it stays down (it sounds for one within {_c(cfg, 'reach_alarm_near_tiles')} "
            "tiles of a dwarf, inside the fort, or a new one)")


def note_alarm_change(memory, now, on: bool, reason: str) -> None:
    """record(): the AI's alarm went up or came down (the game said so)."""
    if memory is None or not _int(now):
        return
    g = dict(_gov(memory))
    if on:
        cause, key = alarm_cause(reason)
        g["on"] = {"tick": now, "cause": cause, "key": key, "why": str(reason or "")[:100]}
        if cause in GOVERNED:
            g["month"] = {"m": now // TICKS_PER_MONTH, "n": _month_count(g, now) + 1}
    else:
        on_ = g.get("on") if isinstance(g.get("on"), dict) else {}
        off = dict(g.get("off") or {}) if isinstance(g.get("off"), dict) else {}
        if on_.get("key"):
            off[on_["key"]] = now
        # the oldest forgotten (a cooldown is two days; the keys stay few)
        off = {k: v for k, v in off.items() if _int(v) and 0 <= now - v < 28 * TICKS_PER_DAY}
        g["off"] = dict(sorted(off.items(), key=lambda kv: kv[1])[-20:])
        g["on"] = {}
        if str(reason or "").startswith(REACH_CAP_WHY):
            g["reach_capped"] = now             # (0.105.48, K1) reach_raise_held
    if on:
        g.pop("reach_capped", None)
    memory.alarm_gov = g
