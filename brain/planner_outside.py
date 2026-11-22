"""(r2 h9) The world outside: a fort DF sends no migrants to for seasons,
and a caravan that never left.

Why (the 15-16 Nov run, R-B.md): from y251 to y261 B had no migrant and no
caravan. The y251 caravan said "will be leaving soon" and never embarked:
its two merchants were still on the map in y261, the fort's 325 goods
stayed locked in its depot, and the 12 waves the recovery called with
DFHack's force Migrants ("ok, queued: 1") brought nobody. DF's own bug
12624 has the same signs (a caravan stuck "Leaving" for years, forced
migrant waves arriving empty). DF sends migrants after the first two waves
by the wealth the fort created, as the outgoing caravan reports it home: a
caravan that never goes home reports nothing. Nothing said so in ten years.

_drought_rule (every cycle, bookkeeping in memory.outside):
  * a migrant wave is a rise of `h9_wave_min` citizens or more at once (one
    alone is a birth); the drought is `h9_drought_days` without one (the
    fort watched that long). Not in Maintain or Extreme-low Growth (no
    newcomers on purpose).
  * the cause, said once a season (a note; a Needs you only where the player
    must act), the first that holds: DF's population cap at or under the
    citizens (the AI's cap rule says why it holds; the player's own cap is a
    Needs you); DFHack's hermit tool; the fort's civilisation gone; a caravan
    stuck leaving (its merchants on the map `h9_caravan_stuck_days` after it
    began to leave); a siege or an enemy at the edge; else not known.
  * what the AI does about it: a stuck caravan's merchants are told to walk
    off the map (`free_caravan`, DFHack emigration's own flags), once a
    month, `h9_caravan_free_max` times, then a Needs you; with no other
    cause a wave is called (`call_migrants`, Rules "call migrants") once a
    season, at most `h9_drought_max_calls` calls that brought nobody, then
    said plainly. A fallen or stalled fort's calls stay the recovery's
    (planner_recovery._migrants_rule): never two callers.

The trade module (lua/ai-trade.lua) is not touched: the caravans are read
by the migration section (lua/ai-recovery.lua caravans()).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, TICKS_PER_DAY, Proposal, abs_tick, ask_player, growth_mode,
                          player_rules)

__all__ = ["note_outside", "stuck_caravans", "drought_cause", "_drought_rule"]

from util import conf_lookup as _c  # noqa: E402  (r6 c2) was a copy here


def _mem(memory, write: bool = False) -> dict:
    """memory.outside: booked by note_outside (note_cycle), read by the rule
    (plan() never writes memory)."""
    o = getattr(memory, "outside", None)
    if not isinstance(o, dict):
        o = {}
        if write:
            try:
                memory.outside = o
            except Exception:  # noqa: BLE001
                pass
    return o


def _pop(s: dict):
    try:
        from planner_recovery import fort_pop
        return fort_pop(s)
    except Exception:  # noqa: BLE001
        p = _d(s.get("dwarves")).get("total")
        return p if isinstance(p, int) and not isinstance(p, bool) else None


def note_outside(s: dict, memory, cfg: dict) -> dict:
    """Bookkeeping: the first tick watched, the last wave, the citizens last
    seen, the caravans leaving (since when, by civilisation); the drought and
    its cause. Returns the memory (note_cycle, before plan)."""
    o = _mem(memory, True)
    now = abs_tick(s)
    for k in ("first", "last_wave"):
        if isinstance(o.get(k), int) and o[k] > now:          # an older save loaded
            o.pop(k, None)
    if not isinstance(o.get("first"), int):
        o["first"] = now
    pop = _pop(s)
    if isinstance(pop, int) and pop > 0:
        last = o.get("last_pop")
        if isinstance(last, int) and pop - last >= int(_c(cfg, "h9_wave_min")):
            o["last_wave"] = now
            o["calls"] = []
        o["last_pop"] = pop
    # the caravans leaving with merchants on the map: since when
    mig = _d(s.get("migration"))
    seen = {}
    old = _d(o.get("leaving"))
    for c in _l(mig.get("caravans")):
        c = _d(c)
        ent = c.get("entity")
        if not isinstance(ent, int) or not c.get("leaving") or not int(c.get("merchants") or 0):
            continue
        since = old.get(str(ent))
        seen[str(ent)] = since if isinstance(since, int) and since <= now else now
    o["leaving"] = seen
    # the AI's calls (record() kept the tick of the rule's last done action)
    lf = _d(getattr(memory, "last_fired", None)).get("migrant_drought")
    if isinstance(lf, int) and lf != o.get("call_seen") and lf <= now:
        o["call_seen"] = lf
        o["calls"] = (_l(o.get("calls")) + [lf])[-10:]
    lf = _d(getattr(memory, "last_fired", None)).get("stuck_caravan")
    if isinstance(lf, int) and lf != o.get("free_seen") and lf <= now:
        o["free_seen"] = lf
        o["frees"] = (_l(o.get("frees")) + [lf])[-10:]
    # the drought (no wave h9_drought_days) and its cause, for the rule and the digest
    start = max(x for x in (o.get("first"), o.get("last_wave")) if isinstance(x, int))
    mode, _n = growth_mode(s, cfg) if isinstance(s.get("settings"), dict) else ("target", None)
    on_purpose = mode == "shrink" or player_rules(s).get("fort_goal") == "maintain"
    if now - start >= int(_c(cfg, "h9_drought_days")) * TICKS_PER_DAY and not on_purpose:
        kind = drought_cause(s, memory, cfg)[0]
        o["drought"] = {"since": start, "days": (now - start) // TICKS_PER_DAY, "cause": kind}
    else:
        o.pop("drought", None)
    return o


def stuck_caravans(s: dict, memory, cfg: dict) -> list:
    """The caravans stuck leaving: [{entity, own, state, merchants, can_leave, days}]
    (leaving with merchants on the map h9_caravan_stuck_days or longer)."""
    o = _mem(memory)
    now = abs_tick(s)
    wait = int(_c(cfg, "h9_caravan_stuck_days")) * TICKS_PER_DAY
    out = []
    for c in _l(_d(s.get("migration")).get("caravans")):
        c = _d(c)
        since = _d(o.get("leaving")).get(str(c.get("entity")))
        if isinstance(since, int) and now - since >= wait:
            out.append({**c, "days": (now - since) // TICKS_PER_DAY})
    out.sort(key=lambda c: (not c.get("own"), -int(c.get("days") or 0)))
    return out


def drought_cause(s: dict, memory, cfg: dict) -> tuple:
    """(kind, words, player) for a fort DF sends no migrants to: kind one of
    cap, hermit, civ, caravan, danger, unknown; player True when only the
    player can act."""
    so = _d(s.get("society"))
    pop = _pop(s) or 0
    pc = so.get("pop_cap")
    rules_ = player_rules(s)
    if isinstance(pc, int) and not isinstance(pc, bool) and pc <= pop:
        if not rules_.get("set_pop_cap", True):
            return ("cap", f"DF's population cap is {pc} with {pop} citizens, and it is yours (the Rules' "
                           "population cap is off): DF sends nobody past it; raise it in DF's settings", True)
        return ("cap", f"DF's population cap is {pc} with {pop} citizens: the AI's cap rule holds newcomers "
                       "out (its note says why)", False)
    mig = _d(s.get("migration"))
    if mig.get("hermit_tool"):
        return ("hermit", "DFHack's own `hermit` tool is on: it turns every migrant and caravan away "
                          "(`disable hermit`)", True)
    if mig.get("civ") is False:
        return ("civ", "the fort's civilisation is gone: no migrant will ever come from it", False)
    stuck = stuck_caravans(s, memory, cfg)
    if stuck:
        c = stuck[0]
        who = "the fort's own civilisation's caravan" if c.get("own") else "a caravan"
        return ("caravan", f"{who} has been leaving {c.get('days')} days with {c.get('merchants')} merchant(s) "
                           f"still on the map (DF's state {c.get('state')}): a caravan that never gets home "
                           "reports no wealth, and DF sends no caravan or migrant while it lasts (DF bug 12624)",
                False)
    try:
        from planner_recovery import migrants_wait
        hold = migrants_wait(s, cfg)
    except Exception:  # noqa: BLE001
        hold = None
    if hold:
        return ("danger", f"migrants come in at the map's edge: a wave is called once {hold}", False)
    return ("unknown", "no cause the AI can see (the cap is open, no caravan is stuck): DF sends migrants by "
                       "the wealth the fort created, as the outgoing caravan reports it", False)


def _drought_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """No migrant wave for h9_drought_days: the cause said, and what the AI
    controls done (a stuck caravan's merchants sent off; a wave called)."""
    o = _mem(memory)
    rules_ = player_rules(s)
    mode, _n = growth_mode(s, cfg) if isinstance(s.get("settings"), dict) else ("target", None)
    if mode == "shrink" or rules_.get("fort_goal") == "maintain":
        return
    now = abs_tick(s)
    pop = _pop(s) or 0
    if pop <= 0:
        return
    if not isinstance(o.get("first"), int):
        return                                   # not booked yet (note_outside runs before plan)
    start = max(x for x in (o.get("first"), o.get("last_wave")) if isinstance(x, int))
    wait = int(_c(cfg, "h9_drought_days")) * TICKS_PER_DAY
    stuck = stuck_caravans(s, memory, cfg)
    if now - start < wait and not stuck:
        return
    days = (now - start) // TICKS_PER_DAY
    kind, words, player = drought_cause(s, memory, cfg)
    drought = now - start >= wait
    if drought:
        say = f"no migrants in {days} days: {words}"
        if player:
            ask_player(notes, say)
        else:
            notes.append("MIGRANT DROUGHT: " + say)
    # a caravan stuck leaving: its merchants told to walk off (stuck, drought or not:
    # no caravan comes while it lasts)
    if stuck:
        c = stuck[0]
        ent = c.get("entity")
        since = _d(o.get("leaving")).get(str(ent))
        n = len([t for t in _l(o.get("frees")) if isinstance(t, int) and isinstance(since, int) and t >= since])
        if c.get("can_leave") == 0:
            ask_player(notes, f"a caravan has been leaving {c.get('days')} days and none of its "
                              f"{c.get('merchants')} merchant(s) has a way to the map's edge: open the way out "
                              "(gates, bridges, walls) so they can go home")
        elif n >= int(_c(cfg, "h9_caravan_free_max")):
            ask_player(notes, f"a caravan has been leaving {c.get('days')} days with {c.get('merchants')} "
                              f"merchant(s) on the map; the AI told them to walk off {n} time(s) and they stayed "
                              "(DF bug 12624): DF sends no caravan, and maybe no migrant, while it lasts; "
                              "DFHack's `caravan` command shows it")
        else:
            proposals.append(Proposal("stuck_caravan", {"type": "free_caravan", "entity": ent},
                                      f"a caravan has been leaving {c.get('days')} days and {c.get('merchants')} "
                                      "of its merchants are still on the map: tell them to walk off it, so the "
                                      "caravan gets home (and DF sends caravans and migrants again)", 5))
        return
    if not drought or kind != "unknown":
        return
    # nothing the AI can see in the way: a wave called, unless the recovery
    # calls them (a fallen or stalled fort): never two callers
    try:
        from planner_recovery import in_recovery, stalled
        if in_recovery(memory) or stalled(s, memory, cfg):
            return
    except Exception:  # noqa: BLE001
        pass
    if not rules_.get("call_migrants", True):
        notes.append(f"no migrants in {days} days and the Rules' \"call migrants\" is off: no wave is called")
        return
    mig = _d(s.get("migration"))
    if not mig.get("force"):
        return
    if int(mig.get("queued") or 0) > 0:
        notes.append("a migrant wave is on its way (DF's events)")
        return
    calls = [t for t in _l(o.get("calls")) if isinstance(t, int) and t >= start]
    if len(calls) >= int(_c(cfg, "h9_drought_max_calls")):
        notes.append(f"no migrants in {days} days and {len(calls)} wave(s) called brought nobody: the AI stops "
                     "calling; the fort grows by its births and goes on with what it has")
        return
    proposals.append(Proposal("migrant_drought", {"type": "call_migrants"},
                              f"no migrants in {days} days and no cause the AI can see: call a wave "
                              f"(DFHack's {mig.get('force')} Migrants; {len(calls)} called before)", 6))
