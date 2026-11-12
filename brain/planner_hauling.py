"""(0.105.40, M5) Hauling, balanced. Before this the hauling labours were
never balanced: planner_labor's waiting-work rule skips every HAUL_ labour
(the work details' hauling is the game's own), and a stuck haul was only
said (planner_society's "waiting for a hauler"). In a big fort the haul jobs
pile up and every chain stalls behind them: stone to the masons, logs to the
carpenters, food to the kitchen, bodies to the tombs.

The `hauling` report (lua/ai-hauling.lua): the haul jobs waiting and taken,
by labour, and how many days the oldest has waited; the haulers (civilians
with a hauling labour) and the idle ones; the idle civilians who don't haul
(`candidates`: no soldiers, children, specialists you made, key workers or
dwarves in a mood); the key specialists who haul (doctors and the chief
medical dwarf, manager, bookkeeper, broker, the posts the AI staffs, a dwarf
in a strange mood, a legendary worker) and through what (`via`: the AI's own
detail, the game's Haulers detail at "everybody", or yours); the dwarves the
AI relieved (`relieved`, and those no longer key, `relieved_stale`).

The rule, with the fort's haulers wanted = the larger of a share of the
civilians and one per `hauling_jobs_per_hauler` jobs waiting (at most a
share of the civilians):

  * hauling_add: a backlog that stalls (many jobs waiting, the oldest a day
    or more, no hauler idle) with fewer haulers than wanted: idle civilians
    who don't haul put on the AI's own hauling detail, a few at a time;
  * hauling_back: stalled, short and nobody left to add: the specialists the
    AI relieved given hauling back; and any it relieved who are no longer key;
  * hauling_relieve: no stall, and enough haulers without them: the key
    specialists taken off hauling, a few at a time;
  * (0.105.40b fix) hauling_shrink: haulers to spare (more than wanted and
    the margin, no stall) for `hauling_shrink_days` (note_hauling keeps the
    since in memory.hauling_surplus): the dwarves the AI put on its own
    detail a week or more ago taken off it again, a few at a time.

(0.105.40b fix) A Haulers detail you set to "only selected" (a new fort's is
"everybody") means you pick the haulers: the AI adds none through its own
detail either, and says so.

The player's own work details (any you made, the game's Haulers detail
itself, one you set to nobody) are never changed; the bridge refuses too.
Without a `hauling` section (an older bridge, a failed one) nothing here
proposes or says anything.
"""

from __future__ import annotations

import math

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, TICKS_PER_YEAR

__all__ = ["hauling_report", "haulers_wanted", "hauling_stalled", "_hauling_labor_rule", "hauling_line",
           "note_hauling", "hauling_surplus"]


def _int(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def hauling_report(s: dict) -> dict | None:
    """The bridge's hauling section, or None (an older bridge, a failed or an
    empty section)."""
    h = s.get("hauling")
    if not isinstance(h, dict) or not h or "error" in h:
        return None
    if not isinstance(h.get("backlog"), dict) or not isinstance(h.get("haulers"), dict):
        return None
    if "error" in h["backlog"] or "error" in h["haulers"]:
        return None
    return h


def haulers_wanted(civilians: int, waiting: int, cfg: dict) -> int:
    """Haulers the fort wants: a share of the civilians at least, one per
    hauling_jobs_per_hauler jobs waiting, at most hauling_max_share of them."""
    floor = max(cfg["hauling_min_haulers"], math.ceil(civilians * cfg["hauling_min_share"]))
    by_jobs = math.ceil(waiting / max(1, cfg["hauling_jobs_per_hauler"]))
    return max(0, min(max(floor, by_jobs), math.floor(civilians * cfg["hauling_max_share"])))


def hauling_stalled(h: dict, cfg: dict) -> bool:
    """Many haul jobs waiting, the oldest a day or more, no hauler idle."""
    b, hs = _d(h.get("backlog")), _d(h.get("haulers"))
    return (_int(b.get("waiting")) >= cfg["hauling_backlog_min"]
            and _int(b.get("oldest_days")) >= cfg["hauling_wait_days"]
            and _int(hs.get("idle_any")) <= cfg["hauling_idle_max"])


def _now(s: dict) -> int:
    d = _d(s.get("date"))
    return _int(d.get("year")) * TICKS_PER_YEAR + _int(d.get("tick"))


def hauling_surplus(h: dict, cfg: dict) -> int:
    """Haulers to spare: those past wanted and the margin, 0 while stalled."""
    b, hs = _d(h.get("backlog")), _d(h.get("haulers"))
    civilians = _int(hs.get("civilians"))
    if civilians <= 0 or hauling_stalled(h, cfg):
        return 0
    want = haulers_wanted(civilians, _int(b.get("waiting")), cfg)
    return max(0, _int(hs.get("any")) - want - cfg["hauling_relieve_margin"])


def note_hauling(s: dict, memory, cfg: dict) -> None:
    """(0.105.40b fix, note_cycle) Since when the fort has had haulers to
    spare (memory.hauling_surplus = {since}); {} while it hasn't. Nothing
    without a hauling section."""
    h = hauling_report(s)
    if h is None or memory is None:
        return
    now = _now(s)
    if hauling_surplus(h, cfg) > 0:
        since = _d(getattr(memory, "hauling_surplus", None)).get("since")
        memory.hauling_surplus = {"since": since if isinstance(since, int) and since <= now else now}
    else:
        memory.hauling_surplus = {}


def _kinds(b: dict, n: int = 3) -> str:
    rows = [(k, _int(_d(v).get("waiting"))) for k, v in _d(b.get("by")).items()]
    rows = sorted((r for r in rows if r[1] > 0), key=lambda r: (-r[1], r[0]))[:n]
    return ", ".join(f"{k.lower().replace('haul_', '')} {v}" for k, v in rows)


def _hauling_labor_rule(s: dict, cfg: dict, citizens: int, proposals: list, notes: list, memory=None) -> None:
    """(0.105.40 M5) Enough haulers for the backlog; key specialists off it
    while there are enough others (see the module)."""
    h = hauling_report(s)
    if h is None:
        return
    b, hs = _d(h.get("backlog")), _d(h.get("haulers"))
    civilians = _int(hs.get("civilians"))
    if civilians <= 0:
        return
    waiting, oldest = _int(b.get("waiting")), _int(b.get("oldest_days"))
    have, cands = _int(hs.get("any")), _int(hs.get("candidates"))
    relievable, relieved, stale = _int(hs.get("relievable")), _int(hs.get("relieved")), _int(hs.get("relieved_stale"))
    want = haulers_wanted(civilians, waiting, cfg)
    stalled = hauling_stalled(h, cfg)
    mode = _d(h.get("detail")).get("mode")
    kinds = _kinds(b)
    jobs = f"{waiting} haul job(s) wait" + (f" ({kinds})" if kinds else "") + \
        (f", the oldest {oldest} day(s)" if oldest else "")

    if stale > 0:
        proposals.append(Proposal("hauling_back", {"type": "relieve_haulers", "count": min(cfg["hauling_relieve_max"], stale),
                                                   "back": True},
                                  f"{stale} dwarf(s) the AI took off hauling no longer hold a key post: "
                                  "hauling given back", 6))
    if stalled and have < want:
        if mode == "NobodyDoesThis":
            notes.append(f"{jobs} and {have} dwarves haul: the {_d(h.get('detail')).get('name') or 'Haulers'} "
                         "work detail is set to nobody (your choice), so the AI adds no hauler")
            return
        short = want - have
        if mode == "OnlySelectedDoesThis":
            # (0.105.40b fix) you pick the haulers: no hauler added by the AI
            notes.append(f"{jobs} and {have} dwarves haul ({want} wanted): the "
                         f"{_d(h.get('detail')).get('name') or 'Haulers'} work detail is set to only selected "
                         "(your choice), so the AI adds no hauler; meanwhile it takes no key worker off hauling")
            if relieved > stale:
                n = min(cfg["hauling_relieve_max"], short, relieved - stale)
                proposals.append(Proposal("hauling_back", {"type": "relieve_haulers", "count": n, "back": True},
                                          f"{jobs}, {have} dwarves haul ({want} wanted): {n} key worker(s) the "
                                          "AI took off hauling given it back", 4))
            return
        if cands > 0 and not h.get("ai_detail_gone"):
            n = min(cfg["hauling_add_max"], short, cands)
            proposals.append(Proposal("hauling_add", {"type": "add_haulers", "count": n},
                                      f"{jobs} and none of the {have} haulers is free ({want} wanted): {n} idle "
                                      "civilian(s) who don't haul put on the AI haulers work detail", 3))
        elif relieved > stale:
            n = min(cfg["hauling_relieve_max"], short, relieved - stale)
            proposals.append(Proposal("hauling_back", {"type": "relieve_haulers", "count": n, "back": True},
                                      f"{jobs}, {have} dwarves haul ({want} wanted) and nobody idle is left: "
                                      f"{n} key worker(s) the AI took off hauling given it back", 4))
        return
    if stalled:
        return
    spare = have - want - cfg["hauling_relieve_margin"]
    if spare <= 0:
        return
    # (0.105.40b fix 2) key workers the AI would relieve but for another
    # "everybody" detail of yours (the specialist mark would take them off it too)
    blocked = [x for x in _l(hs.get("specialists")) if isinstance(x, dict) and x.get("blocked_by")]
    if blocked:
        names = ", ".join(f"{x.get('name') or x.get('id')} ({x.get('why')})" for x in blocked[:3])
        notes.append(f"{len(blocked)} key worker(s) haul though {have} others do ({want} wanted): {names}; the AI "
                     f"leaves them hauling, as taking them off (the specialist mark) would also take them off your "
                     f"'{blocked[0].get('blocked_by')}' work detail, which everybody does")
    if relievable <= 0:
        # (0.105.40b fix) the AI's own detail shrinks: spare haulers for a week
        old = _int(_d(h.get("ai_detail")).get("added_old"))
        since = _d(getattr(memory, "hauling_surplus", None)).get("since") if memory is not None else None
        now = _now(s)
        if old > 0 and isinstance(since, int) and now - since >= cfg["hauling_shrink_days"] * TICKS_PER_DAY:
            n = min(cfg["hauling_shrink_max"], old, spare)
            proposals.append(Proposal("hauling_shrink", {"type": "relieve_haulers", "count": n, "shrink": True},
                                      f"{have} dwarves haul ({want} wanted for {waiting} job(s) waiting) and have "
                                      f"for {(now - since) // TICKS_PER_DAY} day(s): {n} of those the AI put on its haulers "
                                      "work detail taken off it again", 7))
        return
    n = min(cfg["hauling_relieve_max"], relievable, spare)
    who = [x for x in _l(hs.get("specialists")) if isinstance(x, dict) and x.get("via") in ("ai", "everybody")]
    names = ", ".join(f"{x.get('name') or x.get('id')} ({x.get('why')})" for x in who[:n])
    proposals.append(Proposal("hauling_relieve", {"type": "relieve_haulers", "count": n},
                              f"{have} dwarves haul ({want} wanted for {waiting} job(s) waiting): {n} key "
                              "worker(s) taken off hauling to keep to their own work"
                              + (f": {names}" if names else ""), 6))


def hauling_line(s: dict) -> str:
    """The hauling in a line for the digest; "" without a hauling section."""
    h = hauling_report(s)
    if h is None:
        return ""
    b, hs = _d(h.get("backlog")), _d(h.get("haulers"))
    kinds = _kinds(b, 4)
    d = _d(h.get("detail"))
    return (f"HAULING waiting {_int(b.get('waiting'))} taken {_int(b.get('taken'))} oldest {_int(b.get('oldest_days'))}d"
            + (f" ({kinds})" if kinds else "")
            + f" | haulers {_int(hs.get('any'))} of {_int(hs.get('civilians'))} civilians, idle {_int(hs.get('idle_any'))}"
            + f" | idle non-haulers {_int(hs.get('candidates'))} | key workers hauling {_int(hs.get('relievable'))}"
            + f" relieved {_int(hs.get('relieved'))}"
            + (f" | detail {d.get('name')}: {d.get('mode')}" if d.get("name") else ""))
