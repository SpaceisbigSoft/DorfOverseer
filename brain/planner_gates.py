"""planner_gates: the gates and lockdowns (split out of planner_military in
0.105.25, 13c): entrances closed and opened, the gate's parts, levers and
their links, traps and the gatehouse; a lone intruder or a few ordinary
enemies, the lockdown released, the quick all-clear; pastures held while
the gates are shut; the gate guard and its dogs. planner_military re-exports
every name here."""

from __future__ import annotations

from dataclasses import field
from culture import profile_from
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_construct import _wings_rule, cavern_wall_style  # (0.105.30) wing walls, the Hermit's cavern walls

__all__ = ["_gate_rules", "_stranded_rule", "shared_lever_row", "player_gate_row", "split_pieces", "stuck_rows", "note_gate_stuck", "note_gate_stuck_cycle", "note_second_way", "_second_way_rule", "WAY_IN_KINDS", "GATE_STUCK_TRIED", "STRANDED_CONFIG", "GATE_PART_RECIPES", "GATE_PART_STUCK_DAYS", "_gate_parts_rule", "_free_gate_levers", "_lever_far_enough", "machinery_wanted", "_lever_hatches_ok", "_link_wanted", "_lever_rule", "_trap_rule", "_gatehouse_rule", "_near_spot", "lone_intruders", "few_ordinary", "few_alert_over", "few_near", "hunted_outside", "ai_gates_shut", "_Rec", "_lockdown", "lockdown_released", "lone_alert_over", "_lockdown_ids", "_lockdown_cap_why", "note_lockdown", "quick_clear", "PASTURE_ACTIONS", "_pasture_hold", "gate_invaders", "main_gate", "_gate_guard_rule", "_gate_dogs_rule"]


# (0.105.26) citizens stranded outside (lua/ai-gates.lua stranded_citizens)
STRANDED_CONFIG = {
    "stranded_after_ticks": 200,         # out this long (~4 game hours) before the rule acts
    "stranded_danger_near": 30,          # an enemy this close to them or the gate: held back
    "gate_close_tiles": 12,              # (0.105.34) an enemy this close to their gate keeps it shut for the stranded
    "stranded_cooldown_ticks": 300,
}
PLANNER_CONFIG.update({k: v for k, v in STRANDED_CONFIG.items() if k not in PLANNER_CONFIG})
STEER_PROTECTED.add("stranded")
AGENDA_THEMES["stranded"] = "bring in the dwarves shut outside"

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
AGENDA_THEMES["gate_stuck"] = "free the gate the game holds shut"
AGENDA_THEMES["way_in"] = "dig a way in for the dwarves cut off"
AGENDA_THEMES["second_way"] = "a second way to the surface"     # (0.105.33)
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
        else:
            prev = rec.get("prevent") if isinstance(rec.get("prevent"), int) else None
            days = int(cfg.get("gate_stuck_prevent_days", 1))
            if (not reach and not ent.get("armed") and (prev is None or not 0 <= now - prev < days * TICKS_PER_DAY)
                    and (since is None or since >= step_ticks)):
                step = 1
            why = (f"{name} reads open, but the game's walk map splits the way through it; nobody is shut "
                   "out yet")
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


def shared_lever_row(r: dict) -> bool:
    """(0.105.35 merge) A citizen shut out by a gate the AI didn't shut, on the
    player's own lever that also works other things (the bridge's
    `entrance.shared_lever`): the AI doesn't pull it (open_entrance refuses
    it too), so they count as having no way in (a stair is dug for them)."""
    return (isinstance(r, dict) and not r.get("by_ai") and r.get("cause") in ("gate_shut", "lockdown")
            and _d(r.get("entrance")).get("shared_lever") is not None)


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
            memory.gate_unstick[k] = {"prevent": prev}
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
    proposals.append(Proposal("second_way", {"type": "dig_way_in", "second": True},
                              f"{why}one way to the surface (x{e.get('x')} y{e.get('y')} elevation "
                              f"{(e.get('z') or 0) + off}): dig a second, 15-40 tiles off", 9))


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

    hot = [r for r in rows if danger(r) is not None and danger(r) <= near_d]
    if hot:
        notes.append(f"{len(rows)} citizen(s) can't get back into the fort ({', '.join(where(r) for r in rows[:3])}), "
                     f"but an enemy is {min(danger(r) for r in hot)} tiles away: the gates stay as they are for now")
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
        for eid, (e, rs) in by_ent.items():
            gd = [r.get("gate_danger") for r in rs if isinstance(r.get("gate_danger"), (int, float))]
            near = min(gd) if gd else None
            at = f"x{e.get('x')} y{e.get('y')} elevation {(e.get('z') or 0) + off}"
            if near is not None and near <= close_d:
                notes.append(f"{len(rs)} citizen(s) shut outside for {days(rs)} at the gate at {at} "
                             f"({', '.join(where(r) for r in rs[:3])}), an enemy {near} tiles from it: the AI keeps "
                             "it shut and opens it for them once the enemy is farther off")
                continue
            act = {"type": "open_entrance", "id": eid}
            if e.get("kind") == "cavern" or any(r.get("in_cavern") for r in rs):
                act["cavern_ok"] = True
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
    if ai_gate and siege_on:
        # (0.105.34, the player: nothing waits for them) open_gates would open
        # every gate the watcher shut and disarm it: a siege held off at
        # another gate would walk in. So only the entrance they stand at
        # opens (open_entrance), while no enemy is within the gates' close
        # distance of it; the watcher stays armed and shuts it again if
        # danger comes. Closer: kept shut, said, tried again each cycle.
        open_one(ai_gate, " while enemies are about elsewhere: open that gate alone to let them in "
                          "(the watcher stays armed)")
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
        # (0.105.35) no gate to open: no way in is dug from a cavern (the
        # bridge refuses it: a hole from the cavern into the fort)
        ask_player(notes, f"{len(cave)} citizen(s) down in the caverns can't get back up for {days(cave)} "
                          f"({', '.join(where(r) for r in cave[:4])}): the way up is gone, and the AI digs no "
                          "way in from a cavern (it would open the fort to the cavern): the AI can't reach them; "
                          "it looks again each cycle and lets them in by any gate that comes to stand on their way")
    return opening


def _gate_rules(s: dict, memory, cfg: dict, rules_: dict, any_reach: bool,
                proposals: list, notes: list, traits: dict | None = None) -> None:
    ent = _d(s.get("entrances"))
    now = abs_tick(s)
    letting_in = _stranded_rule(s, cfg, proposals, notes, memory, any_reach)   # (0.105.26; 0.105.32 memory)
    if ent.get("stranded_error"):
        # (0.105.33 merge) the stranded check failed in the game: said as the
        # watcher's failure is, not read as "nobody shut outside"
        # (0.105.35) kept: the AI can't see who is out; said with what it does meanwhile
        notes.append(f"Needs you: the check for citizens shut outside failed ({str(ent['stranded_error'])[:120]}): "
                     "the AI can't see who is left outside this cycle; it checks again next cycle and opens "
                     "the gates it shut as soon as the danger is gone")
    note_second_way(s, memory)                                           # (0.105.33)
    age = now - ent["scanned_tick"] if isinstance(ent.get("scanned_tick"), int) else None
    stale = (not ent.get("scanned") or age is None or not 0 <= age < cfg["entrance_scan_ticks"]
             or memory.rescan_entrances
             or ent.get("rescan"))           # (0.105.23) a lever linked since the scan (the bridge saw it)
    if stale:
        proposals.append(Proposal("entrances", {"type": "scan_entrances"},
                                  "map the fort's entrances and what closes them", 0 if any_reach else 5))
        if not ent.get("scanned"):
            return
        # (0.100.1, review) an old map of the entrances still knows the gates:
        # they're watched and opened from it while the new scan waits
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    es = [e for e in _l(ent.get("entrances")) if isinstance(e, dict)]
    closable = [e for e in es if _l(e.get("equipment"))]
    # (0.105.3) B (2 Nov): a lone thief inside kept the only hatch shut 2.5
    # hours at 1-3 FPS. Enemies already inside aren't kept out by a gate, and
    # a lockdown the AI held days with no new enemy (the game slow, dwarves
    # shut out) is opened: the watcher stands down until a new enemy comes
    lone = lone_intruders(s, cfg, traits, memory) if any_reach else []
    hunted = [] if lone or not any_reach else hunted_outside(s, cfg, traits, memory)    # (0.105.8)
    released = lockdown_released(memory)
    if any_reach and closable and not ent.get("armed") and rules_["gate_lever"] and (lone or released or hunted):
        notes.append(f"{len(lone)} enemy/enemies inside the fort and none outside: the gates stay open "
                     "(shut, they keep only the others out)" if lone else
                     f"only {len(hunted)} ordinary enemy/enemies outside, and a squad on them or citizens out: "
                     "the gates stay open (shut, they keep the squads in and the citizens out)" if hunted else
                     "the AI's lockdown was lifted (no new enemy for days): the gates stay open until a new one comes")
    elif any_reach and closable and not ent.get("armed") and rules_["gate_lever"] and not letting_in:
        proposals.append(Proposal("gates", {"type": "arm_gates"},
                                  f"a threat can reach the dwarves: watch the {len(closable)} gate(s); each closes "
                                  "once everyone is inside or the danger is 12 tiles away", 0))
    elif ent.get("armed") and (lone or released or hunted):
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"only {len(lone)} enemy/enemies left, inside the fort: open the gates (shut, they "
                                  "keep only the others out)" if lone else
                                  f"only {len(hunted)} ordinary enemy/enemies outside and "
                                  + (f"{int(ent.get('citizens_outside') or 0)} citizen(s) shut out"
                                     if int(ent.get("citizens_outside") or 0) else "a squad sent at them")
                                  + ": open the gates (the squads go out, the citizens come in)" if hunted else
                                  "the fort has been shut for days with no new enemy: open the gates", 0))
    elif not any_reach and ent.get("armed") and all_clear(s, memory, cfg)[0]:
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"no threat for {memory.quiet_cycles} cycles: open the gates", 1))
    elif not any_reach and ent.get("armed") and quick_clear(s, memory, cfg):
        # (0.105.3) A (2 Nov): shut on 9 citizens for a sneaker who hid again
        proposals.append(Proposal("gates", {"type": "open_gates"},
                                  f"{quick_clear(s, memory, cfg)}: open the gates", 0))
    werr = _d(ent.get("watch_error"))
    if ent.get("armed") and werr.get("error"):
        # (0.104.81, 13c) the gate watcher errors: it closes nothing.
        # (0.105.35, the player: nothing waits for them) the AI shuts the
        # gates an enemy comes within 12 tiles of itself, each cycle
        # (close_threatened_gates), while a threat can reach the dwarves
        notes.append(f"the gate watcher failed {werr.get('n', 1)} time(s) and closes no gate "
                     f"({str(werr['error'])[:120]}): "
                     + ("the AI shuts each gate an enemy comes within 12 tiles of itself, every cycle"
                        if any_reach and closable else "nothing threatens now; the AI shuts the gates itself if "
                        "an enemy comes near"))
        if any_reach and closable and not any(p.rule == "gates" for p in proposals):
            proposals.append(Proposal("gates", {"type": "close_threatened_gates"},
                                      "the gate watcher fails: shut the gates an enemy is within 12 tiles of", 0))
    # (0.105.33 merge) the gates group's report fields, said: a drawbridge that
    # waited too long for a lever that can work it (counted open now), and a
    # door or hatch on a lever shared with another gate (the watcher only
    # locks it, it doesn't pull)
    for e in es:
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        wait = e.get("lever_wait_days")
        if isinstance(wait, int) and not isinstance(wait, bool) and wait > 0 and not e.get("sealed"):
            notes.append(f"{where}: its drawbridge waited {wait} day(s) for a lever that can work it; "
                         "counted as open now")
        if e.get("lock_only") and ent.get("armed"):
            notes.append(f"{where}: its door or hatch shares a lever with another gate; the watcher only "
                         "locks it, it pulls no lever there")
    if stale:
        return                              # building gates waits for the new map
    _gate_parts_rule(s, ent, es, off, proposals, notes, memory)
    _second_way_rule(s, memory, cfg, traits or {}, proposals, notes, rules_)     # (0.105.33; fix33 rules_)
    doors_proposed = fortify_proposed = False
    open_wide: list = []
    refused: list = []
    style = profile_from(traits or {}, memory.culture)["gate"]
    for e in es:
        if e.get("sealed") or e.get("closing"):
            continue                        # closed, or walls and doors planned there are being built
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if spot in memory.gate_failures:
            when = memory.gate_failure_ticks.get(spot)
            # refusals over a stockpile in the way are retried at once: the AI
            # moves stockpiles itself now
            if "move the stockpile" in memory.gate_failures[spot]:
                when = None
            # water refused before the AI could look at water itself (bridge
            # 0.34.2): tried again at once, so it investigates
            if "liquid" in memory.gate_failures[spot] and "the AI looked" not in memory.gate_failures[spot]:
                when = None
            if isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
                refused.append((where, memory.gate_failures[spot]))
                continue
            # refused long enough ago (or before refusals were dated): try again;
            # a new refusal is dated by record()

        lever = next((lv for lv in _free_gate_levers(s) if _lever_far_enough(lv, e)), None)
        if (lever and _l(e.get("bridges_unworked"))
                and not any(memory.gate_failures.get(f"lever:{lever['id']}>{bid}")
                            for bid in _l(e.get("bridges_unworked")))):
            continue                        # a drawbridge is there: the AI gate lever is linked to it instead
        for sp, v in list(memory.gates_fortified.items()):
            if str(v).startswith("water@"):
                try:
                    when = int(str(v)[6:])
                except ValueError:
                    when = None
                if when is None or not 0 <= now - when < cfg["water_gate_recheck_ticks"]:
                    del memory.gates_fortified[sp]    # a season on: look at the water again
        built_here = _near_spot(e, memory.gates_fortified, value=True)
        if built_here and not str(built_here).startswith("water"):
            # a gate the AI built, and the entrance still open with nothing
            # being built there: after a while the gate is gone (taken down,
            # destroyed) or never closed it. 0.40's hatch over the main stair
            # vanished and the fort stood open all of y51, the AI "waiting".
            sp_built = next((sp for sp in memory.gates_fortified if _near_spot(e, [sp])), None)
            since = memory.gates_fortified_ticks.get(sp_built)
            if not isinstance(since, int):
                memory.gates_fortified_ticks[sp_built] = now        # (a record from before 0.48: count from now)
            elif now - since >= cfg["gate_gone_ticks"]:
                memory.gates_fortified.pop(sp_built, None)
                memory.gates_fortified_ticks.pop(sp_built, None)
                if sp_built in memory.gate_doors_requested:
                    memory.gate_doors_requested.remove(sp_built)
                notes.append(f"the gate the AI built at {where} doesn't close it any more (gone?): building it again")
                built_here = False
        if built_here and not (e.get("door_spots") and "doors later" in str(built_here)):
            continue                        # walled: waiting on the dwarves, then the weekly rescan
                                            # (doors that had to wait for their walls go in once they stand)
        # (0.105.30, construction 3.4) the Hermit hold walls a narrow cavern
        # opening for good (walls, no door), the doors' turn or not
        e_style = cavern_wall_style(e, traits or {}, cfg, memory, style, now) if rules_["fortify_entrances"] else style
        if e_style == "sealed":
            if not fortify_proposed:
                proposals.append(Proposal("fortify", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                      "style": "sealed"},
                                          f"{where} is {e.get('width')} wide and leads to the caverns: wall it up "
                                          "for good (a hidden hold keeps no door there)", 5))
                fortify_proposed = True
            continue
        if e.get("door_spots"):
            if rules_["build_gate_doors"] and spot not in memory.gate_doors_requested and not doors_proposed:
                proposals.append(Proposal("gate_doors", {"type": "build_gate_doors", "entrance_id": e["id"]},
                                          f"{where} has nothing to close it: put {e['door_spots']} door(s) "
                                          "across it", 5))
                doors_proposed = True
        elif (rules_["fortify_entrances"] and (e.get("width") or 0) <= cfg["fortify_max_width"]):
            if not fortify_proposed:
                # (0.105.30) the underground depot's wagon road: a 3-wide drawbridge, never doors
                st = "wagon" if e.get("deep_road") else style
                why_f = (f"{where} is the underground trade depot's wagon road: a 3-wide drawbridge across it "
                         "(wagons roll over it lowered; a door would shut them out)" if e.get("deep_road")
                         else f"{where} is {e.get('width')} wide: wall it down to a {style} gate")
                proposals.append(Proposal("fortify", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                      "style": st}, why_f, 5))
                fortify_proposed = True
        elif not (isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0):
            open_wide.append((e, where))        # (0.105.0) one a cut closes is _gate_cut_rule's (planner_army)
    if rules_["gate_lever"]:
        _lever_rule(s, memory, cfg, es, now, proposals, traits or {})
    if not any_reach and rules_["fortify_entrances"]:
        _trap_rule(s, memory, cfg, es, now, traits or {}, proposals)
        _gatehouse_rule(s, memory, cfg, es, now, traits or {}, proposals)     # (0.105.23)
        try:
            _wings_rule(s, memory, cfg, es, now, traits or {}, proposals, notes)  # (0.105.30) its wing walls
        except Exception as e_:  # noqa: BLE001  (an odd report value: the gates go on)
            notes.append(f"rule _wings_rule failed ({type(e_).__name__}: {str(e_)[:120]}); the others ran")
    if refused:
        def short_why(text: str, n: int = 140) -> str:
            text = str(text)
            return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."
        # (0.105.35) said as what the AI does: it tries again (a stockpile in
        # the way it moves itself, water it looks at)
        notes.append(f"the game refused to build at {len(refused)} entrance(s), e.g. "
                     + "; ".join(f"{w}: {short_why(r)}" for w, r in refused[:2])
                     + ". The AI tries again every 2 weeks (at once when it moved a stockpile in the way)")
    # Entrances doors can't close: one item for all of them (a big old fort
    # can have dozens), the widest named.
    if open_wide:
        open_wide.sort(key=lambda x: -(x[0].get("width") or 0))
        named = "; ".join(f"{w} ({e.get('width')} wide)" for e, w in open_wide[:3])
        surface = sum(1 for e, _ in open_wide if e.get("kind") == "surface")
        head = (f"{len(open_wide)} entrance(s) can't be closed with doors ({surface} to the surface, "
                f"{len(open_wide) - surface} to the caverns or deeper), e.g. {named}")
        if not rules_["fortify_entrances"]:
            # (0.105.35) the player's own switch (on by default): respected, said plainly
            notes.append(f"{head}: walling entrances down is off on the Rules tab, so the AI leaves them open")
        else:
            # (0.105.35) kept: past the AI's walls (and no stair below to cut
            # off), said with what the AI does meanwhile
            ask_player(notes, f"{head}: wider than {cfg['fortify_max_width']} tiles, past what the AI can wall, "
                              "and no stair below them for it to cut off with hatches: they stay open; when "
                              "danger comes through them the AI's alarm and squads answer it there, not a gate")


GATE_PART_RECIPES = {"hatch": ("hatch_covers", "stone_hatch_cover", "hatch cover"),
                     "door": ("doors", "stone_door", "door")}


GATE_PART_STUCK_DAYS = 7


def _gate_parts_rule(s: dict, ent: dict, es: list, off: int, proposals: list, notes: list, memory=None) -> None:
    """(0.104.105, overnight review) A hatch or door planned at an entrance is
    built only from one the fort has. The hatch over the main stair waited 15
    hours for a hatch cover nobody made; the entrance read "closing" all along,
    so nothing else was tried, and two titans walked in. Parts are ordered at
    the mason's when none is free; a gate still waiting a week with parts free
    is put to the player. (0.105.35) Then its suspended building jobs are
    resumed (free_gate_jobs); still waiting two weeks: Needs you, kept (what
    holds it is past what the AI can see)."""
    parts = _d(ent.get("parts"))
    jobs_freed = False
    want: dict = {}
    for e in es:
        if e.get("sealed") or not e.get("closing"):
            continue
        waiting = _d(e.get("waiting"))
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        for what, (field, recipe, word) in GATE_PART_RECIPES.items():
            n = waiting.get(what)
            if not isinstance(n, int) or n <= 0:
                continue
            free = parts.get(field)
            if not isinstance(free, int):
                continue                    # an older bridge: parts not counted
            if free == 0:
                w = want.setdefault(what, [0, where])
                w[0] += n
            elif isinstance(e.get("closing_days"), int) and e["closing_days"] >= GATE_PART_STUCK_DAYS:
                # (0.104.139) the "free" one may be one the game won't use (an
                # heirloom): one more is made all the same (once for each stuck
                # entrance: review), and you're told
                done_ = memory.gate_part_extra if isinstance(getattr(memory, "gate_part_extra", None), dict) else {}
                ek = f"{e.get('x')},{e.get('y')},{e.get('z')}|{what}"
                if ek not in done_:
                    w = want.setdefault(what, [0, where])
                    w[0] += n
                    w.append(ek)
                if not jobs_freed and isinstance(e.get("id"), int):
                    proposals.append(Proposal("gate_jobs", {"type": "free_gate_jobs", "entrance_id": e["id"]},
                                              f"the {word} planned at {where} has waited {e['closing_days']} days "
                                              f"with {free} free: resume its suspended building job", 3))
                    jobs_freed = True
                if e["closing_days"] >= 2 * GATE_PART_STUCK_DAYS:
                    ask_player(notes, f"a {word} planned at {where} has waited {e['closing_days']} days though "
                                      f"{free} {word}(s) are free, one more was made and its suspended jobs "
                                      "resumed: something the AI can't see holds it (the spot blocked?); the AI "
                                      "keeps it planned and maps the entrances again each week")
                else:
                    notes.append(f"a {word} planned at {where} has waited {e['closing_days']} days though "
                                 f"{free} {word}(s) are free: one more is made and its suspended building "
                                 "job resumed")
    for what, (n, where, *eks) in want.items():
        field, recipe, word = GATE_PART_RECIPES[what]
        held = parts.get(field + "_held") or 0
        need = min(4, n - held) if isinstance(held, int) else n
        need = max(need, 1) if (parts.get(field) or 0) > 0 else need    # (the stuck case above: one)
        if need > 0 and not queued(s, {recipe}):
            if eks and memory is not None:                 # (0.104.139) the extra one: remembered
                if not isinstance(getattr(memory, "gate_part_extra", None), dict):
                    memory.gate_part_extra = {}
                for ek in eks:
                    memory.gate_part_extra[ek] = abs_tick(s)
            proposals.append(Proposal("gate_parts", {"type": "work_order", "recipe": recipe, "amount": need},
                                      f"the {word} planned at {where} waits for a {word} the fort doesn't have: "
                                      f"a mason makes {need}", 3, is_order=True))


def _free_gate_levers(s: dict) -> list:
    """The levers the AI may link, while linked to nothing and with no job:
    ones the AI placed for a drawbridge ("AI gate lever"), or the player's
    "AI gate" (bridge 0.35+ lists both; older ones: the player's only)."""
    free = [g for g in _l(_d(s.get("entrances")).get("free_levers")) if isinstance(g, dict) and "id" in g]
    if free:
        return free
    return [g for g in _l(_d(s.get("military")).get("gates"))
            if isinstance(g, dict) and not g.get("linked") and not g.get("pending") and "id" in g]


def _lever_far_enough(lever: dict, e: dict) -> bool:
    """Is the lever away from the entrance (20+ tiles or 4+ levels)? Unknown
    position (an older bridge): taken as yes."""
    lx, ly, lz = lever.get("x"), lever.get("y"), lever.get("z")
    if not all(isinstance(v, int) for v in (lx, ly, lz)):
        return True
    ex, ey, ez = e.get("x") or 0, e.get("y") or 0, e.get("z") or 0
    return abs(lz - ez) > 3 or max(abs(lx - ex), abs(ly - ey)) >= 20


def machinery_wanted(traits: dict) -> bool:
    """(0.105.12, 14.1 step 4) A fort that cares for its machinery or its
    walls works its gates by lever: Engineering 40+ or Fortification 60+."""
    return ((traits or {}).get("engineering", 0) or 0) >= 40 or ((traits or {}).get("fortification", 0) or 0) >= 60


def _lever_hatches_ok(e: dict, cfg: dict) -> bool:
    """(0.105.23) An entrance whose hatches get levers: not a cut (its many
    hatches, a lever each), at most hatch_lever_max_hatches of them."""
    if e.get("cut") or (isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0):
        return False
    n = sum(1 for b in _l(e.get("equipment")) if isinstance(b, dict) and b.get("kind") == "hatch")
    return n <= cfg.get("hatch_lever_max_hatches", 2)


def _link_wanted(s: dict, e: dict, lever_id=None, hatches: bool = False) -> list:
    """Drawbridges at this entrance the AI gate lever should be linked to:
    ones no lever inside the fort works, and watched ones whose levers are
    all at the gate. [] with an older bridge (no lever details). (0.105.12)
    hatches: a hatch no lever works, too. (0.105.23) Drawbridges first."""
    out = [bid for bid in _l(e.get("bridges_unworked")) if isinstance(bid, int)]
    later = []
    if e.get("gatehouse") == "standing" and not e.get("outer"):
        hatches = False                     # (0.105.23) the gatehouse's drawbridge gets its lever first
    for b in _l(e.get("equipment")):
        if (isinstance(b, dict) and b.get("kind") == "bridge" and "lever_away" in b and not b["lever_away"]
                and not (lever_id is not None and lever_id in _l(b.get("levers")))):
            out.append(b.get("id"))
        elif (hatches and isinstance(b, dict) and b.get("kind") == "hatch" and "levers" in b
              and not _l(b.get("levers")) and isinstance(b.get("id"), int)):
            later.append(b["id"])
    return out + later


def _lever_rule(s: dict, memory, cfg: dict, es: list, now: int, proposals: list, traits: dict | None = None) -> None:
    """A drawbridge in an entrance that no lever inside works, or only levers
    at the gate: the lever named "AI gate", while it's linked to nothing (and
    is itself away from that gate), is linked to it, so a dwarf can close it
    from inside, away from the danger. Two free mechanisms are needed; if
    there aren't, they're ordered.
    (0.105.23, 14.1 step 4a) A fort that works its gates by machinery
    (machinery_wanted) gets a lever for its hatches too (hatch_levers): the
    gate watcher drives a hatch on a lever by DFHack's instant pull, and a
    hatch the link shut is opened at once. One lever for each gate: a free
    lever is linked once, and the next gate gets a lever of its own.
    Drawbridges before hatches; a lever is placed only with 3 mechanisms
    free (its own and the link's two), else they're ordered."""
    hatches = (cfg.get("hatch_levers") and machinery_wanted(traits or {})
               and not _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"))
    ent = _d(s.get("entrances"))
    # (0.105.23) drawbridges before hatches: entrances with a bridge to link come first
    def bridge_first(e):
        wanted = _link_wanted(s, e, None, hatches=False)
        return 0 if wanted else 1
    es = sorted(es, key=bridge_first)
    levers = _free_gate_levers(s)
    if not levers:
        # (0.105.12) a fort that wants machinery and has a gate no lever works: a lever of its own
        if hatches:
            for e in es:
                if (e.get("sealed") and _lever_hatches_ok(e, cfg)
                        and _link_wanted(s, e, None, hatches=True)):
                    off = _d(s.get("map")).get("elevation_offset")
                    elev = (e.get("z") or 0) + (off if isinstance(off, int) else 0)
                    free = ent.get("free_mechanisms")
                    need = cfg.get("hatch_lever_mechanisms", 3)
                    if isinstance(free, int) and free < need:
                        # (0.105.23) the lever and its link's two first: never a lever left unlinked for want
                        if not queued(s, {"mechanisms"}):
                            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                                     "amount": need - free},
                                                      f"{need - free} mechanism(s) for a gate lever and its link "
                                                      f"({free} free)", 6, is_order=True))
                        break
                    proposals.append(Proposal("gate_lever", {"type": "place_gate_lever", "entrance_id": e["id"]},
                                              f"the gate at the {e.get('kind')} entrance at elevation {elev} has no "
                                              "lever, and this fort works its gates by machinery: a lever inside, "
                                              "away from the gate", 6))
                    break
        return
    for e in es:
        # the first free lever away from this gate (another may suit another gate)
        lever = next((lv for lv in levers if _lever_far_enough(lv, e)), None)
        if not lever:
            continue
        for bid in _link_wanted(s, e, lever["id"], hatches=hatches and _lever_hatches_ok(e, cfg)):
            key = f"lever:{lever['id']}>{bid}"
            why = memory.gate_failures.get(key)
            when = memory.gate_failure_ticks.get(key)
            short = why and "free mechanisms" in why
            wait = cfg["link_mechanisms_retry_ticks"] if short else cfg["gate_retry_ticks"]
            if why and "traceback" in why:
                wait = TICKS_PER_DAY            # a fault in the bridge, not the fort: try again tomorrow
            if why and isinstance(when, int) and 0 <= now - when < wait:
                if short:
                    proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                             "amount": 2},
                                              "2 mechanisms to link the AI gate lever to a drawbridge", 4,
                                              is_order=True))
                continue
            off = _d(s.get("map")).get("elevation_offset")
            elev = (e.get("z") or 0) + (off if isinstance(off, int) else 0)
            proposals.append(Proposal("gate_lever", {"type": "link_lever", "lever_id": lever["id"],
                                                     "target_id": bid},
                                      f"the gate at the {e.get('kind')} entrance at elevation {elev} "
                                      f"(x{e.get('x')} y{e.get('y')}) has no lever a dwarf can pull from "
                                      "inside, away from the gate: link the AI gate lever to it", 4))
            return


def _trap_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list) -> None:
    """Traps behind each gate that has none, in the fort's trap style (the
    Traps area: none, cage, stone-fall or weapon traps), as many as
    Fortification, Engineering and Caution call for. One gate a cycle, never
    while a threat can reach the dwarves; mechanisms ordered if too few."""
    import defence
    kind = profile_from(traits, memory.culture)["traps"]
    if kind == "none":
        return
    reg = _d(_d(memory.atlas).get("registry"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    for e in es:
        # (0.105.9) a hatch is a gate too: the founding stair's hatch was every
        # fort's only gate, so no fort ever got a trap
        if not e.get("sealed") or not any(isinstance(b, dict) and b.get("kind") in ("door", "bridge", "hatch")
                                          for b in _l(e.get("equipment"))):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        # (records are filed under the tile the scan named then, which moves a
        # little as walls go up: near, 3 tiles on the same level, counts)
        traps_near = {k[6:]: v for k, v in reg.items() if k.startswith("traps:")}
        gates_near = {k[5:]: v for k, v in reg.items() if k.startswith("gate:")}
        if _near_spot(e, traps_near) or str(_d(_near_spot(e, gates_near, value=True)).get("variant")) == "gatehouse":
            continue                            # (a gatehouse has its cage traps already)
        why, when = memory.gate_failures.get("traps:" + spot), memory.gate_failure_ticks.get("traps:" + spot)
        if why and isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
            continue
        n = defence.trap_count(traits)
        from quirks import has_rule
        if has_rule(memory.culture, "more_traps"):
            n = min(10, n + 2)                     # (Trapsmiths)
        if has_rule(memory.culture, "harden_after_siege"):
            # (0.103.1, Grudge-keepers: the rule had no effect) a trap more for each siege survived
            n = min(12, n + min(4, int(_d(memory.culture).get("sieges") or 0)))
        n = min(8, n)                              # (0.105.10) the bridge places 1-8 a call (A asked 9: refused)
        where = f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} (x{e.get('x')} y{e.get('y')})"
        proposals.append(Proposal("traps", {"type": "place_traps", "entrance_id": e["id"], "kind": kind, "count": n},
                                  f"{where} has a gate but no traps: {n} {kind} trap(s) just inside it", 6))
        free = _d(s.get("entrances")).get("free_mechanisms")
        if isinstance(free, int) and free < n:
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": n - free},
                                      f"{n - free} mechanisms for the traps at {where}", 6, is_order=True))
        return


def _gatehouse_rule(s: dict, memory, cfg: dict, es: list, now: int, traits: dict, proposals: list) -> None:
    """(0.105.23, 14.1 step 4a) The War-hold's gate as a level: a fort of
    Fortification gatehouse_fortification+ builds a gatehouse in front of
    the founding stair's hatch (lua/ai-gates.lua build_gatehouse): a walled
    corridor on the surface, its floor set with traps in the fort's style
    (cage when it has none), ended by a drawbridge the gate rule then gives
    a lever. Once at a spot, never while a threat can reach the dwarves (the
    caller), one a cycle; a refusal waits gate_retry_ticks. Mechanisms for
    the traps, the lever and its link are ordered when short."""
    import defence
    if (traits.get("fortification", 0) or 0) < cfg["gatehouse_fortification"]:
        return
    ent = _d(s.get("entrances"))
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    built = getattr(memory, "gatehouses", None) or {}
    for e in es:
        if not (e.get("sealed") and e.get("kind") == "surface" and e.get("gatehouse") == "possible"):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if _near_spot(e, built):
            continue                            # built here once: the scan sees its bridge, or it was taken down
        why, when = memory.gate_failures.get("gatehouse:" + spot), memory.gate_failure_ticks.get("gatehouse:" + spot)
        if why and isinstance(when, int) and 0 <= now - when < cfg["gate_retry_ticks"]:
            continue
        kind = profile_from(traits, memory.culture)["traps"]
        kind = kind if kind in ("cage", "stonefall", "weapon") else "cage"
        n = max(2, min(4, defence.trap_count(traits)))
        where = f"the founding stair at elevation {(e.get('z') or 0) + off + 1} (x{e.get('x')} y{e.get('y')})"
        proposals.append(Proposal("gatehouse", {"type": "build_gatehouse", "entrance_id": e["id"], "kind": kind,
                                                "count": n},
                                  f"a fortified fort (Fortification {int(traits.get('fortification', 0)):+d}): a "
                                  f"gatehouse in front of the hatch at {where}: a walled corridor with {n} {kind} "
                                  "trap(s) and a drawbridge, raised with the hatch when danger comes", 6))
        need = n + 3                            # the traps, the bridge's lever and its link
        free = ent.get("free_mechanisms")
        if isinstance(free, int) and free < need and not queued(s, {"mechanisms"}):
            proposals.append(Proposal("mechanisms", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": need - free},
                                      f"{need - free} mechanisms for the gatehouse at {where}", 6, is_order=True))
        return


def _near_spot(e: dict, spots, value: bool = False):
    """Is this entrance where the AI already built? Walls move an entrance's
    first tile to its gap, so near (3 tiles, same level) counts. value: give
    back what's stored there (spots is a dict) instead of True."""
    for sp in spots:
        try:
            x, y, z = (int(v) for v in str(sp).split(","))
        except ValueError:
            continue
        exact = x == e.get("x") and y == e.get("y") and z == e.get("z")
        if isinstance(spots, dict) and str(spots[sp]).startswith("water"):
            # nothing was built for a water gate, so the map didn't move: that
            # spot only (a real opening 3 tiles away is another entrance)
            if not exact:
                continue
        if z == e.get("z") and abs(x - (e.get("x") or 0)) <= 3 and abs(y - (e.get("y") or 0)) <= 3:
            return (spots[sp] if isinstance(spots, dict) and spots[sp] else True) if value else True
    return False


def lone_intruders(s: dict, cfg: dict, traits: dict | None = None, memory=None) -> list:
    """The ids of the enemies that can reach the dwarves when they are only a
    few (`lone_intruder_max`) ordinary ones (no great danger, flier or
    building destroyer) already INSIDE the fort, and nothing hostile is left
    outside; [] otherwise. Inside is the gate scan's map of the fort
    (entrances.intruders_inside, lua/ai-gates.lua): DF's walk groups can't
    tell an enemy inside from one waiting at a locked door. Without that map
    (an older bridge, no scan yet): [] (as before). One read as inside before
    (memory) still counts while no new enemy came: a thief walking out past
    the gate doesn't arm it again behind him."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = reachable_threats(s, traits if traits is not None else _traits(s), cfg)
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    # (0.105.4 review) no map this cycle (a rescan, a reload): the ones read
    # as inside before still count, so the lone-thief case doesn't flip
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if isinstance(x, int)} | {
        x for x in _l(_lockdown(memory).get("lone_ids")) if isinstance(x, int)}
    if not inside:
        return []
    for i in reach:
        t = rows.get(i)
        if (not isinstance(t, dict) or i not in inside or t.get("great_danger") or t.get("flier")
                or t.get("destroyer")):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []                       # a siege still outside: the gates hold it off, as before
    return list(reach)


def few_ordinary(s: dict, cfg: dict, traits: dict | None = None) -> list:
    """(0.105.8) The ids of the enemies that can reach the dwarves when they
    are only a few (`lone_intruder_max`) ordinary ones (no great danger,
    flier or building destroyer), inside or outside, and no siege is held off
    at the gates; [] otherwise."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = list(reachable_threats(s, traits if traits is not None else _traits(s), cfg))
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    for i in reach:
        t = rows.get(i)
        if not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer"):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []
    return reach


def few_alert_over(s: dict, memory, cfg: dict) -> bool:
    """(0.105.8) The alarm has been up `lone_intruder_alert_ticks` while only a
    few ordinary enemies were about, inside or out. B (Monastery, 2 Nov): one
    thief outside, the alarm up 70 real minutes at 1-3 FPS; the shelter held
    the civilians from the drink and 31 died of thirst when it came down.
    (0.105.30 live fixes) Counted from the last cycle one of them was seen
    near a dwarf (few_near, note_lockdown), not from when the few began: E
    (8 Nov 13:51) lowered the alarm 635 ticks after raising it, the thief 1
    tile from the citizens and still killing (3 citizens dead)."""
    rec = _lockdown(memory)
    since, now = rec.get("few_since"), abs_tick(s)
    near = rec.get("few_near")
    if isinstance(since, int) and isinstance(near, int) and near > since:
        since = near
    return (isinstance(since, int) and isinstance(now, int)
            and now - since >= cfg.get("lone_intruder_alert_ticks", 600))


def few_near(s: dict, cfg: dict, ids: list) -> bool:
    """(0.105.30 live fixes) Is one of these enemies within
    `few_alert_near_tiles` of a dwarf (and 2 levels): among the citizens, not
    one waiting about far off (B's thief outside)?"""
    want = set(ids)
    tiles = cfg.get("few_alert_near_tiles", 12)
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict) or t.get("id") not in want:
            continue
        d, dz = t.get("distance_to_nearest_dwarf"), t.get("levels_from_nearest_dwarf")
        if (isinstance(d, (int, float)) and d <= tiles
                and (not isinstance(dz, (int, float)) or abs(dz) <= 2)):
            return True
    return False


def hunted_outside(s: dict, cfg: dict, traits: dict | None = None, memory=None) -> list:
    """The ids of the enemies that can reach the dwarves when they are only a
    few (`lone_intruder_max`) ordinary ones (no great danger, flier or
    building destroyer), some of them outside the fort, no siege is held off
    at the gates, and an armed squad has a kill order on every one of them
    (the gates then open: the squads must get out, the citizens in); []
    otherwise. Without the gate scan's map: []."""
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict)}
    reach = list(reachable_threats(s, traits if traits is not None else _traits(s), cfg))
    if not reach or len(reach) > cfg.get("lone_intruder_max", 2):
        return []
    ent = _d(s.get("entrances"))
    if not ent.get("scanned"):
        return []
    for i in reach:
        t = rows.get(i)
        if not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer"):
            return []
    if any(t.get("id") not in reach for t in held_off_threats(s)) or great_present(s):
        return []
    want = set(reach)
    hunted = set()
    for q in _l(_d(s.get("military")).get("squads")):
        if isinstance(q, dict) and q.get("ai_orders") and can_fight(q, cfg) and isinstance(q.get("kill_ids"), list):
            hunted |= want & set(q["kill_ids"])
    # (a squad on them, not citizens outside alone: without one the watcher
    # would be armed, shut and opened again each cycle)
    return reach if hunted == want else []


def ai_gates_shut(s: dict, memory=None) -> bool:
    """The AI's gates shut now: the watcher armed with an entrance closed, or
    the AI gate lever pulled by the AI."""
    ent = _d(s.get("entrances"))
    if ent.get("armed") and any(isinstance(e, dict) and e.get("closed") for e in _l(ent.get("entrances"))):
        return True
    return bool(memory is not None and getattr(memory, "gate_closed_by_ai", False))


class _Rec:
    """A stand-in memory holding only a lockdown record (note_lockdown reads
    lone_intruders against the record it is building)."""
    def __init__(self, rec: dict):
        self.atlas = {"lockdown": rec}


def _lockdown(memory) -> dict:
    """The lockdown's record, kept in the atlas beside the gates' history:
    {new: tick the last new enemy came, seen: ids, released: tick the AI
    opened up early, lone_since: tick only a lone intruder was left}."""
    return _d(_d(getattr(memory, "atlas", None)).get("lockdown")) if memory is not None else {}


def lockdown_released(memory) -> bool:
    return isinstance(_lockdown(memory).get("released"), int)


def lone_alert_over(s: dict, memory, cfg: dict) -> bool:
    """The alarm has been up `lone_intruder_alert_ticks` for a lone intruder."""
    since, now = _lockdown(memory).get("lone_since"), abs_tick(s)
    return (isinstance(since, int) and isinstance(now, int)
            and now - since >= cfg.get("lone_intruder_alert_ticks", 600))


def _lockdown_ids(s: dict, traits: dict, cfg: dict) -> list:
    ids = list(reachable_threats(s, traits, cfg))
    return ids + [t.get("id") for t in held_off_threats(s) if t.get("id") not in ids]


def _lockdown_cap_why(s: dict, cfg: dict, ids: list, quiet_ticks: int, rec: dict | None = None) -> str:
    """Why an AI lockdown is opened early ("" if it isn't): no new enemy for
    `lockdown_max_days`, only a few ordinary ones left, all of them already
    INSIDE the fort, and the game slow or citizens shut out. A siege or a
    great danger: never. (0.105.4 review) Enemies held off outside never
    count toward it: two camped at the gate of a slow fort for 2 days got the
    gates opened, and nothing closed them again when those two walked in."""
    if not ids or quiet_ticks < cfg.get("lockdown_max_days", 2) * TICKS_PER_DAY:
        return ""                       # (nothing left: all_clear's quiet days, as before)
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if isinstance(x, int)} | {
        x for x in _l(_d(rec).get("lone_ids")) if isinstance(x, int)}
    if held_off_threats(s) or any(i not in inside for i in ids):
        return ""
    rows = {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    if (len(ids) > cfg.get("lockdown_cap_threats", 2) or great_present(s)
            or any(i not in rows or rows[i].get("great_danger") for i in ids)):
        return ""
    out = int(_d(s.get("entrances")).get("citizens_outside") or 0)
    if s.get("fps_low"):
        return f"the game runs slowly (FPS {s.get('fps_low')})"
    if out > 0:
        return f"{out} citizen(s) are shut out"
    return ""


def note_lockdown(s: dict, memory, cfg: dict) -> list[str]:
    """(0.105.3) Bookkeeping before planning (note_cycle): when the last new
    enemy came while the AI held the fort shut, whether only a lone intruder
    is left (and since when), and whether the lockdown is opened early. A
    new enemy closes it again."""
    notes: list[str] = []
    if not isinstance(getattr(memory, "atlas", None), dict):
        memory.atlas = {}
    now = abs_tick(s)
    if not isinstance(now, int):
        return notes
    traits = _traits(s)
    ids = _lockdown_ids(s, traits, cfg)
    holding = _holding_off(s, memory) or bool(memory.gate_closed_by_ai)
    if not ids and not holding:
        memory.atlas.pop("lockdown", None)
        return notes
    rec = dict(_lockdown(memory))
    seen = _l(rec.get("seen"))
    new = [i for i in ids if i not in seen]
    if not isinstance(rec.get("new"), int) or rec["new"] > now:
        rec["new"] = now
    # (0.105.4 review) a lifted lockdown closes again for a new enemy, or for
    # one that can reach the dwarves now and couldn't (or wasn't inside) when
    # it was lifted: the same two camped outside walking in
    reach_now = list(reachable_threats(s, traits, cfg))
    came_in = [i for i in reach_now if i not in _l(rec.get("released_ids"))]
    if new:
        rec["new"] = now
        rec["seen"] = (seen + new)[-100:]
    if (new or came_in) and isinstance(rec.get("released"), int):
        rec.pop("released", None)
        rec.pop("released_ids", None)
        notes.append(f"{len(new) or len(came_in)} " + ("new enemy/enemies" if new else "enemy/enemies able to reach "
                     "the dwarves now") + ": the gates and alarm may close again")
    if new:
        rec.pop("lone_ids", None)       # a new enemy: read afresh from the map
    few = few_ordinary(s, cfg, traits)
    if few:
        if not isinstance(rec.get("few_since"), int) or rec["few_since"] > now:
            rec["few_since"] = now
        if few_near(s, cfg, few):           # (0.105.30 live fixes) seen among the dwarves: the half-day again
            rec["few_near"] = now
        elif isinstance(rec.get("few_near"), int) and rec["few_near"] > now:
            rec.pop("few_near", None)
    else:
        rec.pop("few_since", None)
        rec.pop("few_near", None)
    lone = lone_intruders(s, cfg, traits, _Rec(rec))
    if lone:
        if not isinstance(rec.get("lone_since"), int) or rec["lone_since"] > now:
            rec["lone_since"] = now
        rec["lone_ids"] = lone[:10]
    else:
        rec.pop("lone_since", None)
        rec.pop("lone_ids", None)
    if ids:
        rec["peak"] = max(int(rec.get("peak") or 0), len(ids))
    if great_present(s):
        rec["great"] = True
    if holding and not isinstance(rec.get("released"), int):
        why = _lockdown_cap_why(s, cfg, ids, now - rec["new"], rec)
        if why:
            rec["released"] = now
            rec["released_ids"] = reach_now[:50]
            notes.append(f"the AI has kept the fort shut {(now - rec['new']) // TICKS_PER_DAY} day(s) with no new "
                         f"enemy and only {len(ids)} left, and {why}: the gates open and the alarm comes down "
                         "(a new enemy closes them again)")
    memory.atlas["lockdown"] = rec
    return notes


def quick_clear(s: dict, memory, cfg: dict) -> str:
    """(0.105.3) Why the AI's shut gates and alarm may be lifted before
    all_clear's quiet days ("" if not): nothing hostile in sight (no enemy
    that can reach the dwarves, no siege held off at the gates, no great
    danger lately), a cycle quiet, and since the last enemy was seen either
    `lockdown_clear_ticks` with citizens or many visitors shut out (A, 2 Nov:
    9 citizens and 39 visitors outside a hatch shut for a sneaker who hid
    again), or `small_alert_ticks` when only a few ordinary enemies were ever
    seen (a sneaker, a thief). A siege in sight keeps the fort shut as before."""
    if memory is None or memory.quiet_cycles < cfg["alert_quiet_cycles"]:
        return ""                       # (the quiet cycles as all_clear: only its days are cut)
    if reachable_threats(s, _traits(s), cfg) or held_off_threats(s) or great_present(s):
        return ""
    now = abs_tick(s)
    if not isinstance(now, int):
        return ""
    if memory.last_great_tick and (now - memory.last_great_tick) // TICKS_PER_DAY < cfg["alert_quiet_days_great"]:
        return ""
    since = now - int(memory.last_threat_tick or 0) if memory.last_threat_tick else 10 ** 9
    rec = _lockdown(memory)
    # shut out: only while the AI's gates are shut (with them open, nobody is)
    shut = ai_gates_shut(s, memory)
    out = int(_d(s.get("entrances")).get("citizens_outside") or 0) if shut else 0
    # (0.105.4 review) visitors OUTSIDE the fort only (a tavern holds 20+
    # inside); an older bridge without the count: citizens alone
    vo = _d(s.get("entrances")).get("visitors_outside")
    visitors = vo if shut and isinstance(vo, int) and not isinstance(vo, bool) else 0
    # (0.105.4 review) only after a small one (a sneaker, a thief): a bigger
    # ambush that vanished keeps the normal quiet wait
    small = not rec.get("great") and 0 < int(rec.get("peak") or 0) <= cfg.get("lockdown_cap_threats", 2)
    if (small and (out > 0 or visitors >= cfg.get("lockdown_visitors", 20))
            and since >= cfg.get("lockdown_clear_ticks", 300)):
        return (f"nothing hostile in sight for {since // 50} game hour(s) and "
                + (f"{out} citizen(s)" if out else f"{visitors} visitors") + " shut out")
    if small and since >= cfg.get("small_alert_ticks", 1200):
        return f"only {int(rec['peak'])} enemy/enemies were seen and none for a day"
    return ""


# (0.105.3) B (2 Nov): 26 PenLargeAnimal jobs open at once behind the shut
# hatch (back to 1 after): animals led to pastures outside, every one
# re-routing to a way in that wasn't there. What puts animals in a pasture
# (or makes one, or pens the hens) waits while the AI's gates are shut.
PASTURE_ACTIONS = ("pasture", "make_pasture", "nest_boxes")


def _pasture_hold(s: dict, memory, proposals: list, notes: list) -> list:
    if not ai_gates_shut(s, memory):
        return proposals
    held = [p for p in proposals if p.action.get("type") in PASTURE_ACTIONS]
    if not held:
        return proposals
    notes.append(f"the AI's gates are shut: {len(held)} pasture assignment(s) wait until they open "
                 "(animals led to a pasture outside would only pile up at the gate)")
    return [p for p in proposals if p not in held]


def gate_invaders(s: dict) -> list:
    """Invaders on the map that can't reach the dwarves yet (outside the gates,
    on the surface): the squads wait for them inside the main gate."""
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)
            and t.get("invader") and not t.get("can_reach_dwarves") and t.get("layer") in (None, "surface")]


def main_gate(s: dict, memory) -> dict | None:
    """The fort's main gate: the entrance nearest the plan's main stair (else
    the first surface one)."""
    es = [e for e in _l(_d(s.get("entrances")).get("entrances"))
          if isinstance(e, dict) and all(isinstance(e.get(k), int) for k in ("x", "y", "z"))]
    if not es:
        return None
    spine = _d(_d(_d(getattr(memory, "atlas", None)).get("plan")).get("spine"))
    if isinstance(spine.get("x"), int) and isinstance(spine.get("y"), int):
        return min(es, key=lambda e: abs(e["x"] - spine["x"]) + abs(e["y"] - spine["y"]))
    return next((e for e in es if e.get("kind") == "surface"), es[0])


def _gate_guard_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.83) Invaders on the map who can't reach the dwarves yet: every
    squad able to fight holds the main gate (a defend order on the gate guard
    burrow, inside it); once they can reach the dwarves the kill orders take
    over, and when they are gone the squads are called back."""
    if not player_rules(s).get("train_squads", True):
        return
    if int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return
    inv = gate_invaders(s)
    gate = main_gate(s, memory)
    if not inv or not gate:
        return
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]
    able = [q for q in squads if can_fight(q, cfg)
            and not q.get("ai_orders") and not (q.get("orders") or 0)]
    if not able:
        return
    proposals.append(Proposal("gate_guard", {"type": "guard_gate", "x": gate["x"], "y": gate["y"], "z": gate["z"],
                                             "squads": [q["id"] for q in able]},
                              f"{len(inv)} invader(s) on the map, none in reach of the dwarves yet: "
                              f"{len(able)} squad(s) hold the main gate (x{gate['x']} y{gate['y']})", 0))


def _gate_dogs_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(0.104.83) War-trained animals with no post: penned just inside the
    main gate (a pen made there the first time), a few a call."""
    an = _d(_d(s.get("society")).get("animals"))
    free = int(_d(an.get("gate")).get("free") or 0)
    if free <= 0 or int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0) > 0:
        return
    gate = main_gate(s, memory)
    if not gate:
        return
    proposals.append(Proposal("gate_dogs", {"type": "gate_dogs", "x": gate["x"], "y": gate["y"], "z": gate["z"],
                                            "max": min(4, free)},
                              f"{free} war-trained animal(s) with no post: pen them inside the main gate "
                              "(they meet what comes in)", 5))
