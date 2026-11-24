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
    off the map (`free_caravan`, DFHack emigration's own flags),
    `h9_caravan_free_max` times; (0.105.97) then taken to the map's edge
    (step "edge": teleported to an edge tile of their own walk group,
    `h9_caravan_edge_max` times); once none of its merchants is on the map
    and DF still holds it Leaving, DFHack's own fix/stuck-merchants and
    `caravan leave` (step "dismiss", `h9_caravan_dismiss_max` times); each
    step `h9_caravan_step_days` after the try before; only then a Needs you
    saying what was tried and what DFHack answered; with no other
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

__all__ = ["note_outside", "stuck_caravans", "gone_caravans", "drought_cause", "_drought_rule",
           "note_caravan_try"]

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
    _book_stuck(o, mig, seen, now, cfg)
    # the AI's calls (record() kept the tick of the rule's last done action)
    lf = _d(getattr(memory, "last_fired", None)).get("migrant_drought")
    if isinstance(lf, int) and lf != o.get("call_seen") and lf <= now:
        o["call_seen"] = lf
        o["calls"] = (_l(o.get("calls")) + [lf])[-10:]
    lf = _d(getattr(memory, "last_fired", None)).get("stuck_caravan")
    if isinstance(lf, int) and lf != o.get("free_seen") and lf <= now:
        o["free_seen"] = lf
        _book_try_seen(o, lf, cfg)
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


# --- (0.105.97) the stuck caravan's escalation ------------------------------------------
#
# B (23 Nov): a caravan stuck "Leaving" 118 days with 2 merchants on the map;
# told to walk off twice, they stayed, and the AI only said so (a Needs you)
# while no caravan and few migrants came. Each stuck caravan now has its book
# in memory.outside["stuck"] (by civilisation): since when it is stuck, its
# tries ([tick, step, what the bridge said]) and since when its merchants are
# gone from the map while DF still holds it Leaving ("gone").

STEPS = ("walk", "edge", "dismiss")


def _book_stuck(o: dict, mig: dict, seen: dict, now: int, cfg: dict) -> None:
    """The stuck book kept: a caravan leaving with its merchants on the map
    h9_caravan_stuck_days gets an entry; it stays while DF holds the caravan
    leaving (its merchants gone: "gone" since then); a caravan gone home or
    trading again drops it. 0.105.96's walk tries ("frees") are carried over."""
    wait = int(_c(cfg, "h9_caravan_stuck_days")) * TICKS_PER_DAY
    old = _d(o.get("stuck"))
    frees = [t for t in _l(o.get("frees")) if isinstance(t, int)]
    new = {}
    for c in _l(mig.get("caravans")):
        c = _d(c)
        ent = c.get("entity")
        if not isinstance(ent, int) or not c.get("leaving"):
            continue
        k = str(ent)
        e = dict(_d(old.get(k)))
        if int(c.get("merchants") or 0) > 0:
            since = seen.get(k)
            if not e:
                if not isinstance(since, int) or now - since < wait:
                    continue
                e = {"since": since, "tries": [[t, "walk", ""] for t in frees if t >= since][-10:]}
            e.pop("gone", None)
        else:
            if not e:
                continue                         # leaving, no merchant on the map: DF's own business
            if not isinstance(e.get("gone"), int) or e["gone"] > now:
                e["gone"] = now
        if not isinstance(e.get("since"), int) or e["since"] > now:
            e["since"] = now
        e["tries"] = [t for t in _l(e.get("tries")) if isinstance(t, list) and t and isinstance(t[0], int)
                      and t[0] <= now][-12:]
        new[k] = e
    o["stuck"] = new
    o.pop("frees", None)


def _counts(e: dict) -> dict:
    n = {k: 0 for k in STEPS}
    for t in _l(e.get("tries")):
        st = t[1] if isinstance(t, list) and len(t) > 1 else "walk"
        n[st if st in n else "walk"] += 1
    return n


def _next_step(e: dict, cfg: dict, at: int | None = None) -> str:
    """The step the rule takes next for this book (by its tries so far; dismiss
    when its merchants were gone by `at`)."""
    if isinstance(e.get("gone"), int) and (at is None or e["gone"] <= at):
        return "dismiss"
    n = _counts(e)
    return "walk" if n["walk"] < int(_c(cfg, "h9_caravan_free_max")) else "edge"


def _book_try_seen(o: dict, lf: int, cfg: dict) -> None:
    """A try the rule's cooldown says was done (record booked last_fired) and
    note_caravan_try did not book (a test, an older record): put in the book
    of the caravan the rule acts on first, its step worked out."""
    books = _d(o.get("stuck"))
    if any(isinstance(t, list) and t and t[0] == lf for e in books.values() for t in _l(_d(e).get("tries"))):
        return
    if not books:
        return
    k = sorted(books, key=lambda k: (isinstance(_d(books[k]).get("gone"), int),
                                     int(_d(books[k]).get("since") or 0)))[0]
    e = _d(books[k])
    e["tries"] = (_l(e.get("tries")) + [[lf, _next_step(e, cfg, lf), ""]])[-12:]


def _said(step: str, r: dict) -> str:
    """What the bridge answered a try, short."""
    if not isinstance(r, dict):
        return ""
    if step == "dismiss":
        ran = r.get("ran")
        ran = list(ran.values()) if isinstance(ran, dict) else _l(ran)
        bits = []
        for x in ran:
            x = _d(x)
            out = " ".join(str(x.get("out") or "").split())[:80]
            bits.append(f"`{x.get('cmd')}`: {'ok' if x.get('ok') else 'failed'}" + (f" ({out})" if out else ""))
        if r.get("skipped"):
            bits.append(str(r["skipped"])[:120])
        if r.get("still") is True:
            bits.append("DF still held it leaving")
        if not bits and r.get("error"):
            bits.append(str(r["error"])[:120])
        return "; ".join(bits)
    if r.get("ok") is False:
        return str(r.get("error") or "refused")[:160]
    if step == "edge":
        extra = [f"{r[k]} {w}" for k, w in (("shut", "with no way out"), ("held", "fighting or held"),
                                            ("no_tile", "with no edge tile"), ("failed", "not moved"))
                 if isinstance(r.get(k), int) and r[k]]
        return f"{r.get('moved', r.get('told'))} taken to the edge" + (" (" + ", ".join(extra) + ")" if extra else "")
    return f"{r.get('told')} told to leave" if r.get("told") is not None else ""


def note_caravan_try(p, r, memory, now: int) -> None:
    """(0.105.97, record) a free_caravan try booked in its caravan's book with
    its step and what the bridge said (refused ones too: a step DF refuses
    counts, so the next step comes). A dry run books nothing."""
    a = _d(getattr(p, "action", None))
    if a.get("type") != "free_caravan" or a.get("dry_run"):
        return
    step = a.get("step") if a.get("step") in STEPS else "walk"
    o = _mem(memory, True)
    books = o.setdefault("stuck", {})
    k = str(a.get("entity"))
    e = books.get(k)
    if not isinstance(e, dict):
        e = books[k] = {"since": now, "tries": []}
    tries = [t for t in _l(e.get("tries")) if not (isinstance(t, list) and t and t[0] == now)]
    e["tries"] = (tries + [[now, step, _said(step, _d(r))]])[-12:]


def gone_caravans(s: dict, memory, cfg: dict) -> list:
    """(0.105.97) The stuck caravans DF still holds leaving with none of their
    merchants on the map: [{entity, ..., days (stuck), gone_days}]."""
    books = _d(_mem(memory).get("stuck"))
    now = abs_tick(s)
    out = []
    for c in _l(_d(s.get("migration")).get("caravans")):
        c = _d(c)
        e = _d(books.get(str(c.get("entity"))))
        if c.get("leaving") and not int(c.get("merchants") or 0) and isinstance(e.get("gone"), int):
            out.append({**c, "days": (now - int(e.get("since") or now)) // TICKS_PER_DAY,
                        "gone_days": (now - e["gone"]) // TICKS_PER_DAY})
    out.sort(key=lambda c: (not c.get("own"), -int(c.get("days") or 0)))
    return out


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
    gone = gone_caravans(s, memory, cfg)                  # (0.105.97)
    if gone:
        c = gone[0]
        who = "the fort's own civilisation's caravan" if c.get("own") else "a caravan"
        return ("caravan", f"DF still holds {who} leaving {c.get('days')} days, {c.get('gone_days')} days after "
                           f"its last merchant left the map (DF's state {c.get('state')}): DF sends no caravan or "
                           "migrant while it lasts (DF bug 12624)", False)
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
    gone = gone_caravans(s, memory, cfg)
    if now - start < wait and not stuck and not gone:
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
    # a caravan stuck leaving: its merchants told to walk off, then taken to the
    # edge, then DFHack's fixes (stuck, drought or not: no caravan comes while it lasts)
    if stuck or gone:
        _caravan_step(s, memory, cfg, stuck, gone, proposals, notes)
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


def _tried(n: dict, e: dict) -> str:
    """What the AI tried on a stuck caravan, in words (with DFHack's answers)."""
    bits = []
    if n["walk"]:
        bits.append(f"told its merchants to walk off {n['walk']} time(s)")
    if n["edge"]:
        last = next((t[2] for t in reversed(_l(e.get("tries"))) if isinstance(t, list) and len(t) > 2
                     and t[1] == "edge" and t[2]), "")
        bits.append(f"took them to the map's edge {n['edge']} time(s)" + (f" ({last})" if last else ""))
    if n["dismiss"]:
        last = next((t[2] for t in reversed(_l(e.get("tries"))) if isinstance(t, list) and len(t) > 2
                     and t[1] == "dismiss" and t[2]), "")
        bits.append("ran DFHack's fix/stuck-merchants and `caravan leave`" + (f" ({last})" if last else ""))
    return ", ".join(bits) if bits else "nothing yet"


def _caravan_step(s: dict, memory, cfg: dict, stuck: list, gone: list, proposals: list, notes: list) -> None:
    """(0.105.97) The stuck caravan's next step, each h9_caravan_step_days
    after the try before: walk off (free_max), taken to the edge (edge_max),
    with its merchants gone DFHack's fixes (dismiss_max); then a Needs you
    saying what was tried. B, 23 Nov: 118 days stuck, two walk-offs, and
    only a Needs you."""
    now = abs_tick(s)
    books = _d(_mem(memory).get("stuck"))
    on_map = bool(stuck)
    c = stuck[0] if on_map else gone[0]
    ent = c.get("entity")
    e = _d(books.get(str(ent)))
    n = _counts(e)
    ticks = [t[0] for t in _l(e.get("tries")) if isinstance(t, list) and t and isinstance(t[0], int)]
    gap = int(_c(cfg, "h9_caravan_step_days")) * TICKS_PER_DAY
    rested = not ticks or now - max(ticks) >= gap
    tried = _tried(n, e)
    if on_map:
        if c.get("can_leave") == 0:
            ask_player(notes, f"a caravan has been leaving {c.get('days')} days and none of its "
                              f"{c.get('merchants')} merchant(s) has a way to the map's edge: open the way out "
                              "(gates, bridges, walls) so they can go home")
            return
        if n["walk"] < int(_c(cfg, "h9_caravan_free_max")):
            if rested:
                proposals.append(Proposal("stuck_caravan", {"type": "free_caravan", "entity": ent},
                                          f"a caravan has been leaving {c.get('days')} days and {c.get('merchants')} "
                                          "of its merchants are still on the map: tell them to walk off it, so the "
                                          "caravan gets home (and DF sends caravans and migrants again)", 5))
            return
        if n["edge"] < int(_c(cfg, "h9_caravan_edge_max")):
            if rested:
                proposals.append(Proposal("stuck_caravan", {"type": "free_caravan", "entity": ent, "step": "edge"},
                                          f"a caravan has been leaving {c.get('days')} days and its "
                                          f"{c.get('merchants')} merchant(s) stayed when told to walk off "
                                          f"{n['walk']} time(s) (DF bug 12624): take them to the map's edge, "
                                          "so they leave at once", 5))
            return
        ask_player(notes, f"a caravan has been leaving {c.get('days')} days with {c.get('merchants')} "
                          f"merchant(s) on the map; the AI {tried}, and they stayed (DF bug 12624): DF sends "
                          "no caravan, and maybe no migrant, while it lasts; DFHack's `caravan` command shows it")
        return
    # its merchants gone, DF still holding it leaving
    others = sum(int(_d(x).get("merchants") or 0) for x in _l(_d(s.get("migration")).get("caravans")))
    if n["dismiss"] < int(_c(cfg, "h9_caravan_dismiss_max")):
        if others > 0:
            notes.append(f"a caravan's merchants are gone from the map but DF still holds it leaving "
                         f"({c.get('gone_days')} days): DFHack's fix/stuck-merchants waits until no merchant of "
                         f"any caravan is on the map ({others} now)")
            return
        if rested and now - int(e.get("gone") or now) >= gap:
            proposals.append(Proposal("stuck_caravan", {"type": "free_caravan", "entity": ent, "step": "dismiss"},
                                      f"DF still holds a caravan leaving {c.get('gone_days')} days after its last "
                                      "merchant left the map (DF bug 12624): DFHack's fix/stuck-merchants and "
                                      "`caravan leave` dismiss it, so DF sends caravans and migrants again", 5))
        return
    ask_player(notes, f"DF still holds a caravan leaving {c.get('days')} days, {c.get('gone_days')} days after its "
                      f"last merchant left the map; the AI {tried}, and DF still holds it (DF bug 12624): DF "
                      "sends no caravan, and maybe no migrant, while it lasts; DFHack's `caravan` command shows it")
