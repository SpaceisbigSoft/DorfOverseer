"""planner_gates_stuck: dwarves shut out (split out of planner_gates in r7,
0.105.62): the gate the game holds shut freed a step at a time, a way in
dug for those cut off, a second way to the surface, the citizens stranded
outside brought in. planner_gates re-exports every name here."""

from __future__ import annotations

from dataclasses import field
from culture import profile_from
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_construct import _wings_rule, cavern_wall_style  # (0.105.30) wing walls, the Hermit's cavern walls

__all__ = ["WAY_IN_KINDS", "GATE_STUCK_TRIED", "split_pieces", "stuck_rows", "PREVENT_BACKOFF_DAYS", "gate_exhausted", "player_gate_row", "note_gate_stuck", "note_gate_stuck_cycle", "note_second_way"]


# (0.105.32) E (8 Nov): the founding stair's hatch (building 7) read open
# after the watcher's instant lever pulls (shut 13:51:08, opened 13:51:11),
# but DF's walk map was split at it: the hatch and the surface one walk
# group, the stair and the fort another. Every citizen who went out, and
# every migrant wave, was stranded there and 64 died of thirst with 470+
# drinks in store; the rule only asked the player to "dig them a way in".
# The bridge now reports each such piece (an entrance's `split`) and marks
# its stranded `gate_stuck`; unstick_gate frees it a step at a time (1: its
# flags cleared, the walk map rebuilt; 2: its lever pulled twice; 3: taken
# down). Nobody knows yet which of those it takes: each is tried in turn.
WAY_IN_KINDS = ("way_in", "dig_way_in")      # the project dig_way_in starts (the report's projects)
GATE_STUCK_TRIED = {1: "its forbid and shut flags cleared and the walk map rebuilt",
                    2: "its lever pulled shut and open again",
                    3: "taken down"}


def split_pieces(s: dict) -> dict:
    """(0.105.32) Every gate piece the entrance scan found open but split
    (an entrance's `split`): piece id -> (piece, its entrance)."""
    out = {}
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict):
            continue
        for pc in _l(e.get("split")):
            if isinstance(pc, dict) and pc.get("id") is not None:
                out.setdefault(pc["id"], (pc, e))
    return out


def stuck_rows(s: dict) -> dict:
    """(0.105.32) The stranded each split piece shuts out: piece id ->
    rows. A row the bridge marked `gate_stuck` (its `stuck_gate`), or, from
    a bridge that doesn't mark them, a `no_path` row whose walk group is a
    split piece's outside group."""
    pieces = split_pieces(s)
    by_group = {pc.get("outside_group"): pid for pid, (pc, _e) in pieces.items()
                if pc.get("outside_group") is not None}
    out: dict = {}
    for r in _l(_d(s.get("entrances")).get("stranded")):
        if not isinstance(r, dict):
            continue
        pid = None
        if r.get("cause") == "gate_stuck":
            pid = r.get("stuck_gate") if r.get("stuck_gate") is not None else by_group.get(r.get("group"), "?")
        elif r.get("cause") == "no_path" and r.get("group") is not None and r.get("group") in by_group:
            pid = by_group[r["group"]]
        if pid is not None:
            out.setdefault(pid, []).append(r)
    return out


def _row_danger(r: dict):
    ds = [r.get(k) for k in ("danger_near", "gate_danger") if isinstance(r.get(k), (int, float))]
    return min(ds) if ds else None


def _flags_text(pc: dict) -> str:
    """The piece's flags as read, the shut ones first: 'closed=false forbidden=false ...'."""
    fl = _d(pc.get("flags"))
    keys = [k for k in ("closed", "forbidden") if k in fl]
    keys += sorted(k for k in fl if k not in keys and fl[k] not in (False, 0, None, ""))
    def v(x):
        return str(x).lower() if isinstance(x, bool) else str(x)[:20]
    return " ".join(f"{k}={v(fl[k])}" for k in keys[:8]) or "none read"


PREVENT_BACKOFF_DAYS = (1, 3, 7)    # (0.105.48, K2) a split nobody is shut out by: the waits between tries


def _gate_stuck_rule(s: dict, memory, cfg: dict, proposals: list, notes: list, off: int = 0) -> bool:
    """(0.105.32) unstick_gate for each open gate piece DF's walk map holds
    shut: at once for its stranded (no `stranded_after_ticks` wait: the
    hatch is the fort's way in), one step at a time, the next after
    `gate_stuck_step_hours` while it is still split; a split with nobody shut
    out yet gets step 1 at most once a game day. Held while an enemy is near
    them or the gate. True when a gate is being unstuck (the gate watcher
    isn't armed that cycle)."""
    pieces = split_pieces(s)
    rows_by = stuck_rows(s)
    if not pieces and not rows_by:
        return False
    if not isinstance(getattr(memory, "gate_unstick", None), dict):
        memory.gate_unstick = {}
    ent = _d(s.get("entrances"))
    now = abs_tick(s)
    hour = TICKS_PER_DAY // 24
    step_ticks = int(cfg.get("gate_stuck_step_hours", 6)) * hour
    near_d = cfg.get("stranded_danger_near", 30)
    scanned = ent.get("scanned_tick") if isinstance(ent.get("scanned_tick"), int) else None
    # (merge32 review) a siege: the lever pulled shut and open, the gate taken
    # down, only once nothing can reach the dwarves and the watcher is down
    reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
    siege = reach > 0 or bool(ent.get("armed"))
    # (0.105.35, the player: nothing waits for them) a cavern's way gets step
    # 2 too (cavern_ok) once the caverns are read and hold no great danger,
    # nothing can reach the dwarves and the watcher is down; (v35 fix) never
    # step 3 (taken down)
    from planner_threats import cavern_great, deep_read
    cave_safe = not siege and deep_read(s) and not cavern_great(s)
    from planner_way_out import sealed as _fort_sealed       # (0.105.47, J16) the one way-out check
    fort_sealed = _fort_sealed(s) is True
    acting = False
    for pid in list(dict.fromkeys(list(rows_by) + list(pieces))):
        pc, e = pieces.get(pid, ({}, {}))
        rows = rows_by.get(pid, [])
        if not pc and rows:
            e = _d(rows[0].get("entrance"))
        kind = pc.get("kind") if pc.get("kind") in ("hatch", "door") else "gate"
        x, y, z = (pc.get("x"), pc.get("y"), pc.get("z")) if pc else (e.get("x"), e.get("y"), e.get("z"))
        at = f"x{x} y{y} elevation {(z or 0) + off}" if isinstance(z, int) else f"x{x} y{y}"
        name = f"the {kind} (building {pid}) at {at}"
        rec = _d(memory.gate_unstick.get(str(pid)))
        cavern = bool(rec.get("cavern") or e.get("kind") == "cavern" or any(r.get("in_cavern") for r in rows))
        hot = [r for r in rows if _row_danger(r) is not None and _row_danger(r) <= near_d]
        if isinstance(pc.get("danger"), (int, float)) and pc["danger"] <= near_d:
            hot.append(pc)
        if hot:
            ds = [d for d in ([_row_danger(r) for r in rows] + [pc.get("danger")]) if isinstance(d, (int, float))]
            notes.append(f"{name} reads open but the game holds it shut ({len(rows)} citizen(s) can't get in), "
                         f"but an enemy is {min(ds)} tiles away: the AI waits to unstick it")
            continue
        last_step = rec.get("step") if isinstance(rec.get("step"), int) else 0
        last_tick = rec.get("tick") if isinstance(rec.get("tick"), int) else None
        since = now - last_tick if last_tick is not None and now >= last_tick else None
        step = None
        if rows:
            # still split: the bridge still marks its stranded, unless the last
            # step answered "joined" and no scan since has found it split again
            fresh = scanned is not None and last_tick is not None and scanned > last_tick
            still = rec.get("split_after") is not False or fresh
            if not last_step or since is None:
                step = 1
            elif last_step >= 3 and since >= step_ticks:
                # (merge32) every step tried (or taking it down refused: the
                # player's own piece): no more steps; the way in is dug
                # instead (_way_in_rule, gate_exhausted)
                step = None
            elif (rec.get("ok") is False and last_step == 2 and "no lever" in str(rec.get("done") or "")
                  and since >= step_ticks):
                step = 3                         # (merge32 review) an older bridge's "no lever" refusal: on to step 3
            elif rec.get("ok") is False and since >= step_ticks:
                step = last_step                 # refused (a reason given): the same step again
            elif still and since >= step_ticks:
                step = last_step + 1
            why = (f"{len(rows)} citizen(s) can't get back in ({', '.join(str(r.get('name') or 'a dwarf') for r in rows[:3])}"
                   + (f" and {len(rows) - 3} more" if len(rows) > 3 else "")
                   + f"): {name} reads open, but the game's walk map holds it shut")
            # (merge32 review) a cavern's way: not pulled shut and open nor
            # taken down while the caverns may hold a great danger; (0.105.35)
            # once they're read safe, it is (cavern_ok)
            if step in (2, 3) and cavern and not cave_safe:
                notes.append(f"{name} still holds {len(rows)} citizen(s) out on a cavern's way, but the caverns "
                             + ("hold a great danger" if cavern_great(s) else "couldn't be read" if not deep_read(s)
                                else "can't be trusted in a siege")
                             + f": step {step} ({GATE_STUCK_TRIED[step]}) waits until they're safe")
                step = None
            # (v35 fix) a cavern's way is never taken down (step 3): the way
            # into the caverns would stay open until a door is rebuilt; after
            # step 2 every step is tried there
            if step == 3 and cavern:
                step = None
            if step in (2, 3) and siege:
                notes.append(f"{name} still holds {len(rows)} citizen(s) out, but "
                             + (f"{reach} enemy(ies) can reach the dwarves" if reach else "the gate watcher is armed")
                             + f": step {step} ({GATE_STUCK_TRIED[step]}) waits until that is over")
                step = None
        elif fort_sealed and not cavern:
            # (0.105.47, J16) the whole fort sealed in (planner_way_out.sealed: the
            # citizens' walk group reaches no edge of the map) at a piece that reads
            # open: each step in turn, as for the stranded, not once a day
            if not last_step or since is None:
                step = 1
            elif rec.get("ok") is False and since >= step_ticks and last_step < 3:
                step = last_step
            elif last_step < 3 and since >= step_ticks and rec.get("split_after") is not False:
                step = last_step + 1
            if step in (2, 3) and siege:
                notes.append(f"the fort is sealed in at {name}, but "
                             + (f"{reach} enemy(ies) can reach the dwarves" if reach else "the gate watcher is armed")
                             + f": step {step} ({GATE_STUCK_TRIED[step]}) waits until that is over")
                step = None
            why = (f"the fort is sealed in at {name}: it reads open, but the game's walk map holds the way "
                   "through it shut")
        else:
            prev = rec.get("prevent") if isinstance(rec.get("prevent"), int) else None
            # (0.105.48, K2) War-hold: a split nobody is shut out by (it may be
            # real geometry) got step 1 and a rescan every day for 60 days. Backed
            # off 1, 3, 7 days (x gate_stuck_prevent_days); after
            # gate_stuck_prevent_max tries, left with a note (a citizen shut out
            # by it brings the stepped rule above back at once)
            tries = int(rec.get("prevent_n") or 0)
            days = int(cfg.get("gate_stuck_prevent_days", 1)) * PREVENT_BACKOFF_DAYS[
                min(max(tries - 1, 0), len(PREVENT_BACKOFF_DAYS) - 1)]
            if tries >= int(cfg.get("gate_stuck_prevent_max", 4)):
                notes.append(f"{name} reads open, but the game's walk map splits the way through it; step 1 "
                             f"was tried {tries} time(s) and the split stays with nobody shut out: left as it is "
                             "(unstuck at once if a citizen is shut out by it)")
            elif (not reach and not ent.get("armed") and (prev is None or not 0 <= now - prev < days * TICKS_PER_DAY)
                    and (since is None or since >= step_ticks)):
                step = 1
            why = (f"{name} reads open, but the game's walk map splits the way through it; nobody is shut "
                   "out yet" + (f" (try {tries + 1})" if tries else ""))
        if step and isinstance(pid, int):
            act = {"type": "unstick_gate", "id": pid, "step": step}
            if cavern and step >= 2:
                act["cavern_ok"] = True          # (0.105.35) the caverns read safe (cave_safe)
            proposals.append(Proposal("gate_stuck", act,
                                      f"{why}: unstick it, step {step} of 3 ({GATE_STUCK_TRIED[step]})", -1))
            acting = True
        if rows:
            # (0.105.35, the player: nothing waits for them) said as what the
            # AI does: each step in turn, then a way dug in. Kept as Needs you
            # only for a cavern's way with every step tried: no way in is dug
            # from a cavern (it would open the fort to it)
            tried = (f"step {last_step} ({GATE_STUCK_TRIED.get(last_step, '?')})"
                     + (f": {str(rec.get('done'))[:100]}" if rec.get("done") else "")
                     if last_step else "nothing yet")
            head = (f"{len(rows)} citizen(s) shut outside by {name}: it reads open, but the walk "
                    f"groups on its two sides don't join (outside {pc.get('outside_group', rows[0].get('group', '?'))}, "
                    f"inside {pc.get('inside_group', '?')}); flags read: {_flags_text(pc)}; tried: {tried}")
            done_all = (last_step >= (2 if cavern else 3) and since is not None and since >= step_ticks
                        and not (cavern and last_step == 2 and rec.get("ok") is False))
            own = rec.get("ok") is False and "player's own" in str(rec.get("done") or "")
            if done_all and cavern:
                ask_player(notes, f"{head}. Every step is tried, and the AI digs no way in from a cavern (it would "
                                  "open the fort to the cavern): the AI can do no more for them; it keeps the "
                                  "caverns watched and lets them in the moment the way joins again")
            elif done_all or own:
                notes.append(f"{head}. " + ("It is the player's own gate (the AI doesn't take it down): "
                                            if own else "Every step is tried: ")
                             + "the AI digs them a way in instead")
            else:
                notes.append(f"{head}. DF's walk map holds an open {kind} shut: the AI tries each step in turn"
                             + (" (on a cavern's way, step 2 while the caverns are safe; never taken down)"
                                if cavern else ", then digs them a way in if they're still out"))
    return acting


def gate_exhausted(s: dict, memory, cfg: dict) -> set:
    """(merge32) Piece ids (as text) whose three unstick steps are all tried
    (the last `gate_stuck_step_hours` ago or more) and which still hold
    citizens out: their stranded go to the way in, not back to step 1."""
    now = abs_tick(s)
    step_ticks = int(cfg.get("gate_stuck_step_hours", 6)) * (TICKS_PER_DAY // 24)
    out = set()
    for pid, rec in _d(getattr(memory, "gate_unstick", None)).items():
        rec = _d(rec)
        t = rec.get("tick")
        if ((rec.get("step") or 0) >= (2 if rec.get("cavern") else 3) and isinstance(t, int)
                and now - t >= step_ticks):
            out.add(str(pid))
    return out


def _way_in_doing(s: dict, memory, second: bool = True) -> str:
    """(0.105.32) A way in being dug (the report's projects), as words, or ''.
    (fix33) second=False (the stranded's emergency way in): the second way to
    the surface (summary.second, or memory.second_way's project) doesn't count:
    a slow second way never holds the way in for dwarves cut off."""
    ids = {v.get("project_id") for v in _d(getattr(memory, "way_in", None)).values()
           if isinstance(v, dict) and v.get("project_id") is not None}
    sid = _d(getattr(memory, "second_way", None)).get("project_id")
    for p in _l(_d(s.get("projects")).get("open")):
        if not isinstance(p, dict):
            continue
        if not second and (_d(p.get("summary")).get("second") or (sid is not None and p.get("id") == sid)):
            continue
        if p.get("kind") in WAY_IN_KINDS or (p.get("id") in ids and p.get("id") is not None):
            return f"project #{p.get('id')}, {p.get('phase') or 'under way'}"
    return ""


def _way_in_area(memory, x: int, y: int, z: int, cfg: dict) -> list:
    """(merge32 review) The way-in records (spot text, record) in the area
    of (x, y, z): within `way_in_area_tiles` across and 10 levels."""
    area = int(cfg.get("way_in_area_tiles", 20))
    out = []
    for sp, v in _d(getattr(memory, "way_in", None)).items():
        try:
            vx, vy, vz = (int(c) for c in str(sp).split(","))
        except ValueError:
            continue
        v = _d(v)
        if isinstance(v.get("tick"), int) and max(abs(vx - x), abs(vy - y)) <= area and abs(vz - z) <= 10:
            out.append((sp, v))
    return out


def player_gate_row(r: dict) -> bool:
    """(v35 fix) A citizen shut out by a gate the AI didn't shut (the player's
    raised bridge, lever or locked door): the AI never opens the player's gate
    (open_entrance refuses it too); they count as having no way in, and a
    stair is dug for them (_way_in_rule)."""
    return (isinstance(r, dict) and not r.get("by_ai") and r.get("cause") in ("gate_shut", "lockdown"))


def _way_in_rule(s: dict, memory, cfg: dict, proposals: list, notes: list, off: int = 0,
                 status: dict | None = None) -> str:
    """(0.105.32) Citizens cut off with no gate to blame (no split explains
    them), out `way_in_after_days` or more, at least `way_in_min_stranded`,
    not in a cavern, no enemy near: dig_way_in at their spot (the median of
    where they stand); never while one is being dug, nor while enemies can
    reach the dwarves or the watcher is armed; one dwarf alone after
    `way_in_single_days`; refused, again in that area after 1, 2, 4... days,
    `way_in_max_refusals` at most; one dug there and they're still out: no
    more there (merge32 review). The words for it when one is proposed, else
    ''. (0.105.35) status: filled with why none is dug yet ("when": what the
    AI waits for) or ("kept": the AI can do no more there), for _stranded_rule's
    line; refused `way_in_max_refusals` times, the AI goes on trying every
    8 days (it never stops for the player)."""
    status = status if isinstance(status, dict) else {}
    ent = _d(s.get("entrances"))
    done = gate_exhausted(s, memory, cfg)
    explained, given_up = set(), set()
    for pid, rs in stuck_rows(s).items():
        for r in rs:
            (given_up if str(pid) in done else explained).add(id(r))
    after = int(cfg.get("way_in_after_days", 2)) * TICKS_PER_DAY
    rows = [r for r in _l(ent.get("stranded")) if isinstance(r, dict) and id(r) not in explained
            and (id(r) in given_up or ((r.get("cause") == "no_path" or player_gate_row(r))
                                       and (r.get("out_ticks") or 0) >= after))
            and not r.get("in_cavern")
            and all(isinstance(r.get(k), int) for k in ("x", "y", "z"))]
    if len(rows) < max(1, int(cfg.get("way_in_min_stranded", 1))):
        status["when"] = (f"once they've been out {int(cfg.get('way_in_after_days', 2))} day(s) "
                          "(they may find their own way)")
        return ""
    near_d = cfg.get("stranded_danger_near", 30)
    if any(_row_danger(r) is not None and _row_danger(r) <= near_d for r in rows):
        status["when"] = "once the enemy near them is gone"
        return ""                         # _stranded_rule says the enemy is near
    # (merge32 review) one dwarf alone (a ledge, a tree) waits longer: they
    # may still find their own way
    if len(rows) == 1 and (rows[0].get("out_ticks") or 0) < int(cfg.get("way_in_single_days", 3)) * TICKS_PER_DAY \
            and id(rows[0]) not in given_up:
        status["when"] = (f"once they've been out {int(cfg.get('way_in_single_days', 3))} days "
                          "(one dwarf alone may find their own way)")
        return ""
    # (merge32 review) not during a siege: a new hole in the fort lets them in
    reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
    if reach > 0 or ent.get("armed"):
        notes.append(f"{len(rows)} citizen(s) cut off outside, but "
                     + (f"{reach} enemy(ies) can reach the dwarves" if reach else "the gate watcher is armed")
                     + ": no way in is dug until that is over")
        status["when"] = "once the siege is over (a new hole would let the enemy in)"
        return ""
    if _way_in_doing(s, memory, second=False):
        return ""
    import statistics
    x, y, z = (int(statistics.median_low([r[k] for r in rows])) for k in ("x", "y", "z"))
    now = abs_tick(s)
    if not isinstance(getattr(memory, "way_in", None), dict):
        memory.way_in = {}
    open_ids = {p.get("id") for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)}
    refused, last_refused = 0, None
    for sp, v in _way_in_area(memory, x, y, z, cfg):
        if v.get("ok") is False:
            refused = max(refused, int(v.get("refusals") or 1))
            last_refused = max(last_refused or v["tick"], v["tick"])
        elif v.get("ok") is True:
            if v.get("project_id") in open_ids or 0 <= now - v["tick"] < TICKS_PER_DAY:
                status["when"] = "(a stair is being dug)"
                return ""                 # being dug (or not in the report yet)
            # (0.105.36, X1) how it closed (the registry, as _second_way_rule
            # reads it): cancelled (the game's cancelled tiles, a cancel_project)
            # is not dug: booked as a refusal there, so the back-off digs again
            phase = next((rp.get("phase") for rp in _l(s.get("registry"))
                          if isinstance(rp, dict) and rp.get("id") is not None
                          and rp.get("id") == v.get("project_id")), None)
            if phase == "cancelled":
                n = int(v.get("refusals") or 0) + 1
                memory.way_in[sp] = {"tick": now, "ok": False, "project_id": v.get("project_id"),
                                     "refusals": n, "why": f"the way in (project #{v.get('project_id')}) was cancelled"}
                refused = max(refused, n)
                last_refused = max(last_refused or now, now)
                continue
            # (merge32 review) one dug here and they're still out: no more
            # digging here (the next would fail the same way); the player's
            status["kept"] = (f"a way in was already dug near x{x} y{y} elevation {z + off} and they are still "
                              "cut off there: a second would fail the same way, so the AI digs no more there "
                              "(it digs again if they move elsewhere, and keeps its own gates open for them)")
            return ""
    # (merge32 review) refused: again after 1, 2, 4, 8 days; (0.105.35) after
    # `way_in_max_refusals` every 8 days, said (never left to the player)
    if refused and last_refused is not None and 0 <= now - last_refused < min(8, 2 ** (refused - 1)) * TICKS_PER_DAY:
        why_r = next((str(_d(v).get("why") or "") for _sp, v in _way_in_area(memory, x, y, z, cfg)
                      if _d(v).get("ok") is False and _d(v).get("why")), "")
        left = min(8, 2 ** (refused - 1)) - (now - last_refused) // TICKS_PER_DAY
        status["when"] = (f"again in {max(1, left)} day(s) (the game refused it {refused} time(s)"
                          + (f": {why_r[:100]}" if why_r else "") + ")")
        return ""
    days = max(int(r.get("out_days") or 0) for r in rows)
    blame = ("behind a gate the AI didn't shut (the player's, left as it is)" if any(player_gate_row(r) for r in rows)
             else "with no gate to blame")
    proposals.append(Proposal("way_in", {"type": "dig_way_in", "x": x, "y": y, "z": z},
                              f"{len(rows)} citizen(s) cut off outside for {days} day(s) {blame} "
                              f"({', '.join(str(r.get('name') or 'a dwarf') for r in rows[:3])}): dig them a stair "
                              f"in from where they stand (x{x} y{y} elevation {z + off})", -1))
    return f"a stair dug in at x{x} y{y} elevation {z + off}"


def note_gate_stuck(p, r: dict, state: dict, memory, now: int) -> None:
    """(0.105.32) After unstick_gate or dig_way_in: the step tried and its
    answer (the next step waits on it); the entrances mapped again so the
    split is read anew."""
    a = _d(getattr(p, "action", None))
    t = a.get("type")
    r = _d(r)
    if t == "unstick_gate" and a.get("id") is not None:
        if not isinstance(getattr(memory, "gate_unstick", None), dict):
            memory.gate_unstick = {}
        rec = dict(_d(memory.gate_unstick.get(str(a["id"]))))
        step = a.get("step") if isinstance(a.get("step"), int) else 1
        rec.update(step=step, tick=now, ok=r.get("ok"), split_after=r.get("split_after"),
                   done=str(r.get("done") or r.get("error") or "")[:160])
        if r.get("cavern"):
            rec["cavern"] = True                 # (merge32 review) a cavern's way: no step 2 or 3 again
        if step == 1:
            rec["prevent"] = now
            rec["prevent_n"] = int(rec.get("prevent_n") or 0) + 1      # (0.105.48, K2) the back-off's count
        memory.gate_unstick[str(a["id"])] = rec
        if r.get("ok") is not False:
            memory.rescan_entrances = True
    elif t == "dig_way_in" and a.get("second") is True:
        # (0.105.33) the second way to the surface: tried (ok or refused); the
        # next try waits `second_way_retry_days`
        sw = dict(_d(getattr(memory, "second_way", None)))
        sw.update(tick=now, ok=r.get("ok"), project_id=r.get("project_id"),
                  why=str(r.get("why") or r.get("error") or "")[:160])
        sw.pop("rescanned", None)
        sw.pop("closed_phase", None)             # (fix33) the new try's own
        memory.second_way = sw
    elif t == "dig_way_in" and all(isinstance(a.get(k), int) for k in ("x", "y", "z")):
        if not isinstance(getattr(memory, "way_in", None), dict):
            memory.way_in = {}
        # (merge32 review) refusals counted over the area (the back-off)
        before = _way_in_area(memory, a["x"], a["y"], a["z"], PLANNER_CONFIG)
        n = max([int(_d(v).get("refusals") or 0) for _sp, v in before] + [0])
        rec = {"tick": now, "ok": r.get("ok"), "project_id": r.get("project_id"),
               "why": str(r.get("why") or r.get("error") or "")[:160]}
        if r.get("ok") is False:
            rec["refusals"] = n + 1
        elif n:
            rec["refusals"] = n               # (0.105.36) kept: a cancel then backs off further
        for sp, _v in before:
            if _d(_v).get("ok") is False:
                del memory.way_in[sp]             # the area's count is the new record's
        memory.way_in[f"{a['x']},{a['y']},{a['z']}"] = rec
        if r.get("ok") is True:
            memory.rescan_entrances = True    # the new stair is an entrance
        # (kept while anyone is cut off: note_gate_stuck_cycle forgets them once nobody is)
        for k in [k for k, v in memory.way_in.items()
                  if not isinstance(_d(v).get("tick"), int) or now < v["tick"]]:
            del memory.way_in[k]


def note_gate_stuck_cycle(s: dict, memory) -> None:
    """(0.105.32) A piece no longer split and shutting nobody out: its
    steps forgotten (the day's prevention mark kept, so a split that comes
    and goes isn't stepped every scan)."""
    ent = _d(s.get("entrances"))
    # (merge32 review) nobody cut off any more: the way-in records (their
    # back-off, the "dug here already") forgotten
    if (ent.get("scanned") and isinstance(getattr(memory, "way_in", None), dict) and memory.way_in
            and not [r for r in _l(ent.get("stranded")) if isinstance(r, dict)]):
        memory.way_in = {}
    if not isinstance(getattr(memory, "gate_unstick", None), dict) or not memory.gate_unstick:
        return
    if not ent.get("scanned"):
        return
    live = {str(k) for k in split_pieces(s)} | {str(k) for k in stuck_rows(s)}
    now = abs_tick(s)
    for k in list(memory.gate_unstick):
        if k in live:
            continue
        prev = _d(memory.gate_unstick[k]).get("prevent")
        if isinstance(prev, int) and 0 <= now - prev < TICKS_PER_DAY:
            memory.gate_unstick[k] = {"prevent": prev, "prevent_n": _d(memory.gate_unstick[k]).get("prevent_n")}
        else:
            del memory.gate_unstick[k]


# (0.105.33) E (8 Nov) had one way in, the founding stair under a hatch: when
# DF's walk map held that hatch shut, everyone outside was cut off and 64 died
# of thirst. A fort of `second_way_min_citizens` or more with one surface
# entrance digs a second one by design (dig_way_in second = true), in peace.
def note_second_way(s: dict, memory) -> None:
    """(0.105.33) Citizens ever stranded (cut off with no way back in, or by a
    gate the game holds shut): remembered for good. The Hermit hold then
    gets its second way in too. Two surface entrances seen: done for good."""
    if memory is None:
        return
    after = int(PLANNER_CONFIG.get("stranded_after_ticks", 200))
    for r in _l(_d(s.get("entrances")).get("stranded")):
        if (isinstance(r, dict) and (r.get("out_ticks") or 0) >= after
                and (r.get("cause") in ("no_path", "gate_stuck") or r.get("stuck_gate") is not None)):
            sw = dict(_d(getattr(memory, "second_way", None)))
            if not sw.get("stranded_ever"):
                sw["stranded_ever"] = abs_tick(s)
                memory.second_way = sw
            break
    # two ways to the surface seen (an old map of the entrances counts): never again
    if len(_surface_entrances(s)) >= 2 and not _d(getattr(memory, "second_way", None)).get("done"):
        sw = dict(_d(getattr(memory, "second_way", None)))
        sw["done"] = abs_tick(s)
        memory.second_way = sw


def _surface_entrances(s: dict) -> list:
    return [e for e in _l(_d(s.get("entrances")).get("entrances"))
            if isinstance(e, dict) and e.get("kind") == "surface"]


def _second_way_rule(s: dict, memory, cfg: dict, traits: dict, proposals: list, notes: list,
                     rules_: dict | None = None) -> None:
    """(0.105.33) A second way to the surface by design: a fort of
    `second_way_min_citizens` (30) or more with exactly one surface entrance,
    no enemy that can reach the dwarves, the watcher not armed and no way in
    being dug: dig_way_in {second: true} (the bridge picks open ground under
    the sky 15-40 tiles from the entrance). Not for the Hermit hold's
    character (hidden_hold or winding_ways, or Outsiders at
    `second_way_hermit_outsiders` or lower) unless citizens were ever
    stranded. Refused: again after `second_way_retry_days`; never again once
    a second surface entrance exists. (fix33) Only while the Rules let the
    AI close an entrance (build_gate_doors or fortify_entrances): a new hole
    nothing closes is the player's to make. One dug (its project done) and
    the scan still sees one surface entrance: no more, said (0.105.35)."""
    import customs
    sw = dict(_d(getattr(memory, "second_way", None)))
    if sw.get("done") or sw.get("dug_unseen"):
        return
    surf = _surface_entrances(s)
    if len(surf) >= 2:
        sw["done"] = abs_tick(s)
        memory.second_way = sw
        return
    if len(surf) != 1:
        return
    dw = _d(s.get("dwarves"))
    if int(dw.get("total") or 0) < int(cfg.get("second_way_min_citizens", 30)):
        return
    traits = traits or {}
    try:
        outsiders = float(traits.get("outsiders", 0) or 0)
    except (TypeError, ValueError):
        outsiders = 0.0
    hermit = (customs.has(traits, "hidden_hold") or customs.has(traits, "winding_ways")
              or outsiders <= int(cfg.get("second_way_hermit_outsiders", -50)))
    if hermit and not sw.get("stranded_ever"):
        return
    ent = _d(s.get("entrances"))
    reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
    if reach > 0 or ent.get("armed"):
        return                              # a new hole in the fort in a siege lets them in
    if _way_in_doing(s, memory):
        return
    now = abs_tick(s)
    t = sw.get("tick")
    if isinstance(t, int) and 0 <= now - t < int(cfg.get("second_way_retry_days", 60)) * TICKS_PER_DAY:
        if sw.get("ok") is True and not sw.get("rescanned"):
            open_ids = {p.get("id") for p in _l(_d(s.get("projects")).get("open")) if isinstance(p, dict)}
            if sw.get("project_id") not in open_ids and now - t >= TICKS_PER_DAY:
                # dug (the project closed): the new stair is mapped as an entrance
                memory.rescan_entrances = True
                sw["rescanned"] = now
                # (fix33) how it closed (the registry): cancelled is not dug
                for rp in _l(s.get("registry")):
                    if isinstance(rp, dict) and rp.get("id") == sw.get("project_id") and rp.get("id") is not None:
                        sw["closed_phase"] = rp.get("phase")
                memory.second_way = sw
        return
    if sw.get("ok") is True and sw.get("rescanned") and sw.get("closed_phase") != "cancelled":
        # (fix33) dug, mapped again, and still one surface entrance: the new
        # stair comes out where the scan counts it inside (a courtyard): no
        # more digging, said once
        sw["dug_unseen"] = now
        memory.second_way = sw
        # (0.105.35) the AI's own decision, said: no third hole in the fort;
        # anyone cut off gets the emergency way in (_way_in_rule)
        notes.append(f"a second way to the surface was dug (project #{sw.get('project_id')}), but the map of "
                     "the entrances still shows one surface entrance (it may come out in a walled courtyard): "
                     "the AI digs no more second ways (each is a new hole in the fort); anyone cut off gets a "
                     "way dug in from where they stand")
        return
    rules_ = rules_ if isinstance(rules_, dict) else player_rules(s)
    if not (rules_.get("build_gate_doors", True) or rules_.get("fortify_entrances", True)):
        notes.append("one way to the surface, but doors and walls on entrances are both off on the Rules tab: "
                     "the AI digs no second way (it could put nothing on it to close it)")
        return
    e = surf[0]
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    why = ("citizens were stranded outside once; " if hermit else "")
    act = {"type": "dig_way_in", "second": True}
    # (0.105.47) the Garden fort's field customs: the second way comes up by
    # its fields above ground (a stair from the field hall and kitchens to them)
    import fields
    f = fields.current() if customs.has(traits, "field_hall") else None
    toward = ""
    if f and isinstance(f.get("x"), int) and isinstance(f.get("y"), int):
        act["near"] = {"x": f["x"], "y": f["y"]}
        toward = f", as near the fields above ground (x{f['x']} y{f['y']}) as it may"
    proposals.append(Proposal("second_way", act,
                              f"{why}one way to the surface (x{e.get('x')} y{e.get('y')} elevation "
                              f"{(e.get('z') or 0) + off}): dig a second, 15-40 tiles off{toward}",
                              5 if sw.get("stranded_ever") else 9))   # (0.105.36, X1) not behind routine work then


def _stranded_relook(memory, p, s: dict, cfg: dict) -> None:
    """(0.105.36, X1) open_entrance answered waiting (an enemy near the gate,
    a great danger in sight, the cavern seal): looked at again after the
    rule's own cooldown (`stranded_cooldown_ticks`), not the 2 days every
    waiting answer gets: citizens shut out go thirsty. A back-off (n > 0)
    is kept."""
    refs = getattr(memory, "refusals", None) if memory is not None else None
    if not isinstance(refs, dict):
        return
    key = refusal_key(p)
    r = _d(refs.get(key))
    at, now = r.get("at"), abs_tick(s)
    if (r and not int(r.get("n") or 0) and isinstance(at, int)
            and not 0 <= now - at < int(cfg.get("stranded_cooldown_ticks", 300))):
        refs.pop(key, None)


def _stranded_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None, any_reach=None) -> bool:
    """(0.105.26) E (3-5 Nov): 8 citizens shut outside after a surface fire
    died there. A gate the AI shut (the watcher's lockdown or another) with
    no enemy near it or them: the gates opened (open_gates). No way in at all
    (a collapse, a fire): put to the player with their names and where. Held
    while an enemy is near. True when the gates are being opened or a gate
    unstuck (the gate rule then doesn't arm them in the same cycle).
    (0.105.32) an open gate DF's walk map holds shut (_gate_stuck_rule) and a
    way dug in for the cut off (_way_in_rule) go first.
    (0.105.33) open_gates opens every gate the watcher shut: never while an
    enemy can reach the dwarves or is held off at a gate (put to the player),
    so the return is True only when nothing threatens; an unstick under way
    doesn't hold arm_gates while a threat can reach the dwarves."""
    ent = _d(s.get("entrances"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    if any_reach is None:
        any_reach = (bool(reachable_threats(s, _d(_d(s.get("settings")).get("traits")), cfg))
                     if isinstance(s.get("others_on_map"), dict) else False)
    reach_n = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
    held = held_off_threats(s)
    unsticking = _gate_stuck_rule(s, memory, cfg, proposals, notes, off) if memory is not None else False
    if any_reach:
        unsticking = False                  # (0.105.33) the watcher arms all the same
    way_status: dict = {}
    way_new = _way_in_rule(s, memory, cfg, proposals, notes, off, way_status) if memory is not None else ""
    stuck = {id(r) for rs in stuck_rows(s).values() for r in rs}      # theirs is the gate's line, not "no way in"
    rows = [r for r in _l(ent.get("stranded")) if isinstance(r, dict)
            and (r.get("out_ticks") or 0) >= cfg.get("stranded_after_ticks", 200)
            and id(r) not in stuck]
    if not rows:
        return unsticking
    near_d = cfg.get("stranded_danger_near", 30)

    def where(r):
        return f"{r.get('name') or 'a dwarf'} (x{r.get('x')} y{r.get('y')} elevation {(r.get('z') or 0) + off})"

    def days(rs):
        d = max(int(r.get("out_days") or 0) for r in rs)
        return f"{d} day(s)" if d else f"{max(int(r.get('out_ticks') or 0) for r in rs) // 50} hour(s)"

    danger = _row_danger

    # (0.105.36, X1) an enemy near one of them no longer holds every entrance:
    # a gate the AI shut is judged per entrance in open_one, at the gates'
    # close distance (gate_close_tiles); the `stranded_danger_near` hold is
    # for the rows themselves (a way dug in: _way_in_rule; open_gates, which
    # disarms the watcher, gives way to open_one below)
    hot = [r for r in rows if danger(r) is not None and danger(r) <= near_d]
    hot_rest = [r for r in hot if not (r.get("by_ai") and r.get("cause") in ("gate_shut", "lockdown")
                                       and isinstance(_d(r.get("entrance")).get("id"), int))]
    if hot_rest:
        notes.append(f"{len(hot_rest)} citizen(s) can't get back into the fort "
                     f"({', '.join(where(r) for r in hot_rest[:3])}), but an enemy is "
                     f"{min(danger(r) for r in hot_rest)} tiles away: the AI leaves them as they are for now "
                     "(no way dug in, no gate the AI didn't shut touched) and looks again each cycle")
        rest = {id(r) for r in hot_rest}
        rows = [r for r in rows if id(r) not in rest]
        if not rows:
            return unsticking
    cave = [r for r in rows if r.get("in_cavern")]
    gate = [r for r in rows if not r.get("in_cavern") and r.get("cause") in ("gate_shut", "lockdown")]
    ai_gate = [r for r in gate if r.get("by_ai")]
    other_gate = [r for r in gate if not r.get("by_ai")]
    nopath = [r for r in rows if not r.get("in_cavern") and r.get("cause") == "no_path"]
    # (0.105.35) down in the caverns behind a shut gate: let in by their
    # entrance (open_entrance cavern_ok) as the shut-out on the surface are
    cave_shut = [r for r in cave if r.get("cause") in ("gate_shut", "lockdown")]
    cave = [r for r in cave if r not in cave_shut]
    opening = unsticking
    # (0.105.26 seal fix) not a cavern-side entrance while a forgotten beast or
    # other great danger is in the caverns (open_gates would open the way it
    # comes up by); (0.105.35) said as what the AI does: kept shut, opened by
    # the AI once the caverns are read and the danger is gone
    from planner_threats import cavern_great, deep_read
    great = cavern_great(s)
    deep_ok = deep_read(s)              # (0.105.33) the caverns unread: no beast seen is no beast gone
    close_d = int(cfg.get("gate_close_tiles", 12))
    # (0.105.47, R2 item 7) one ordinary enemy held off at the gates: kept
    # shut while it is within `one_enemy_gate_tiles`, the citizens let in by
    # another gate far from it (planner_holdfast)
    from planner_holdfast import one_enemy_hold, other_gate as far_gate
    # (open_entrance keeps the watcher armed, which shuts it again at the
    # gates' close distance: each gate is judged at that; the hold's own
    # distance is for open_gates, which disarms it, and for the other gate)
    hold = one_enemy_hold(s, cfg, memory) if (any_reach or reach_n > 0) else None
    alt_done: set = set()

    def cavern_side(r):
        return bool(r.get("in_cavern")) or _d(r.get("entrance")).get("kind") == "cavern"

    if great or not deep_ok:
        # (v35 fix) only the AI's own gates wait for that: the player's are
        # never opened (a way is dug in for them below)
        cave_gate = [r for r in ai_gate + cave_shut if cavern_side(r) and r.get("by_ai")]
        ai_gate = [r for r in ai_gate if r not in cave_gate]
        cave_shut = [r for r in cave_shut if not r.get("by_ai")]
        if cave_gate:
            e = _d(cave_gate[0].get("entrance"))
            g0 = _d(great[0]) if great else {}
            what = (f"{g0.get('name') or 'a great beast'} ({g0.get('kind') or 'great danger'}) is in the caverns"
                    if great else "the caverns couldn't be read this cycle (a forgotten beast may be down there)")
            notes.append(f"{len(cave_gate)} citizen(s) shut outside for {days(cave_gate)} at the cavern "
                         f"entrance at x{e.get('x')} y{e.get('y')} elevation {(e.get('z') or 0) + off} "
                         f"({', '.join(where(r) for r in cave_gate[:3])}), but {what}: the AI keeps that way "
                         "shut and opens it for them once the caverns are read and hold no great danger")

    def open_one(rs_all, why_tail):
        """open_entrance for each entrance of rs_all (cavern_ok on a cavern's,
        only reached here with the caverns read safe), unless an enemy is
        within the gates' close distance of it: then kept shut, said."""
        nonlocal opening
        by_ent = {}
        loose = []
        for r in rs_all:
            e = _d(r.get("entrance"))
            if isinstance(e.get("id"), int):
                by_ent.setdefault(e["id"], (e, []))[1].append(r)
            else:
                loose.append(r)
        opening_ids = set()
        for eid, (e, rs) in by_ent.items():
            gd0 = [r.get("gate_danger") if isinstance(r.get("gate_danger"), (int, float)) else r.get("danger_near")
                   for r in rs]
            gd0 = [d for d in gd0 if isinstance(d, (int, float))]
            if not gd0 or min(gd0) > close_d:
                opening_ids.add(eid)
        for eid, (e, rs) in by_ent.items():
            # (0.105.36, X1) the enemy's distance from this gate (from the
            # citizen when the gate's isn't read)
            gd = [r.get("gate_danger") if isinstance(r.get("gate_danger"), (int, float)) else r.get("danger_near")
                  for r in rs]
            gd = [d for d in gd if isinstance(d, (int, float))]
            near = min(gd) if gd else None
            at = f"x{e.get('x')} y{e.get('y')} elevation {(e.get('z') or 0) + off}"
            if near is not None and near <= close_d:
                alt = far_gate(s, hold, eid) if hold else None
                if alt is not None and alt["id"] not in opening_ids and alt["id"] not in alt_done:
                    alt_done.add(alt["id"])
                    # (0.105.47) let in by another gate, far from the enemy
                    proposals.append(Proposal("stranded", {"type": "open_entrance", "id": alt["id"]},
                                              f"{len(rs)} citizen(s) shut outside for {days(rs)} at the gate at {at} "
                                              f"({', '.join(where(r) for r in rs[:3])}), an enemy {near} tiles from "
                                              f"it: open the gate at x{alt.get('x')} y{alt.get('y')} instead, far "
                                              "from it (the watcher stays armed)", 0))
                    continue
                notes.append(f"{len(rs)} citizen(s) shut outside for {days(rs)} at the gate at {at} "
                             f"({', '.join(where(r) for r in rs[:3])}), an enemy {near} tiles from it: the AI keeps "
                             "it shut and opens it for them once the enemy is farther off")
                continue
            act = {"type": "open_entrance", "id": eid}
            if e.get("kind") == "cavern" or any(r.get("in_cavern") for r in rs):
                act["cavern_ok"] = True
            _stranded_relook(memory, Proposal("stranded", act, "", 0), s, cfg)
            proposals.append(Proposal("stranded", act,
                                      f"{len(rs)} citizen(s) shut outside for {days(rs)} at the gate at {at} "
                                      f"({', '.join(where(r) for r in rs[:3])}){why_tail}", 0))
            # the watcher may still arm this cycle while an enemy can reach the
            # dwarves (open_entrance doesn't disarm it, and it shuts the gate
            # again if danger comes within its close distance)
            if not (any_reach or reach_n > 0):
                opening = True
        return loose

    # (0.105.33 fix) held off means a siege at the gates: invaders, a great
    # danger, or a held-off threat near a gate the AI shut. A wild animal far
    # out on the surface doesn't keep the AI's own lockdown shut on citizens
    # (main let them in; E 3-5 Nov left them out to die of thirst).
    shut_ents = [e for e in _l(ent.get("entrances")) if isinstance(e, dict) and e.get("closed")]

    def _near_shut(t):
        pos = _d(t.get("pos"))
        if not all(isinstance(pos.get(k), (int, float)) for k in ("x", "y", "z")):
            dn = t.get("distance_to_nearest_dwarf")      # unplaced: how far from any dwarf
            return not isinstance(dn, (int, float)) or dn <= near_d
        for e in shut_ents:
            if not all(isinstance(e.get(k), (int, float)) for k in ("x", "y", "z")):
                continue
            d = (max(abs(pos["x"] - e["x"]), abs(pos["y"] - e["y"])) - int(e.get("width") or 1)
                 + 3 * abs(pos["z"] - e["z"]))
            if d <= near_d:
                return True
        return False
    held = [t for t in held if t.get("invader") or t.get("great_danger") or _near_shut(t)]
    siege_on = bool(any_reach or reach_n > 0 or held)
    if ai_gate and (siege_on or any(r in hot for r in ai_gate)):
        # (0.105.34, the player: nothing waits for them) open_gates would open
        # every gate the watcher shut and disarm it: a siege held off at
        # another gate would walk in. So only the entrance they stand at
        # opens (open_entrance), while no enemy is within the gates' close
        # distance of it; the watcher stays armed and shuts it again if
        # danger comes. Closer: kept shut, said, tried again each cycle.
        # (0.105.36, X1) an enemy within `stranded_danger_near` of them, no
        # siege: the same (open_gates would disarm the watcher with it near)
        open_one(ai_gate, (" while enemies are about elsewhere" if siege_on else " with an enemy about")
                 + ": open that gate alone to let them in (the watcher stays armed)")
        ai_gate = []
    if ai_gate:
        lock = any(r.get("cause") == "lockdown" for r in ai_gate)
        e = _d(ai_gate[0].get("entrance"))
        proposals.append(Proposal("stranded", {"type": "open_gates"},
                                  f"{len(ai_gate)} citizen(s) shut outside for {days(ai_gate)} by "
                                  + ("the lockdown" if lock else "a shut gate")
                                  + f" at x{e.get('x')} y{e.get('y')} ({', '.join(where(r) for r in ai_gate[:3])}) "
                                  "and no enemy near: open the gates to let them in", 0))
        opening = True
    # (v35 fix, the player: the player's things stay the player's) a gate shut
    # not by the AI (a raised bridge, the player's lever, a locked door): the
    # AI never opens it (no lever of the player's pulled, no door unlocked);
    # it digs them a way in instead (_way_in_rule), said as a plain note
    player_cave = [r for r in cave_shut if not r.get("by_ai")]
    cave_shut = [r for r in cave_shut if r.get("by_ai")]
    if other_gate:
        e = _d(other_gate[0].get("entrance"))
        at = (f" at x{e.get('x')} y{e.get('y')} elevation {(e.get('z') or 0) + off}"
              if e.get("x") is not None else "")
        lever = (f" (on the player's lever {e.get('shared_lever')}, which works "
                 f"{e.get('works_other') or 'other'} other thing(s) too)" if e.get("shared_lever") is not None else "")
        head = (f"{len(other_gate)} citizen(s) shut outside for {days(other_gate)} by a gate the AI didn't shut"
                f"{at}{lever} ({', '.join(where(r) for r in other_gate[:3])}): the gate is the player's, so the AI "
                "leaves it as it is")
        way = way_new or (_way_in_doing(s, memory, second=False) if memory is not None else "")
        if way:
            notes.append(f"{head} and digs them a way in ({way})")
        elif way_status.get("kept"):
            notes.append(f"{head}; {way_status['kept']}")
        else:
            notes.append(f"{head} and digs them a stair in " + (way_status.get("when") or "when it can"))
    if player_cave:
        notes.append(f"{len(player_cave)} citizen(s) down in the caverns shut out for {days(player_cave)} by a gate "
                     f"the AI didn't shut ({', '.join(where(r) for r in player_cave[:3])}): the gate is the "
                     "player's, so the AI leaves it as it is, and it digs no way in from a cavern (it would open "
                     "the fort to the cavern); it looks again each cycle")
    # the AI's own gate on a cavern's way, the caverns read safe: that entrance
    # opened by the AI (open_entrance cavern_ok: only that entrance's gates,
    # refused with an enemy within 12 tiles of it, a great danger in sight or
    # the cavern seal on it)
    loose = open_one(cave_shut,
                     ": its gate was shut by the AI and the caverns hold no great danger: open that "
                     "entrance to let them in")
    if loose:
        notes.append(f"{len(loose)} citizen(s) shut outside for {days(loose)} "
                     f"({', '.join(where(r) for r in loose[:4])}) by a gate the AI shut, and the "
                     "map of the entrances doesn't say which: the AI maps the entrances again and opens "
                     "it once it knows it")
        if memory is not None:
            memory.rescan_entrances = True
    if nopath:
        way = way_new or (_way_in_doing(s, memory, second=False) if memory is not None else "")
        head = (f"{len(nopath)} citizen(s) stranded outside for {days(nopath)} with no way back in "
                f"(a collapse or a fire?): {', '.join(where(r) for r in nopath[:5])}"
                + (f" and {len(nopath) - 5} more" if len(nopath) > 5 else ""))
        if way:
            notes.append(f"{head}: the AI digs them a way in ({way})")
        elif way_status.get("kept"):
            # (0.105.35) the AI can do no more there: said, with what it does meanwhile
            ask_player(notes, f"{head}: {way_status['kept']}")
        else:
            notes.append(f"{head}: the AI digs them a stair in " + (way_status.get("when") or "when it can"))
    if cave:
        # (0.105.47) under a cavern well: its own rescue lets them up (planner_wellsafe)
        from planner_wellsafe import well_rescue_covers
        cave = [r for r in cave if not well_rescue_covers(s, r, cfg)]
    if cave:
        # (0.105.35) no gate to open: no way in is dug from a cavern (the
        # bridge refuses it: a hole from the cavern into the fort)
        ask_player(notes, f"{len(cave)} citizen(s) down in the caverns can't get back up for {days(cave)} "
                          f"({', '.join(where(r) for r in cave[:4])}): the way up is gone, and the AI digs no "
                          "way in from a cavern (it would open the fort to the cavern): the AI can't reach them; "
                          "it looks again each cycle and lets them in by any gate that comes to stand on their way")
    return opening
