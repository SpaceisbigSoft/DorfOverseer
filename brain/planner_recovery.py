"""(0.105.46, I4) Collapse recovery: a fort that has fallen goes into
survival mode until it is back on its feet.

Why (the run of 14 Nov): B fell from 100 to 1 (thirst) and came back to 28,
E from 58 to 23, F from 100 to 46 (a titan in the shelter); D (the Hermit
hold, Outsiders -150) sat at 15 dwarves for ten years, then 8: DF sent it
no migrants. Each fallen fort went on opening libraries, statues, hunts and
kill zones with a handful of dwarves.

The state (memory.recovery, kept by note_recovery before each plan):

  * enters when the citizens are under the floor, max(`recovery_floor_min`,
    `recovery_floor_peak_share` of the most the fort ever had), and the fort
    was once over it (a new fort of 7 is not a fallen one); or when they
    fell by `recovery_drop_share` (a third) within a game year from a high
    of `recovery_drop_min` or more;
  * leaves when back at the floor or over it for `recovery_leave_days` (a
    season), and at least `recovery_min_days` after it began. The year's
    high starts again from there (the same fall is not counted twice).
    Never in Extreme-low Growth: that fort shrinks on purpose.

While in it (recovery_apply, after every rule in plan()): the survival
rules go on (water, wells, drink, food, farms, kitchens, beds and rooms,
the hospital and care, burial, the guard and its squads, the gates, the
threats' answers) and the rest waits: hunts, kill zones, lures, missions,
landmarks, the hall and wings above ground, siege works, gatehouses,
artifacts on show, polish, export orders, the crisis's expansion list, and
every new level that is not bedrooms, a dining hall, a hospital, a well,
farms, storage, workshops or tombs (urgent ones and a strange mood's
workshop always go). The crafts stay: DF sends migrants by the wealth the
fort created (reported by the outgoing dwarven caravan).

Closed forts still take migrants: the Outsiders slider shuts the fort to
visitors (petitions, locations, the citizenship of visitors) and trade,
never to migrants. Nothing the AI does for "closed" touches DF's
population cap; what held D at 15 was the cap held at the fort's size while
it was strained (planner_growth: the strain hold), with DF's own rules for
waves after the second (no wealth reported, no migrants). In recovery the
cap is opened (open_cap, called from _pop_cap_rule): at least the floor
and `recovery_cap_room` over the citizens (never past Maintain's own size,
never in Extreme-low Growth), the strict cap over it, the baby caps raised
as under the survival floor.

When DF still sends none (`recovery_migrants_wait_days` with no newcomer,
the cap open, no siege) the AI calls a wave itself with DFHack's `force
Migrants` (the `call_migrants` action, Rules `call_migrants`), once a
`recovery_migrants_cooldown_ticks` at most. A Needs you only when it can't:
the player's own cap (Rules set_pop_cap off) under the citizens, DFHack's
own `hermit` tool on, no force script, the switch off, or
`recovery_migrants_max_calls` calls that brought nobody.

The same call helps a fort stalled under the survival floor (D at 15 for
ten years): `recovery_stall_days` without a newcomer under
`survival_floor`, in recovery or not.

Reported in the notes, the digest (s["_recovery"], digest.recovery_line)
and the fort's journal (recovery_journal: entered, left, calls).
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, TICKS_PER_DAY, Proposal, abs_tick, ask_player, growth_mode,
                          growth_target, player_rules)

__all__ = ["SURVIVAL_KINDS", "HOLD_TYPES", "HOLD_RULES", "recovery_floor", "in_recovery", "note_recovery",
           "held_in_recovery", "recovery_apply", "open_cap", "_migrants_rule", "recovery_journal",
           "recovery_line", "stalled"]

TICKS_PER_WEEK = 7 * TICKS_PER_DAY
TICKS_PER_YEAR = 336 * TICKS_PER_DAY

# levels that keep a fallen fort alive (a growth hall or a set piece of
# these kinds still waits)
SURVIVAL_KINDS = {"bedrooms", "dining", "hospital", "well", "farms", "storage", "workshops", "tombs"}

# actions that wait while the fort recovers, whatever rule made them
HOLD_TYPES = {
    "hunt_send",                                        # hunts
    "build_killzone", "build_lure", "lure_open",        # kill zones, lures (lure_shut still goes)
    "send_mission",                                     # missions and Make contact
    "expel_dwarf",                                      # nobody sent away
    "polish", "polish_room",
    "blueprint_sites", "build_blueprint", "landmark_step",   # landmarks
    "place_hall", "build_wings", "floor_rooms", "place_keep",  # building above ground
    "place_siege_engine", "place_siege_shop", "build_gatehouse", "fortify_entrance", "cut_entrance",
    "display_artifact", "place_display",
    "keep_grove",
}

try:
    import crisis as _crisis
    _EXPANSION = set(_crisis.EXPANSION_RULES) - {"squad_make"}   # the guard's squads are kept
    _KEEP_RULES = set(_crisis.RECOVERY_RULES)
except Exception:  # noqa: BLE001
    _EXPANSION, _KEEP_RULES = set(), set()

# rules that wait (their other actions too: the parts and labours for them)
HOLD_RULES = _EXPANSION | {
    "hunt", "killzone", "killzone_parts", "lure_build", "lure_open", "lure_archer",
    "mission", "contact", "export", "paper", "paper_shop", "alloy",
    "artifact_display", "artifact_furniture", "artifact_pedestals",
    "hall", "wings", "soil_floor", "keep", "construct_blocks", "landmark_sites", "landmark_step",
    "siege_engine", "siege_shop", "siege_parts", "siege_ammo", "siege_operator", "wild_hunt", "caravan_guard",
    "gatehouse", "fortify", "traps", "gate_cut", "grove", "grove_guard", "leather_gear",
    "waterworks_moat", "waterworks_magma", "waterworks_power", "expel",
}


def _c(cfg: dict, k: str):
    return cfg[k] if k in cfg else PLANNER_CONFIG[k]


def _rec(memory) -> dict:
    r = getattr(memory, "recovery", None)
    if not isinstance(r, dict):
        r = {}
        try:
            memory.recovery = r
        except Exception:  # noqa: BLE001
            pass
    return r


def recovery_floor(cfg: dict, peak) -> int:
    """max(recovery_floor_min, recovery_floor_peak_share of the fort's peak)."""
    p = int(peak or 0)
    return max(int(_c(cfg, "recovery_floor_min")), int(math.ceil(p * float(_c(cfg, "recovery_floor_peak_share")))))


def in_recovery(memory) -> dict:
    """The recovery under way ({since, why, floor, ...}) or {}."""
    r = getattr(memory, "recovery", None) if memory is not None else None
    return r if isinstance(r, dict) and isinstance(r.get("since"), int) else {}


def _timeline_peak(memory) -> int:
    """The most dwarves the timeline ever saw (days, seasons, years): a fort
    that fell before this version knows its peak."""
    t = _d(getattr(memory, "timeline", None))
    best = 0
    try:
        fields = _l(t.get("fields")) or ["day", "pop"]
        i = fields.index("pop") if "pop" in fields else 1
        for r in _l(t.get("days")):
            if isinstance(r, list) and len(r) > i and isinstance(r[i], (int, float)):
                best = max(best, int(r[i]))
        for part in _l(t.get("seasons")) + _l(t.get("years")):
            v = _d(_d(part).get("high")).get("pop")
            if isinstance(v, (int, float)):
                best = max(best, int(v))
    except Exception:  # noqa: BLE001
        pass
    return best


def _journal(rec: dict, entry: dict) -> None:
    j = rec.get("journal")
    if not isinstance(j, list):
        j = []
    j.append(entry)
    rec["journal"] = j[-20:]


def stalled(s: dict, memory, cfg: dict) -> bool:
    """Under the survival floor with no newcomer for recovery_stall_days
    (D: 15 dwarves for ten years), and watched that long."""
    rec = _d(getattr(memory, "recovery", None))
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    floor = int(cfg.get("survival_floor") or 0)
    now = abs_tick(s)
    first, rise = rec.get("first"), rec.get("last_rise")
    wait = int(_c(cfg, "recovery_stall_days")) * TICKS_PER_DAY
    return (0 < pop < floor and isinstance(first, int) and now - first >= wait
            and (not isinstance(rise, int) or now - rise >= wait))


def note_recovery(s: dict, memory, cfg: dict, notes: list) -> dict:
    """Bookkeeping before planning (note_cycle): the weekly highs, the peak,
    the last newcomer, the calls made; entering and leaving. Puts a copy in
    s["_recovery"] for the digest. Returns the recovery under way or {}."""
    s.pop("_recovery", None)
    dw = _d(s.get("dwarves"))
    pop = dw.get("total")
    if not isinstance(pop, int) or isinstance(pop, bool) or pop <= 0:
        return in_recovery(memory)
    now = abs_tick(s)
    rec = _rec(memory)
    # an older save loaded: forget what lies in its future
    for k in ("since", "above_since", "base_from", "last_rise", "first", "call_seen"):
        if isinstance(rec.get(k), int) and rec[k] > now:
            rec.pop(k, None)
    if not isinstance(rec.get("first"), int):
        rec["first"] = now
    # weekly highs, a year of them (since the last recovery ended)
    wk = now // TICKS_PER_WEEK
    weeks = [w for w in _l(rec.get("weeks")) if isinstance(w, list) and len(w) == 2
             and isinstance(w[0], int) and isinstance(w[1], int) and 0 <= wk - w[0] < 49 and w[0] <= wk]
    if weeks and weeks[-1][0] == wk:
        weeks[-1][1] = max(weeks[-1][1], pop)
    else:
        weeks.append([wk, pop])
    base = rec.get("base_from")
    if isinstance(base, int):
        weeks = [w for w in weeks if w[0] * TICKS_PER_WEEK >= base - TICKS_PER_WEEK] or [[wk, pop]]
    rec["weeks"] = weeks[-49:]
    # the peak: the fort's own, or the timeline's for a fort that fell before
    peak = max(int(rec.get("peak") or 0), pop)
    if not rec.get("peak_seeded"):
        peak = max(peak, _timeline_peak(memory))
        rec["peak_seeded"] = True
    rec["peak"] = peak
    # newcomers (migrants, births): any rise over the last count
    last = rec.get("last_pop")
    if isinstance(last, int) and pop > last:
        rec["last_rise"] = now
    rec["last_pop"] = pop
    # calls for migrants the AI made (record() kept the tick)
    lf = _d(getattr(memory, "last_fired", None)).get("recovery_migrants")
    if isinstance(lf, int) and lf != rec.get("call_seen") and lf <= now:
        rec["call_seen"] = lf
        rec["calls"] = (_l(rec.get("calls")) + [lf])[-10:]
        _journal(rec, {"event": "migrants_called", "pop": pop, "tick": lf})
    floor = recovery_floor(cfg, peak)
    year_high = max(w[1] for w in rec["weeks"])
    mode, _n = growth_mode(s, cfg) if isinstance(s.get("settings"), dict) else ("target", None)
    held = isinstance(rec.get("since"), int)
    if mode == "shrink":
        if held:
            _leave(rec, now, pop, "Extreme-low Growth shrinks the fort on purpose", notes)
        return {}
    if not held:
        why = []
        if pop < floor and peak > floor:
            why.append(f"down to {pop} dwarves, under its floor of {floor} (it once had {peak})")
        share = float(_c(cfg, "recovery_drop_share"))
        if year_high >= int(_c(cfg, "recovery_drop_min")) and pop <= year_high * (1 - share) + 1e-9:
            why.append(f"fell from {year_high} to {pop} within a year")
        if why:
            rec.update({"since": now, "why": "; ".join(why), "floor": floor, "entered_pop": pop, "low": pop,
                        "above_since": now if pop >= floor else None, "calls": []})
            rec.pop("needs", None)
            notes.append("RECOVERY: the fort has fallen (" + "; ".join(why) + "): survival first (water, food, "
                         "drink, beds, the hospital, the guard, the gates); new projects, hunts, kill zones and "
                         "lures wait; DF's population cap opened to migrants")
            _journal(rec, {"event": "entered", "why": "; ".join(why), "pop": pop, "floor": floor, "peak": peak,
                           "tick": now})
    else:
        rec["floor"] = floor
        rec["low"] = min(int(rec.get("low") or pop), pop)
        if pop >= floor:
            if not isinstance(rec.get("above_since"), int):
                rec["above_since"] = now
        else:
            rec["above_since"] = None
        above = rec.get("above_since")
        if (isinstance(above, int) and now - above >= int(_c(cfg, "recovery_leave_days")) * TICKS_PER_DAY
                and now - rec["since"] >= int(_c(cfg, "recovery_min_days")) * TICKS_PER_DAY):
            _leave(rec, now, pop, f"back to {pop} dwarves, at its floor of {floor} or over for a season", notes)
    r = in_recovery(memory)
    if r:
        s["_recovery"] = {"since": r["since"], "why": r.get("why"), "floor": r.get("floor"), "peak": peak,
                          "pop": pop, "low": r.get("low"), "days": (now - r["since"]) // TICKS_PER_DAY,
                          "calls": len(_l(r.get("calls")))}
    elif stalled(s, memory, cfg):
        s["_recovery"] = {"stalled": True, "pop": pop, "floor": int(cfg.get("survival_floor") or 0), "peak": peak}
    return r


def _leave(rec: dict, now: int, pop: int, why: str, notes: list) -> None:
    since = rec.get("since")
    days = (now - since) // TICKS_PER_DAY if isinstance(since, int) else 0
    notes.append(f"recovery over: {why}, after {days} days (the lowest {rec.get('low')}): the fort's own plans "
                 "go on")
    _journal(rec, {"event": "left", "why": why, "pop": pop, "days": days, "low": rec.get("low"), "tick": now})
    for k in ("since", "why", "floor", "entered_pop", "low", "above_since", "calls", "needs"):
        rec.pop(k, None)
    rec["base_from"] = now
    rec["weeks"] = [[now // TICKS_PER_WEEK, pop]]


def held_in_recovery(p) -> str | None:
    """What waits while the fort recovers (in words), or None for a step that goes."""
    a = _d(getattr(p, "action", None))
    t = a.get("type")
    if t == "start_project":
        if a.get("urgent") or p.rule == "mood":
            return None
        kind = a.get("kind")
        if kind in SURVIVAL_KINDS and not a.get("set_piece") and not a.get("growth") and not a.get("landmark"):
            return None
        return f"a new {a.get('set_piece') or kind or '?'} level"
    if p.rule in _KEEP_RULES:
        return None
    if t in HOLD_TYPES:
        return str(t).replace("_", " ")
    if p.rule in HOLD_RULES:
        return str(p.rule).replace("_", " ")
    return None


def recovery_apply(proposals: list, memory, notes: list) -> list:
    """While in recovery: the non-survival steps wait (said in one note);
    the survival rules move up a step (crisis mode moves them itself)."""
    r = in_recovery(memory)
    if not r:
        return proposals
    in_crisis = bool(_d(getattr(memory, "crisis", None)).get("why"))
    kept, waiting = [], []
    for p in proposals:
        w = held_in_recovery(p)
        if w:
            waiting.append(w)
            continue
        if p.rule in _KEEP_RULES and not in_crisis:
            p.priority -= 1
        kept.append(p)
    if waiting:
        names = sorted(set(waiting))
        notes.append(f"recovery ({r.get('why')}): {len(waiting)} step(s) wait until the fort is back on its "
                     f"feet: {', '.join(names[:8])}" + (" ..." if len(names) > 8 else ""))
    return kept


def open_cap(s: dict, memory, cfg: dict, citizens: int, cap: int, strict: int, why: str,
             babies: dict) -> tuple:
    """(called from planner_growth._pop_cap_rule) DF's cap opened to migrants
    while the fort recovers: at least the floor and recovery_cap_room over
    the citizens, past the strain and slow-game holds; never in Maintain
    (the player's size) past its own cap, never in Extreme-low Growth. The
    baby caps raised as under the survival floor. Returns (cap, strict, why)."""
    r = in_recovery(memory)
    if not r:
        return cap, strict, why
    rules_ = player_rules(s)
    mode, _n = growth_mode(s, cfg)
    if mode == "shrink":
        return cap, strict, why
    floor = int(r.get("floor") or 0)
    want = max(floor, citizens + int(_c(cfg, "recovery_cap_room")))
    if rules_.get("fort_goal") == "maintain":
        want = min(want, max(cap, floor))
    if want > cap:
        why = (f"{why}; but the fort is recovering ({r.get('why')}): DF's cap opened to migrants "
               f"(Outsiders shuts visitors and trade, not migrants)")
        cap = want
    strict = max(strict, cap + 10)
    so = _d(s.get("society"))
    for k, ck in (("baby_cap", "floor_baby_cap"), ("baby_pct", "floor_baby_pct")):
        have, w = so.get(k), int(cfg.get(ck) or 0)
        if isinstance(have, int) and not isinstance(have, bool) and w and have < w:
            babies[k] = max(int(babies.get(k) or 0), w)
    return cap, strict, why


def _migrants_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """A fallen fort (or one stalled under the survival floor) DF sends no
    migrants to: the AI calls a wave (DFHack's force Migrants), or says
    why it can't (Needs you only when nothing else can be done)."""
    r = in_recovery(memory)
    stall = not r and stalled(s, memory, cfg)
    if not r and not stall:
        return
    rec = _d(getattr(memory, "recovery", None))
    now = abs_tick(s)
    pop = int(_d(s.get("dwarves")).get("total") or 0)
    wait = int(_c(cfg, "recovery_migrants_wait_days")) * TICKS_PER_DAY
    rise = rec.get("last_rise")
    start = r.get("since") if r else rec.get("first")
    quiet_since = max(x for x in (rise, start) if isinstance(x, int)) if any(
        isinstance(x, int) for x in (rise, start)) else now
    if now - quiet_since < wait:
        return
    days = (now - quiet_since) // TICKS_PER_DAY
    so = _d(s.get("society"))
    rules_ = player_rules(s)
    pc = so.get("pop_cap")
    who = "recovering" if r else f"stalled under its floor of {int(cfg.get('survival_floor') or 0)}"
    if isinstance(pc, int) and pc <= pop:
        if not rules_.get("set_pop_cap", True):
            ask_player(notes, f"the fort is {who} ({pop} dwarves) and no newcomer came in {days} days: DF's "
                              f"population cap is {pc}, yours (the Rules' population cap is off), so DF sends no "
                              "migrants: raise it in DF's settings or turn the Rules' population cap back on")
        else:
            notes.append(f"the fort is {who}: DF's population cap ({pc}) is opened this cycle before migrants "
                         "are called")
        return
    mig = s.get("migration")
    if not isinstance(mig, dict) or "error" in mig or not mig:
        notes.append(f"the fort is {who} and no newcomer came in {days} days; this bridge doesn't say whether a "
                     "migrant wave can be called (no migration section)")
        return
    if mig.get("hermit_tool"):
        ask_player(notes, f"the fort is {who} ({pop} dwarves) and DFHack's own `hermit` tool is on: it turns away "
                          "every migrant (and caravan); turn it off (`disable hermit`) for the fort to grow again")
        return
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        notes.append(f"the fort is {who}: a migrant wave is called once no enemy can reach the dwarves")
        return
    if int(mig.get("queued") or 0) > 0:
        notes.append(f"the fort is {who}: a migrant wave is on its way (DF's events)")
        return
    calls = [t for t in _l(rec.get("calls")) if isinstance(t, int) and (not isinstance(rise, int) or t > rise)]
    if len(calls) >= int(_c(cfg, "recovery_migrants_max_calls")):
        ask_player(notes, f"the fort is {who} ({pop} dwarves): no newcomer in {days} days and {len(calls)} migrant "
                          "waves called brought nobody; DF sends migrants by the wealth the fort created (reported "
                          "by the dwarven caravan as it leaves) and only while the home civilisation lives and isn't "
                          "at civil war: the AI has nothing more to try; the fort goes on with what it has")
        return
    if not rules_.get("call_migrants", True):
        ask_player(notes, f"the fort is {who} ({pop} dwarves) and DF sent no migrants in {days} days though its "
                          "cap is open: the AI would call a wave (DFHack's force Migrants) but the Rules' "
                          "\"call migrants\" is off")
        return
    if not mig.get("force"):
        ask_player(notes, f"the fort is {who} ({pop} dwarves) and DF sent no migrants in {days} days though its "
                          "cap is open, and this DFHack has no `force` script to call a wave (a newer DFHack has "
                          "one); the fort goes on with what it has")
        return
    proposals.append(Proposal("recovery_migrants", {"type": "call_migrants"},
                              f"the fort is {who} ({pop} dwarves, the cap {pc}) and DF sent no migrants in "
                              f"{days} days: call a wave (DFHack's {mig.get('force')} Migrants)", 4))


def recovery_journal(memory) -> list:
    """The journal entries waiting (each written once)."""
    rec = getattr(memory, "recovery", None)
    if not isinstance(rec, dict):
        return []
    out = [e for e in _l(rec.get("journal")) if isinstance(e, dict)]
    rec["journal"] = []
    return out


def recovery_line(s: dict) -> str:
    """The digest's RECOVERY line, or ""."""
    r = s.get("_recovery")
    if not isinstance(r, dict) or not r:
        return ""
    if r.get("stalled"):
        return (f"RECOVERY stalled: {r.get('pop')} dwarves under the survival floor of {r.get('floor')} with no "
                f"newcomer a long while (peak {r.get('peak')})")
    return (f"RECOVERY {r.get('days')} days ({r.get('why')}) | floor {r.get('floor')} peak {r.get('peak')} now "
            f"{r.get('pop')} low {r.get('low')} | migrant waves called {r.get('calls') or 0} | survival first: "
            "new projects, hunts, kill zones, lures wait; the cap is open to migrants")
