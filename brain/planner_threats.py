"""(0.105.0) Threats that were only noted before, now answered (round 3).

The bridge's `threats` report (lua/ai-threats.lua) says where fire burns,
who sits caught in a cage, thieves and snatchers about, the walking dead,
evil clouds and a reanimating land, werebeast citizens and the moon, great
dangers out on the surface, and who fetches the wounded. Each gets a rule:

  1. fire: the tiles round it restricted and the jobs beside it taken off
     (lifted once it is out); the alarm is held while it is near the dwarves;
  2. prisoners: a cage room inside the fort; the Rules tab's choice (keep,
     release outside, kill) - only "keep" can be done safely through DFHack,
     so the others are said and the prisoners kept;
  3. thieves and snatchers: the squads sent at one inside the fort, and cage
     traps at every gated entrance once one was seen or the world has goblins;
  4. the undead, an evil cloud on the surface: the alarm (everyone inside,
     no surface work) until clear; bodies lying out in a reanimating land
     rotted away when nothing threatens;
  5. werebeast citizens: a cell (a jail or a free bedroom, its doors locked
     once they're in) for the days round the full moon, learned from the
     changes seen; let out after;
  6. great beasts in the caverns: every cavern opening on record locked,
     whatever the squads could do (0.105.26); unlocked once it has gone;
     every opening onto a cavern gets a door or hatch straight away;
  7. a great danger on the surface near dwarves out there: the alarm;
  8. nobody has DF's Recover wounded labour: two dwarves put on it;
  9. (0.105.54, "fight back") the great beast sealed out of the caverns gets a
     kill plan (beast_tactic: planner_matchup.beast_plan on its facts):
     melee only when nothing it breathes or spins makes closing in suicidal
     and the squads are about even; ranged from behind a cavern opening's
     fortifications; else a cage trap line or the lure pocket (planner_lure)
     while the fort builds toward the fight, what is missing said. Ready:
     the squads posted (stationed at the door, or on the archer post), then
     the seal opened for the fight (_beast_hunt); shut again when the fight
     goes badly, a citizen goes down, or it never comes.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, PLANNER_CONFIG, Proposal, STEER_PROTECTED, TICKS_PER_DAY, abs_tick, ask_player,
                          can_fight, crowded_thief, player_rules, reachable_threats, thief_rows, _traits)

__all__ = ["_threat_rules", "threat_alert", "alarm_held", "threat_rules_of", "moon_due", "PRISONER_CHOICES", "THREAT_CONFIG",
           "note_intrusions", "unseen_intrusion", "lone_sneaker", "watch_spots", "thief_watchers"]

PRISONER_CHOICES = ("keep", "release", "kill")

# (0.105.0) the round's own settings, added to the planner's (cooldowns are read from there by select())
THREAT_CONFIG = {
    "fire_guard_cooldown_ticks": 100,        # the fire guard every ~2 hours while it burns
    "fire_guard_near": 40,                   # a fire this close to the dwarves (levels count 3) is guarded
    "fire_guard_radius": 6,
    "fire_guard_jobs": 40,                   # jobs beside the fire taken off at most each time
    "prisoner_room_cooldown_ticks": 7 * 1200,
    "thief_traps": 3,                        # cage traps at a gate once thieves or snatchers were seen
    "thief_crowd_min": 3,                    # (0.105.51) people within a few tiles of a thief: no squad sent in
    "undead_near": 30,                       # the walking dead this close to a dwarf: the alarm
    "evil_cloud_near": 40,                   # an evil cloud this close to a dwarf out on the surface
    "surface_danger_near": 40,               # a great danger this close to a dwarf out there
    "reanimate_corpses": 5,                  # bodies lying out in a reanimating land: rotted away
    "reanimation_cooldown_ticks": 7 * 1200,
    "moon_days": 28,                         # DF's moon: about a month from one full moon to the next
    "moon_before_days": 3,                   # in the cell this long before the expected change...
    "moon_after_days": 2,                    # ...and this long after
    "moon_cell_cooldown_ticks": 300,
    "seal_cavern_cooldown_ticks": 600,
    "seal_missing_days": 7,                  # (0.105.0 review) a sealed layer gone from the report: unlocked after
    "threat_alarm_max_days": 7,              # (0.105.0 review) the threats round holds the alarm this long at most
    "cavern_alarm_max_days": 3,              # (v35 fix) the alarm held for citizens in the caverns this long at most
    "cavern_realarm_days": 7,                # (0.105.51) after that, no new alarm for the caverns this long
    "rescue_labor_cooldown_ticks": 14 * 1200,
    "beast_open_days": 3,                    # (0.105.54) the seal open this long for a fight that never came: shut
    "beast_retry_days": 7,                   # ...and not opened again for this long
}
PLANNER_CONFIG.update({k: v for k, v in THREAT_CONFIG.items() if k not in PLANNER_CONFIG})

# (0.105.0) the fire guard and the moon cells wait for no action slot, and the strategist never holds them
LIMIT_EXEMPT.update({"fire_guard", "moon_cell"})
STEER_PROTECTED.update({"fire_guard", "moon_cell", "seal_cavern"})

AGENDA_THEMES.update({"fire_guard": "keep the dwarves away from the fire", "prisoners": "a cage room for prisoners",
                      "thieves": "keep thieves and snatchers out", "undead": "keep the dwarves in from the dead",
                      "reanimation": "rot the bodies an evil land would raise",
                      "moon_cell": "lock the werebeasts in for the full moon",
                      "seal_cavern": "seal the cavern against a beast", "rescue_labor": "fetch the wounded",
                      "cavern_openings": "doors on the ways into the caverns",
                      "beast_hunt": "kill the great beast in the caverns"})


def note_intrusions(state: dict, memory, events: list) -> int:
    """(0.105.30 live fixes) DF's invasion records, from the bridge's events,
    kept for the alarm (unseen_intrusion): {tick, civ, invaders}. E (8 Nov):
    `invasion civ_id -1, invaders_now 1` at 13:50:49 was the hidden thief, a
    weasel woman who had asked the mayor for meetings since 13:44; she was
    "spotted sneaking around" only at 13:51:07, among the dwarves, and the
    alarm came then, with the fight already on (3 citizens dead). A new
    record replaces the last (and what the player did about it). Returns how
    many records came."""
    now = abs_tick(state)
    if not isinstance(now, int):
        return 0
    n = 0
    for e in events or []:
        if isinstance(e, dict) and e.get("kind") == "invasion":
            memory.intrusion = {"tick": now, "civ": e.get("civ_id"),
                                "invaders": e.get("invaders_now") if isinstance(e.get("invaders_now"), int) else None}
            n += 1
    return n


def unseen_intrusion(s: dict, memory, cfg: dict):
    """(0.105.30 live fixes) DF's last invasion record ({tick, civ, invaders})
    while it is under `intrusion_alert_days` old and the player hasn't
    lowered the alarm the AI sounded for it, and no enemy able to reach the
    dwarves has been seen since (then the usual rules have them), else None.
    Thieves and snatchers hide until spotted; the record is the only word of
    them."""
    rec = getattr(memory, "intrusion", None)
    if not isinstance(rec, dict) or not isinstance(rec.get("tick"), int) or rec.get("cleared"):
        return None
    seen = getattr(memory, "last_threat_tick", None)
    if isinstance(seen, int) and seen >= rec["tick"]:
        return None
    now = abs_tick(s)
    days = int(cfg.get("intrusion_alert_days", 2) or 0)
    if not isinstance(now, int) or days <= 0 or not 0 <= now - rec["tick"] < days * TICKS_PER_DAY:
        return None
    return rec


def lone_sneaker(rec) -> bool:
    """(0.105.51) Is DF's invasion record a lone sneaker: one invader (or
    none counted) of no civilisation (civ_id -1)? Those are artifact seekers
    and lone thieves: the R3 run (15 Nov) had 17 such records in six forts
    and no other kind; each raised the full alarm (B 4, C 5, F 1) for one
    hero the intruder guard (planner_holdfast) meets at the stair and the
    artifact. A siege's record names its civilisation."""
    if not isinstance(rec, dict):
        return False
    civ, n = rec.get("civ"), rec.get("invaders")
    return civ in (None, -1) and (n is None or (isinstance(n, int) and n <= 1))


def threat_rules_of(s: dict) -> dict:
    """The round's Rules-tab switches (lua/ai-overseer-settings.lua), with their defaults."""
    st = s.get("settings") if isinstance(s.get("settings"), dict) else {}
    pr = st.get("prisoners")
    return {"prisoners": pr if pr in PRISONER_CHOICES else "keep",
            "moon_cells": st.get("moon_cells") is not False,
            "seal_caverns": st.get("seal_caverns") is not False}


def _c(cfg: dict, k: str):
    return cfg.get(k, THREAT_CONFIG[k])


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def threat_alert(s: dict, cfg: dict) -> str:
    """Why the alarm should be up for this round's threats ("" if none): the
    walking dead near the dwarves, an evil cloud near those out on the
    surface, a great danger on the surface near those out there.
    (0.105.47) farther with Caution above 0, never nearer (brain/alarm_caution.py)."""
    from alarm_caution import near_for
    t = _d(s.get("threats"))
    u = _d(t.get("undead"))
    for x in _l(u.get("list")):
        # (0.105.0 review) only the dead that can walk to the dwarves (walled-off
        # cavern undead never could), near them; and not the dead a reanimating
        # land keeps on the surface (not invaders, not great dangers: they never
        # leave, as held_off_threats has said since 0.104.139)
        if not isinstance(x, dict) or x.get("can_reach_dwarves") is not True:
            continue
        if x.get("outside") and not x.get("invader") and not x.get("great"):
            continue
        if not _num(x.get("distance")) or x["distance"] <= near_for(s, cfg, "undead_near", 30):
            return f"the walking dead ({x.get('name') or 'undead'}) near the dwarves"
    if _num(u.get("cloud_outside_near")) and u["cloud_outside_near"] <= near_for(s, cfg, "evil_cloud_near", 40):
        return (f"an evil cloud{' of ' + str(u['cloud_material']) if u.get('cloud_material') else ''} "
                f"{u['cloud_outside_near']} tiles from dwarves on the surface")
    for x in _l(_d(t.get("surface")).get("list")):
        if (isinstance(x, dict) and x.get("great") and _num(x.get("distance_outside"))
                and x["distance_outside"] <= near_for(s, cfg, "surface_danger_near", 40)):
            return f"{x.get('name') or 'a great beast'} on the surface near dwarves out there"
    return ""


def moon_due(changes: list, now: int, cfg: dict) -> bool | None:
    """Is a werebeast's change near (from the changes seen, a moon apart)?
    None: no change seen yet, so nothing to go by."""
    ticks = [int(c["tick"]) for c in changes if isinstance(c, dict) and _num(c.get("tick"))]
    if not ticks or not isinstance(now, int):
        return None
    period = _c(cfg, "moon_days") * TICKS_PER_DAY
    since = (now - max(ticks)) % period
    return since >= period - _c(cfg, "moon_before_days") * TICKS_PER_DAY or since <= _c(cfg, "moon_after_days") * TICKS_PER_DAY


def _weak_free(s: dict):
    """(0.105.35) The best free squad with anyone armed (planner_military weak_squad)."""
    from planner_military import weak_squad
    return weak_squad([q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)
                       and not q.get("ai_orders")])


def _able_squads(s: dict, cfg: dict) -> list:
    return [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)
            and can_fight(q, cfg) and not q.get("ai_orders")]


def _fire(s, cfg, t, proposals, notes):
    f = _d(t.get("fire"))
    spots = [x for x in _l(f.get("spots")) if isinstance(x, dict)]
    n = int(f.get("fires") or 0)
    if n > 0:
        near = [x for x in spots if _num(x.get("near")) and x["near"] <= _c(cfg, "fire_guard_near")]
        where = ", ".join(f"x{x.get('x')} y{x.get('y')} z{x.get('z')}" + (" (outside)" if x.get("outside") else "")
                          for x in spots[:3])
        notes.append(f"fire in {n} place(s): {where}")
        if near:
            proposals.append(Proposal("fire_guard", {"type": "fire_guard", "radius": _c(cfg, "fire_guard_radius"),
                                                     "max_jobs": _c(cfg, "fire_guard_jobs")},
                                      f"fire {near[0]['near']} tiles from the dwarves: paths round it restricted, "
                                      f"the jobs beside it ({f.get('jobs_near') or 0}) taken off", 0))
    elif int(f.get("guarded_tiles") or 0) > 0:
        proposals.append(Proposal("fire_guard", {"type": "fire_guard", "lift": True},
                                  f"the fire is out: the {f['guarded_tiles']} tiles round it back to normal traffic", 3))


def _prisoners(s, cfg, t, rules, proposals, notes):
    p = _d(t.get("prisoners"))
    n = int(p.get("caged") or 0)
    if n <= 0:
        return
    if not p.get("cage_rooms"):
        proposals.append(Proposal("prisoners", {"type": "prisoner_room"},
                                  f"{n} prisoner(s) in cages and no cage room inside the fort: an animal stockpile "
                                  "for the full cages, inside", 5))
    choice = rules["prisoners"]
    if isinstance(_d(s.get("captives")).get("list"), list):
        return          # (item6) the captives rule says each one's outcome (planner_captives)
    if choice == "keep":
        notes.append(f"{n} prisoner(s) kept in their cages (Rules tab: prisoners)")
    else:
        what = "released outside" if choice == "release" else "put to death"
        notes.append(f"{n} prisoner(s) to be {what} (Rules tab), but DFHack offers no safe way to do it: "
                     "they stay caged in the cage room meanwhile")


def watch_spots(s: dict, memory) -> list:
    """(0.105.51) Where a squad waits for a thief in a crowd: the artifact the
    last thief named, then the main stair (planner_holdfast's guard spots):
    [(what, {x, y, z})]."""
    from planner_holdfast import _stair_spot, named_artifact
    out = []
    art = named_artifact(s, memory) if memory is not None else None
    if art:
        out.append((f"artifact {str(art.get('name'))[:40]} the thief named",
                    {"x": art["x"], "y": art["y"], "z": art["z"]}))
    st = _stair_spot(s, memory)
    if st:
        out.append(("main stair", st))
    return out


def thief_watchers(s: dict, memory) -> list:
    """(0.105.51) The squads the thieves rule posted to wait for a thief in a
    crowd: on the AI's orders, stationed on a watch spot, not the player's
    and not the intruder guard's (planner_holdfast keeps those)."""
    from planner_holdfast import _hf
    spots = [at for _, at in watch_spots(s, memory)]
    guards = {str(k) for k in _d(_hf(memory).get("guards"))} if memory is not None else set()
    return [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("ai_orders")
            and q.get("stationed") and str(q.get("id")) not in guards and not q.get("kill_ids")
            and {c: _d(q.get("stationed")).get(c) for c in ("x", "y", "z")} in spots]


def _crowded_thieves(s, cfg, memory, crowded, on_it, proposals, notes) -> None:
    """(0.105.51) A thief among a crowd (crowded_thief): no squad sent into
    it. E (15 Nov): a thief come as a guest was attacked in the tavern three
    times and each fight drew in the bards, dancers and poets (~26 visitors).
    One squad waits at the artifact the thief named (else the main stair);
    the squads go once the thief leaves the crowd. A squad already after
    the thief is left on them."""
    names = ", ".join(f"{x.get('name')} ({x.get('kind')}, {x.get('crowd')} people round them"
                      + (f" in the {str(x.get('location')).lower().replace('inn_', '')}" if x.get("location") else "")
                      + ")" for x in crowded[:3])
    if on_it:
        notes.append(f"{names}: {on_it[0].get('name') or 'a squad'} is already after them")
        return
    watch = thief_watchers(s, memory)
    if watch:
        notes.append(f"{names}: no squad sent into the crowd; {watch[0].get('name') or 'a squad'} waits for them "
                     "and the squads go once they leave it")
        return
    spots = watch_spots(s, memory)
    from planner_holdfast import _players
    busy = {p.action.get("squad_id") for p in proposals if isinstance(p.action, dict)}
    free = [q for q in _able_squads(s, cfg) if q.get("id") not in busy and not _players(q)]
    if not spots or not free:
        notes.append(f"{names}: no squad sent into the crowd; the squads go once they leave it"
                     + ("" if free else " (no free squad to post meanwhile)"))
        return
    what, at = spots[0]
    q = free[0]
    proposals.append(Proposal("thief_watch", {"type": "squad_station", "squad_id": q["id"], **at, "what": what},
                              f"{names}: no squad sent into the crowd (a fight there draws in the guests); "
                              f"{q.get('name') or 'a squad'} waits on the {what} at x{at['x']} y{at['y']} "
                              f"z{at['z']} until they leave it", 0))


def _thieves(s, cfg, t, memory, proposals, notes):
    th = _d(t.get("thieves"))
    # (0.105.51) the pulse's others_on_map thieves merged in (thief_rows)
    rows = [x for x in thief_rows(s, t) if isinstance(x, dict) and x.get("id") is not None]
    inside = [x for x in rows if x.get("inside") or x.get("can_reach_dwarves") is True]
    crowded = [x for x in inside if crowded_thief(x, cfg)]
    if crowded:
        hit_c = {x["id"] for x in crowded}
        on_c = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("ai_orders")
                and set(_l(q.get("kill_ids"))) & hit_c]
        _crowded_thieves(s, cfg, memory, crowded, on_c, proposals, notes)
        inside = [x for x in inside if x not in crowded]
    if inside:
        # (0.105.51) a squad waiting for a thief in a crowd goes first, once one is out of it
        able = thief_watchers(s, memory) + _able_squads(s, cfg)
        names = ", ".join(f"{x.get('name')} ({x.get('kind')})" for x in inside[:3])
        hit = [x["id"] for x in inside if x.get("kill_ok") is not False]
        # (0.105.3) B (2 Nov): all four squads went at one thief, one after
        # another (each cycle the next free squad). One already after them: no other
        on_it = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("ai_orders")
                 and set(_l(q.get("kill_ids"))) & set(hit)]
        if on_it:
            notes.append(f"{names} in the fort: {on_it[0].get('name') or 'a squad'} is after them")
        elif able and hit:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": able[0]["id"], "kill": hit[:10]},
                                      f"{names} in the fort: send {able[0].get('name') or 'the squad'}", 0))
        elif hit and _weak_free(s) is not None:
            # (0.105.35) no squad with enough armed: the best free one with anyone armed
            q = _weak_free(s)
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": hit[:10]},
                                      f"{names} in the fort and no squad with {cfg.get('min_squad_to_fight', 3)}+ armed "
                                      f"free: send {q.get('name') or 'the squad'} "
                                      f"({_d(q.get('power')).get('armed')} armed)", 0))
        else:
            notes.append(f"{names} in the fort" + (" and no squad free to send: watched, and sent at once a squad "
                                                    "is free" if not able else
                                                    " (the game doesn't count them as a threat: watched)"))
    elif rows:
        notes.append(f"{len(rows)} thief/snatcher(s) about, not inside yet: " + ", ".join(str(x.get("name")) for x in rows[:3]))
    seen = int(th.get("seen_total") or 0) > 0 or bool(rows)
    if not (seen or th.get("evil_civ")):
        return
    # cage traps at every gated entrance (the culture's trap rule covers forts with a trap style)
    from culture import profile_from
    from planner_military import _near_spot
    if profile_from(_traits(s), memory.culture)["traps"] != "none":
        return
    reg = _d(_d(memory.atlas).get("registry"))
    traps = {k[6:]: v for k, v in reg.items() if k.startswith("traps:")}
    now = abs_tick(s)
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict) or not e.get("sealed") or not any(
                isinstance(b, dict) and b.get("kind") in ("door", "bridge", "hatch") for b in _l(e.get("equipment"))):
            continue
        if _near_spot(e, traps):
            continue
        # (0.105.47) thieves come over the surface: its gates, and the others
        # only where Fortification puts traps (planner_traplean)
        from planner_traplean import trap_gate_why
        if e.get("kind") == "cavern" and not trap_gate_why(e, _traits(s), memory, cfg):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        when = memory.gate_failure_ticks.get("traps:" + spot)
        if isinstance(when, int) and 0 <= now - when < cfg.get("gate_retry_ticks", 14 * TICKS_PER_DAY):
            continue
        why = "thieves or snatchers have been seen" if seen else "the world has goblins (snatchers)"
        proposals.append(Proposal("traps", {"type": "place_traps", "entrance_id": e["id"], "kind": "cage",
                                            "count": _c(cfg, "thief_traps")},
                                  f"{why}: {_c(cfg, 'thief_traps')} cage traps behind the gate at x{e.get('x')} "
                                  f"y{e.get('y')}", 5))
        return


def _interrupters(s, cfg, t, memory, proposals, notes):
    """(item1, 14 Nov) B lost 66 citizens to thirst in 13 Nov's 17:05-17:45
    with 845 drinks in store: a visitor beaten in a fight with a squad (a
    human spearman told of an artifact) stayed by the stores, and DF made
    every dwarf who saw him drop the drink or meal on the way ("cancels
    Drink: Interrupted by a human spearman", ~4900 times in two months). He
    was no invader and not isDanger: the AI saw no threat. The bridge reads
    those cancellations (lua/ai-threats.lua interrupters_report) and names
    the unit; a squad is sent at it (kill_target_ok takes it). A merchant or
    diplomat is never attacked: said instead. With dwarves parched or
    starving, why their Drink and Eat jobs were cancelled is said too."""
    it = _d(t.get("interrupters"))
    if not it or it.get("error"):
        return
    so = _d(s.get("society"))
    parched, starving = int(so.get("parched") or 0), int(so.get("starving") or 0)
    rows = [x for x in _l(it.get("list")) if isinstance(x, dict) and x.get("id") is not None]
    loose = [x for x in rows if not x.get("caged")]
    for x in rows:
        if x.get("caged"):
            notes.append(f"{x.get('name')} keeps the dwarves from their drink and food ({x.get('cancels')} jobs "
                         "dropped) though caged or chained: move the cage out of their sight")
    talks = [x for x in loose if x.get("merchant") or x.get("diplomat")]
    for x in talks:
        notes.append(f"{x.get('name')} ({'a merchant' if x.get('merchant') else 'a diplomat'}) keeps the dwarves "
                     f"from their drink and food ({x.get('cancels')} jobs dropped, {x.get('dwarves')} dwarves): not "
                     "attacked (a merchant or diplomat); look at it in the game")
    hit = [x for x in loose if x not in talks and x.get("kill_ok") is not False]
    if hit:
        names = ", ".join(f"{x.get('name')} ({x.get('drink') or 0} drinks, {x.get('eat') or 0} meals dropped "
                          f"by {x.get('dwarves') or 0} dwarves)" for x in hit[:3])
        ids = [x["id"] for x in hit][:10]
        squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)]
        on_it = [q for q in squads if q.get("ai_orders") and set(_l(q.get("kill_ids"))) & set(ids)]
        able = _able_squads(s, cfg)
        busy = [q for q in squads if can_fight(q, cfg) and q.get("ai_orders") and not q.get("guarding")
                and isinstance(q.get("kill_ids"), list)]
        why = "keeps the dwarves from their drink and food (DF drops the job when they see it)"
        if on_it:
            notes.append(f"{names} {why}: {on_it[0].get('name') or 'a squad'} is after them")
        elif able:
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": able[0]["id"], "kill": ids},
                                      f"{names} {why}: send {able[0].get('name') or 'the squad'}", 0, guard=True))
        elif busy:
            q = busy[0]
            kill = list(dict.fromkeys(ids + [k for k in q["kill_ids"] if isinstance(k, int)]))[:50]
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": kill},
                                      f"{names} {why} and no squad free: {q.get('name') or 'the squad'} takes "
                                      "them on too", 0, guard=True))
        elif _weak_free(s) is not None:
            q = _weak_free(s)
            proposals.append(Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": ids},
                                      f"{names} {why} and no squad with {cfg.get('min_squad_to_fight', 3)}+ armed "
                                      f"free: send {q.get('name') or 'the squad'} "
                                      f"({_d(q.get('power')).get('armed')} armed)", 0, guard=True))
        else:
            ask_player(notes, f"{names} {why}, and the fort has no squad to send: draft one, or deal with it "
                              "in the game")
    if parched or starving:
        bits = []
        for job in ("drink", "eat"):
            rs = [r for r in _l(_d(it.get("reasons")).get(job)) if isinstance(r, dict) and r.get("why")]
            if rs:
                bits.append(f"{job.title()} jobs dropped: " + "; ".join(f"{r['why']} x{r.get('n')}" for r in rs[:3]))
        if bits:
            notes.append(f"{parched} parched, {starving} starving; in the last {it.get('window_days') or 2} days "
                         + " | ".join(bits))


def _undead(s, cfg, t, proposals, notes):
    u = _d(t.get("undead"))
    if int(u.get("undead") or 0):
        notes.append(f"{u['undead']} of the walking dead on the map")
    if u.get("reanimating"):
        n = int(u.get("surface_corpses") or 0)
        if n:
            notes.append(f"the land here raises its dead: {n} body/bodies lie outside")
        if (n >= _c(cfg, "reanimate_corpses") and not reachable_threats(s, _traits(s), cfg)
                and not int(u.get("undead") or 0)):
            proposals.append(Proposal("reanimation", {"type": "prune_remains"},
                                      f"{n} bodies lie outside in a land that raises its dead: rot them away "
                                      "before they walk (entombed dead are kept)", 4))


def _were(s, cfg, t, rules, proposals, notes):
    w = _d(t.get("were"))
    rows = [x for x in _l(w.get("list")) if isinstance(x, dict) and x.get("id") is not None]
    cells = [x for x in _l(w.get("cells")) if isinstance(x, dict)]
    if not rows and not cells:
        return
    due = moon_due(_l(w.get("changes")), abs_tick(s), cfg)
    if rows and due is None:
        notes.append(f"{len(rows)} werebeast citizen(s): no change seen yet, so the full moon isn't known "
                     f"(moon phase {w.get('moon_phase')}); the first change teaches it")
    if not rules["moon_cells"]:
        if cells:
            proposals.append(Proposal("moon_cell", {"type": "moon_cell", "ids": [], "release": True},
                                      "moon cells are off on the Rules tab: let every werebeast out", 1))
        return
    if due:
        want = [x["id"] for x in rows if not x.get("changed")]
        locked = all(x.get("cell") and x.get("locked") for x in rows if not x.get("changed"))
        if want and not locked:
            # (0.105.0 review) the changed ones' ids sent too, so their cells are kept
            ids = want + [x["id"] for x in rows if x.get("changed") and x.get("cell")]
            proposals.append(Proposal("moon_cell", {"type": "moon_cell", "ids": ids},
                                      f"the full moon is near: {', '.join(str(x.get('name')) for x in rows[:3])} "
                                      "into a cell (a jail or a free bedroom, locked once inside)", 1))
    elif cells and not any(x.get("changed") for x in rows):
        proposals.append(Proposal("moon_cell", {"type": "moon_cell", "ids": [], "release": True},
                                  f"the full moon is past: let {len(cells)} werebeast(s) out of their cells", 3))


ALL_CAVERNS = "all caverns"        # (0.105.26) the seal's record: every cavern opening on record
GREAT_KINDS = ("forgotten beast", "titan", "megabeast", "demon")


def alarm_held(s: dict, memory, cfg: dict) -> str:
    """(0.105.36) Why the plan keeps the alarm up this cycle ("" if nothing
    does): a threat that can reach the dwarves (not one the player cleared),
    a berserk dwarf, fire, flooding or the like (hazard_alert), this round's
    undead, cloud or surface beast (threat_alert, within its cap), citizens
    in the caverns with a great beast loose (within its cap). The
    strategist's alarm-off came after plan() and got past all of them
    (select() holds it with this)."""
    from planner_military import hazard_alert
    now = abs_tick(s)
    if "others_on_map" not in _d(s.get("_errors")):
        ids = [i for i in reachable_threats(s, _traits(s), cfg)
               if memory is None or i not in (getattr(memory, "alert_suppressed", None) or [])]
        if ids:
            return f"{len(ids)} threat(s) can reach the dwarves"
    why = hazard_alert(s, cfg)
    if why:
        return why
    why = threat_alert(s, cfg)
    if why:
        since = _d(getattr(memory, "threat_alarm", None)).get("since")
        if not (isinstance(since, int) and not isinstance(since, bool)
                and (now - since) // TICKS_PER_DAY >= _c(cfg, "threat_alarm_max_days")):
            return why
    from planner_weather import weather_held        # (0.105.40b) evil weather's spell
    why = weather_held(s, memory, cfg)
    if why:
        return why
    t = _d(s.get("threats"))
    caverns = [c for c in _l(_d(s.get("deep")).get("caverns")) if isinstance(c, dict)]
    down = cavern_down(t, caverns)
    great = cavern_great(s)
    if down and great and cavern_at_risk(down, great, caverns):       # (item4) only those it could come at
        since = _d(getattr(memory, "cavern_alarm", None)).get("since")
        if not (isinstance(since, int) and not isinstance(since, bool)
                and (now - since) // TICKS_PER_DAY >= _c(cfg, "cavern_alarm_max_days")) \
                and not cavern_realarm_wait(memory, now, cfg):
            return f"{len(down)} citizen(s) are in the caverns with a great beast loose"
    return ""


def cavern_down(t: dict, caverns: list) -> list:
    """(0.105.51) The citizens the bridge says are down in the caverns, less
    any whose level is in no cavern layer while the layers' levels are known.
    R3 (15 Nov, A B C E F): fisherdwarves and others at the surface river
    (elevation 32, z 161; Cavern1 is z 123-146) were read as in the caverns
    (the river's tiles are a map feature's too), and the alarm went up and
    down again for each (the bridge now asks for a cavern layer's tile)."""
    down = [x for x in _l(_d(t.get("cavern_citizens")).get("list")) if isinstance(x, dict)]
    rng = [(min(c["z_top"], c["z_bottom"]), max(c["z_top"], c["z_bottom"])) for c in caverns
           if isinstance(c, dict) and _num(c.get("z_top")) and _num(c.get("z_bottom"))]
    if not rng:
        return down
    return [x for x in down if not _num(x.get("z")) or any(lo <= x["z"] <= hi for lo, hi in rng)]


def cavern_realarm_wait(memory, now, cfg) -> bool:
    """(0.105.51) The alarm was let down for citizens in the caverns (held its
    `cavern_alarm_max_days`) less than `cavern_realarm_days` ago: no new
    alarm for the next one to go down (R3: up for 3 days, down, up again for
    the next fisherdwarf, A 6 B 4 C 5 E 2 times); the ways down are locked."""
    lifted = _d(getattr(memory, "cavern_alarm", None)).get("lifted")
    if not isinstance(lifted, int) or isinstance(lifted, bool) or not isinstance(now, int):
        return False
    return 0 <= now - lifted < _c(cfg, "cavern_realarm_days") * TICKS_PER_DAY


def cavern_great(s: dict) -> list:
    """(0.105.26) The forgotten beasts and other great dangers loose in the
    caverns (in a cavern layer; a forgotten beast anywhere: it comes from
    there and tunnels)."""
    out = []
    held = set(_l(_d(s.get("lures")).get("held_beasts")))      # (0.105.45) shut in a lure pocket: cut off
    for x in _l(_d(s.get("deep")).get("dangers")):
        if not isinstance(x, dict) or x.get("caged") or x.get("kind") not in GREAT_KINDS:
            continue
        if x.get("id") in held:
            continue
        if str(x.get("layer") or "").startswith("Cavern") or x.get("kind") == "forgotten beast":
            out.append(x)
    return out


def cavern_at_risk(down: list, great: list, caverns: list) -> list:
    """(item4) The citizens down in the caverns a loose great beast could
    come at. Left out only one known to be in another cavern layer (by the
    layers' levels) than every such beast, none of which can walk to the
    dwarves; anyone whose place can't be told (no layer, no levels, a level
    in no known layer) counts."""
    rng = {}
    for c in caverns:
        if isinstance(c, dict) and _num(c.get("z_top")) and _num(c.get("z_bottom")):
            rng[c.get("name")] = (min(c["z_top"], c["z_bottom"]), max(c["z_top"], c["z_bottom"]))
    out = []
    for x in down:
        z = _d(x).get("z")
        here = next((n for n, r in rng.items() if _num(z) and r[0] <= z <= r[1]), None)
        for b in great:
            b = _d(b)
            if b.get("can_reach_dwarves") is True or here is None or b.get("layer") not in rng or b.get("layer") == here:
                out.append(x)
                break
    return out


def deep_read(s: dict) -> bool:
    """(0.105.33) The deep section read this cycle: present, and not the
    {error=...} a failed get_deep sends. Without it no beast is seen, which
    is not the same as none being there."""
    d = s.get("deep")
    return isinstance(d, dict) and "error" not in d and "deep" not in _d(s.get("_errors"))


def _cavern_doors(s, memory, proposals, notes, cfg=None) -> None:
    """(0.105.26) Every opening onto a cavern gets a lockable door or hatch
    straight away (the gates scan finds them), not only once a beast is seen:
    put on before the gate rule's turn comes, each once."""
    if not player_rules(s)["build_gate_doors"]:
        return
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    asked = set(getattr(memory, "gate_doors_requested", None) or [])
    fails = getattr(memory, "gate_failures", None) or {}
    fail_ticks = getattr(memory, "gate_failure_ticks", None) or {}
    retry = _d(cfg).get("gate_retry_ticks", PLANNER_CONFIG["gate_retry_ticks"])
    now = abs_tick(s)
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict) or e.get("kind") != "cavern" or e.get("sealed") or e.get("closing"):
            continue
        spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
        if not e.get("door_spots") or spot in asked or e.get("id") is None:
            continue
        if spot in fails:
            # (0.105.33) a refusal is tried again after `gate_retry_ticks`, as
            # the gate rule does (an undated one: from before, tried again)
            when = fail_ticks.get(spot)
            if isinstance(when, int) and isinstance(now, int) and 0 <= now - when < retry:
                continue
        proposals.append(Proposal("cavern_openings", {"type": "build_gate_doors", "entrance_id": e["id"]},
                                  f"the fort is open to a cavern at x{e.get('x')} y{e.get('y')} elevation "
                                  f"{(e.get('z') or 0) + off}: {e['door_spots']} door(s) or hatch(es) on it now, "
                                  "to be locked whenever a forgotten beast is about", 2))
        return


def _cavern_beasts(s, cfg, memory, t, rules, proposals, notes):
    """(0.105.26) F lost 54 and C 12 to forgotten beasts that came in through
    caverns the AI opened. While a forgotten beast or other great danger is
    loose in the caverns, every cavern opening on record (the bridge keeps
    them: the gates' cavern entrances, the doors and hatches on the way down)
    is locked, whatever the squads could do; not while citizens are down
    there (the player is told). A cavern well's shaft is shut by its own
    watcher meanwhile (no water through it). Opened again once it's gone."""
    d = _d(s.get("deep"))
    sealed = _d(t.get("sealed"))
    _cavern_doors(s, memory, proposals, notes, cfg)
    if not rules["seal_caverns"]:
        for name in sealed:
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                      "sealing the caverns is off on the Rules tab: unlock the way down", 3))
        return
    if not deep_read(s):
        # (0.105.33) get_deep failed (or wasn't sent): the seals stay as they
        # are until a good read says the caverns are clear
        if sealed:
            err = str(_d(s.get("deep")).get("error") or _d(s.get("_errors")).get("deep") or "not in the report")
            notes.append(f"the caverns couldn't be read this cycle ({err[:80]}): the ways into them stay "
                         "locked until they can")
        return
    great = cavern_great(s)
    caverns = [c for c in _l(d.get("caverns")) if isinstance(c, dict)]
    ops = [o for o in _l(_d(t.get("openings")).get("list")) if isinstance(o, dict)]
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    if great:
        beast = great[0]
        who = f"{beast.get('name') or 'a great beast'} ({beast.get('kind')}" + (
            f", in {beast['layer']})" if beast.get("layer") else ")")
        tiles, seen = [], set()
        for c in caverns:
            if c.get("open"):
                for p in seal_tiles(c):
                    k = tuple(p.get(q) for q in ("x", "y", "z"))
                    if all(_num(v) for v in k) and k not in seen:
                        seen.add(k)
                        tiles.append({"x": p["x"], "y": p["y"], "z": p["z"]})
        # (0.105.51) not a cavern well's door the seal leaves open (its shaft gate keeps the
        # cavern out, or a dwarf is beyond it): R3 counted "1 door on record, 1 open" and the
        # bridge refused "no door or hatch on the way down to lock" (A 12, B 9, C 7, E 7)
        lockable = seal_lockable_rows(ops)
        # (a door reads closed whenever nobody passes: only the lock, or the seal's own lever pull, counts)
        # (0.105.45) a door a lure holds open (lua/ai-lure.lua, its phase "open") is open on purpose:
        # the lure locks it again itself (planner_lure)
        unlocked = [o for o in lockable if o.get("built") is not False and not o.get("locked") and not o.get("sealed")
                    and not o.get("lure_open")]
        down = cavern_down(t, caverns)
        # (v35 fix) the alarm is held for them `cavern_alarm_max_days` at most:
        # then let down and the ways locked (whoever can't climb out is the
        # stranded rules': their gate opened once the caverns hold no great danger)
        held_days, over, rewait = 0, False, False
        if memory is not None:
            ca = memory.cavern_alarm if isinstance(getattr(memory, "cavern_alarm", None), dict) else {}
            now = abs_tick(s)
            # (0.105.51) the last let-down is kept (cavern_realarm_wait)
            lifted = {"lifted": ca["lifted"]} if cavern_realarm_wait(memory, now, cfg) else {}
            if down and (ALL_CAVERNS not in sealed or unlocked):
                since = ca.get("since")
                if not isinstance(since, int) or isinstance(since, bool) or since > now:
                    since = now
                    memory.cavern_alarm = dict(lifted, since=now)
                held_days = (now - since) // TICKS_PER_DAY
                over = held_days >= _c(cfg, "cavern_alarm_max_days")
                if over and not lifted:
                    memory.cavern_alarm = dict(memory.cavern_alarm, lifted=now)
                elif not over and lifted:
                    over = rewait = True
            elif ca != lifted:
                memory.cavern_alarm = lifted
        if rewait:
            n = int(_d(t.get("cavern_citizens")).get("n") or len(down))
            notes.append(f"{who} is about and {n} citizen(s) went down into the caverns again: the alarm was let "
                         f"down for the caverns less than {_c(cfg, 'cavern_realarm_days')} days ago and isn't "
                         "raised again so soon (the whole fort would stop); the ways down are locked, and whoever "
                         "can't climb out is let in by their gate once the caverns hold no great danger")
            down = []
            reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
            from planner_military import hazard_alert
            other = hazard_alert(s, cfg) or threat_alert(s, cfg)
            if (s.get("civ_alert") and getattr(memory, "ai_alert_raised", False) and not reach and not other
                    and not any(p.action == {"type": "civ_alert", "on": False} for p in proposals)):
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                          "the alarm was held for citizens in the caverns not long ago: it "
                                          "comes down, and the ways down are locked", 0))
        elif over:
            n = int(_d(t.get("cavern_citizens")).get("n") or len(down))
            # (0.105.36) not while another danger holds the alarm (a berserk
            # dwarf, a werebeast, fire, a cloud, the undead): every other
            # release checks them, and it flipped on and off
            from planner_military import hazard_alert
            other = hazard_alert(s, cfg) or threat_alert(s, cfg)
            notes.append(f"{who} is about and {n} citizen(s) are still in the caverns after {held_days} day(s) of "
                         + (f"the alarm: the AI locks the ways down (the fort can't wait on them; the alarm stays "
                            f"up for {other}); " if other else
                            "the alarm: the AI lets the alarm down and locks the ways down (the fort can't wait on "
                            "them); ")
                         + "whoever can't climb out is let in by their gate once the caverns hold no great danger")
            down = []
            reach = int(_d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or 0)
            if (s.get("civ_alert") and getattr(memory, "ai_alert_raised", False) and not reach and not other
                    and not any(p.action == {"type": "civ_alert", "on": False} for p in proposals)):
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": False},
                                          f"the alarm held {held_days} day(s) for citizens in the caverns: it comes "
                                          "down, and the ways down are locked", 0))
        # (0.105.54) the kill plan: the seal held open for a fight under way
        hunting = False
        try:
            hunting = _beast_hunt(s, cfg, memory, t, great, ops, down, sealed, unlocked, proposals, notes)
        except Exception as e:  # noqa: BLE001  (the seal as before)
            notes.append(f"the beast plan failed ({type(e).__name__}: {str(e)[:80]})")
        if hunting:
            pass
        elif ALL_CAVERNS not in sealed or unlocked:
            if down:
                n = int(_d(t.get("cavern_citizens")).get("n") or len(down))
                where = ", ".join(f"{_d(x).get('name')} at x{_d(x).get('x')} y{_d(x).get('y')} "
                                  f"elevation {(_d(x).get('z') or 0) + off}" for x in down[:3])
                # (0.105.35) the AI calls them up itself: the alarm sends the
                # civilians into the shelter (inside the fort), and holds while
                # they are down there; the ways are locked once they're out
                risk = cavern_at_risk(down, great, caverns)
                if risk:
                    proposals[:] = [p for p in proposals if p.action != {"type": "civ_alert", "on": False}]
                if not risk and not s.get("civ_alert"):
                    # (item4) F (13 Nov): 110 alarms for beasts in Cavern1 while a fisherdwarf was
                    # in another layer, each lifted a minute later: none for a beast that can't come at them
                    notes.append(f"{who} is about and {n} citizen(s) are in the caverns ({where}), none where "
                                 "it is: no alarm (the whole fort would stop); the ways down are locked once "
                                 "they're out")
                elif s.get("civ_alert"):
                    notes.append(f"{who} is about and {n} citizen(s) are still in the caverns ({where}): the alarm "
                                 "calls them up; the ways down are locked once they're out")
                elif s.get("civ_alert_ready") is True:
                    if not any(p.action == {"type": "civ_alert", "on": True} for p in proposals):
                        proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                                  f"{who} is about and {n} citizen(s) are in the caverns ({where}): "
                                                  "sound the alarm to call them up, then lock the ways down", 0))
                    notes.append(f"{who} is about and {n} citizen(s) are in the caverns: the alarm calls them up "
                                 "before the ways down are locked")
                else:
                    from planner_military import no_shelter
                    no_shelter(s, memory, f"{who} is about and {n} citizen(s) are in the caverns ({where})",
                               proposals, notes)
            elif ((not lockable or _seal_refused_none(memory, s)) and not _seal_has_lock(caverns)
                  and (tiles or any(c.get("open") for c in caverns))):
                # (item7) nothing on the way down to lock: B, E and A (13 Nov)
                # were refused "no door or hatch on the way down to lock" over
                # and over. The AI closes the way itself first (a door, or the
                # opening walled when nobody needs it), or says why it needn't
                _cavern_close_way(s, who, caverns, proposals, notes)
            elif (tiles or lockable) and not _seal_refused_none(memory, s):
                act = {"type": "seal_cavern", "layer": ALL_CAVERNS, "openings": True}
                if tiles:
                    act["tiles"] = tiles[:20]
                zs = [(c["z_bottom"], c["z_top"]) for c in caverns if _num(c.get("z_top")) and _num(c.get("z_bottom"))]
                if zs:
                    act["z1"], act["z2"] = int(min(z[0] for z in zs)), int(max(z[1] for z in zs))
                proposals.append(Proposal("seal_cavern", act,
                                          f"{who} is on the map: lock every way into the caverns "
                                          f"({len(lockable)} door(s) and hatch(es) on record"
                                          + (f", {len(unlocked)} open" if unlocked else "")
                                          + "), whatever the squads could do", 1))
            elif any(c.get("open") for c in caverns):
                # (0.105.35) the AI maps the entrances again (a cavern opening it
                # finds gets its door or hatch, _cavern_doors); only when a fresh
                # map finds none is the player told, with what the AI does
                ent = _d(s.get("entrances"))
                age = (abs_tick(s) - ent["scanned_tick"]) if isinstance(ent.get("scanned_tick"), int) else None
                if age is None or not 0 <= age < TICKS_PER_DAY:
                    proposals.append(Proposal("cavern_scan", {"type": "scan_entrances"},
                                              f"{who} is about and the fort is open to the caverns with no door or "
                                              "hatch known on the way down: map the entrances again to find the "
                                              "openings and put doors on them", 1))
                else:
                    ask_player(notes, f"{who} is about and the fort is open to the caverns, but the entrances "
                                      "mapped today show no spot for a door or hatch on the way down, and the AI "
                                      "can't wall an opening it hasn't mapped; meanwhile it maps them again each "
                                      "day and puts a door on any opening it finds")
            elif not lockable and any(o.get("kind") == "well" or o.get("seal_skip") or o.get("well_blocked")
                                      for o in ops):
                # (r2h7) R3: the only ways down on record were the cavern well's: its shaft
                # hatch (worked by its watcher) and its door (left open: the shaft gate keeps
                # the cavern out). Said, not asked of the bridge (refused 24 of 24)
                notes.append(f"{who} is about: the only way down on record is the cavern well, whose shaft gate "
                             "shuts by itself when a danger comes near it; nothing else to lock")
        shafts =[x for x in _l(_d(s.get("projects")).get("well_lids")) if isinstance(x, dict)
                  and x.get("gate") in ("open", "closed", "pulling")]
        # (group 2) a bridge that judges the shaft itself shuts it only for a
        # danger that could come up it (not for every beast in the caverns): said
        # only for a shaft shut now
        if shafts and any((x.get("watch_rule") or 0) >= 2 for x in shafts):
            shafts = [x for x in shafts if x.get("gate") in ("closed", "pulling")]
        if shafts:
            notes.append(f"the cavern well's shaft is shut while {who} is about: the well draws no water until "
                         "it's gone (then it's opened again)")
            patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
            wells = int(_d(_d(s.get("buildings")).get("other")).get("Well") or 0)
            if patients and wells <= len(shafts):
                # (0.105.35) said, not asked: the water rule marks the nearest
                # open water (not the caverns') a water source meanwhile, and the
                # wells rule places another well
                notes.append(f"{patients} injured dwarves need water and the only well is the cavern well, "
                             f"shut against {who}: the nearest open water outside the caverns is made a water "
                             "source meanwhile, and another well is placed when it can be")
    else:
        _hunt_over(s, memory, notes)
        if ALL_CAVERNS in sealed:
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": ALL_CAVERNS, "open": True},
                                      "no forgotten beast or other great danger left in the caverns: the ways "
                                      "into them opened again", 3))
    # seals from before 0.105.26, one per layer: opened once no great beast is in that layer
    here = {x.get("layer") for x in great}
    names = {c.get("name") for c in caverns}
    for name, rec in sealed.items():
        if name == ALL_CAVERNS:
            continue
        if name in names and name not in here:
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                      f"no great beast left in {name}: unlock the way down again", 3))
        elif name not in names:
            # (0.105.0 review) a sealed layer the deep report no longer lists: unlocked after some days
            days = _d(rec).get("days")
            if _num(days) and days >= _c(cfg, "seal_missing_days"):
                proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                          f"{name} sealed {days} days and no longer in the deep report: unlock "
                                          "the way down", 3))


# --- (0.105.54) the beast killed, not only hidden from -------------------------

def _threat_row(s: dict, bid) -> dict:
    """The others_on_map row of a threat (its facts), {} if none."""
    for o in _l(_d(s.get("others_on_map")).get("threats")):
        if isinstance(o, dict) and o.get("id") == bid and bid is not None:
            return o
    return {}


def _pos(b: dict):
    p = _d(b.get("pos"))
    if all(_num(p.get(k)) for k in ("x", "y", "z")):
        return p
    if all(_num(b.get(k)) for k in ("x", "y", "z")):
        return {"x": b["x"], "y": b["y"], "z": b["z"]}
    return None


def _far(a, b) -> float:
    if not a or not b or not all(_num(_d(b).get(k)) for k in ("x", "y", "z")):
        return 1e9
    return abs(a["x"] - b["x"]) + abs(a["y"] - b["y"]) + 3 * abs(a["z"] - b["z"])


def _hunt_doors(t: dict) -> list:
    """The seal's doors and hatches on the ways down (what the squads hold)."""
    # (r2h7) the seal's own test (seal_lockable_rows): what it can lock, the squads hold
    return [o for o in seal_lockable_rows(_l(_d(t.get("openings")).get("list")))
            if o.get("building") in ("Door", "Hatch") and o.get("built") is not False
            and all(_num(o.get(k)) for k in ("x", "y", "z"))]


def _cavern_posts(s: dict) -> list:
    """The cavern openings with fortifications and posts behind them (the kill
    zones report's survey): where crossbows shoot at a beast coming up."""
    return [e for e in _l(_d(s.get("killzones")).get("entrances")) if isinstance(e, dict) and e.get("kind") == "cavern"
            and int(e.get("posts") or 0) > 0 and e.get("id") is not None and not e.get("error")]


def beast_tactic(s: dict, memory, cfg: dict, beast: dict) -> dict:
    """(0.105.54) The kill plan for one great beast (planner_matchup.beast_plan
    on its facts and the squads not on the player's orders), checked against
    the fort: a ranged plan needs a fortified cavern opening, a melee one a
    door on the way down; a fight called off before isn't tried again while
    it is here. Adds `squads` (ids), `door` or `post`, `name`, `destroyer`."""
    from planner_matchup import beast_plan, fight_bar_of
    from planner_military import _players, called_off_ids, fight_key
    row = dict(_d(beast))
    row.update({k: v for k, v in _threat_row(s, row.get("id")).items() if v is not None})
    lure_b = next((b for b in _l(_d(s.get("lures")).get("beasts")) if isinstance(b, dict)
                   and b.get("id") == row.get("id")), {})
    avoid = lure_b.get("immune") if isinstance(lure_b.get("immune"), bool) else None
    if row.get("destroyer") is None and lure_b.get("destroyer") is not None:
        row["destroyer"] = lure_b.get("destroyer")
    squads = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)
              and can_fight(q, cfg) and not _players(q)]
    ff = _d(getattr(memory, "fight_factor", None)) if memory is not None else {}
    plan = beast_plan(row, squads, fight_bar_of(s, memory, cfg),
                      lambda x: float(ff.get(fight_key(x)) or 1.0), trap_avoid=avoid)
    plan["name"] = str(row.get("name") or row.get("kind") or "a great beast")
    plan["destroyer"] = bool(row.get("destroyer"))
    avoid = row.get("trap_avoid") if avoid is None else avoid

    def hold(missing):
        plan.update(ready=False, tactic="lure" if avoid else "cage")
        plan["missing"] = [missing] + [m for m in plan["missing"] if m != missing]
    if row.get("id") in called_off_ids(s, memory):
        hold("a fight it doesn't win (the last one was called off)")
    at = _pos(row)
    if plan["ready"] and plan["tactic"] == "ranged":
        posts = sorted(_cavern_posts(s), key=lambda e: _far(at, e))
        if posts:
            plan["post"] = posts[0]
            plan["squads"] = [q["id"] for q in squads if squad_ranged(q)]
        else:
            hold("fortifications at a cavern opening (the crossbows shoot through them)")
    if plan["ready"] and plan["tactic"] == "melee":
        doors = sorted(_hunt_doors(_d(s.get("threats"))), key=lambda o: _far(at, o))
        if doors:
            plan["door"] = {k: doors[0][k] for k in ("x", "y", "z")}
            plan["squads"] = [q["id"] for q in squads]
        else:
            hold("a door on the way down for the squads to hold")
    plan.setdefault("squads", [])
    return plan


def squad_ranged(q: dict) -> bool:
    """A squad that shoots: the AI's crossbow uniform, or more ranged power than melee."""
    from planner_matchup import shoots
    return shoots(q)


def _plan_words(plan: dict) -> str:
    from planner_matchup import TACTIC_WORDS
    w = f"the plan is {TACTIC_WORDS.get(plan.get('tactic'), plan.get('tactic'))}"
    if not plan.get("ready") and plan.get("goal") and plan.get("goal") != plan.get("tactic"):
        w += f", building toward {TACTIC_WORDS.get(plan['goal'], plan['goal'])}"
    return w


def _hunt_over(s: dict, memory, notes: list) -> None:
    """No great beast left in the caverns: the plan's record ends (said once
    when the seal had been opened for it)."""
    if memory is None:
        return
    h = getattr(memory, "beast_hunt", None)
    if isinstance(h, dict) and h:
        if h.get("stage") == "open":
            notes.append(f"{h.get('name') or 'the great beast'} is gone from the caverns (killed or fled) after "
                         f"the seal was opened for the fight ({h.get('tactic')})")
        memory.beast_hunt = {}


def _beast_hunt(s, cfg, memory, t, great, ops, down, sealed, unlocked, proposals, notes) -> bool:
    """(0.105.54) The sealed beast's kill plan, acted on. True while the seal is
    held open for the fight (the lock is not asked again meanwhile)."""
    if memory is None or not great:
        return False
    h = memory.beast_hunt if isinstance(getattr(memory, "beast_hunt", None), dict) else {}
    now = abs_tick(s)
    if not isinstance(now, int):
        return False
    loose = [b for b in great if not b.get("caged")]
    if len(loose) != 1:
        if h.get("stage") == "open":
            h.update(stage="sealed", retry=now)
            memory.beast_hunt = h
            notes.append(f"{len(loose)} great beasts below: the seal is locked again (one is fought at a time)")
            return False
        notes.append(f"{len(loose)} great beasts below: the caverns stay sealed (the AI opens them for one at a time)")
        return False
    b = loose[0]
    if h.get("id") != b.get("id"):
        h = {"id": b.get("id"), "stage": "sealed", "since": now}
    plan = beast_tactic(s, memory, cfg, b)
    who = plan["name"]
    h.update(name=who, tactic=plan["tactic"], goal=plan.get("goal"))
    memory.beast_hunt = h
    extra = " (it breaks doors: the seal may not hold it)" if plan.get("destroyer") else ""
    called = b.get("id") in __import__("planner_military").called_off_ids(s, memory)
    if h.get("stage") == "open":
        days = (now - int(h.get("opened") or now)) // TICKS_PER_DAY
        able = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)
                and q.get("id") in set(_l(h.get("squads"))) and can_fight(q, cfg)]
        why = ("citizens went down into the caverns" if down else
               "the fight went badly (called off)" if called else
               "no squad able to fight is left" if not able else
               f"it was open {days} day(s) and {who} never came" if days >= _c(cfg, "beast_open_days") else "")
        if why:
            h.update(stage="sealed", retry=now + _c(cfg, "beast_retry_days") * TICKS_PER_DAY)
            notes.append(f"{who}: the seal opened for the fight is locked again ({why}); "
                         f"{_plan_words(plan)}")
            return False
        if plan["tactic"] == "melee" or h.get("tactic") == "melee":
            on = {x for q in able for x in _l(q.get("kill_ids"))}
            if b.get("id") not in on:
                for q in able:
                    if not any(p.action.get("squad_id") == q["id"] for p in proposals):
                        proposals.append(Proposal("beast_hunt", {"type": "squad_orders", "squad_id": q["id"],
                                                                 "kill": [b["id"]]},
                                                  f"{who}: the seal is open for the fight: "
                                                  f"{q.get('name') or 'the squad'} goes at it", 0))
        notes.append(f"{who}{extra}: {_plan_words(plan)}; stage: the seal is open for the fight "
                     f"({days} day(s)), {len(able)} squad(s) on it")
        return True
    sealed_now = ALL_CAVERNS in sealed and not unlocked
    if not sealed_now:
        notes.append(f"{who}{extra}: {_plan_words(plan)}; stage: sealing it out first")
        return False
    retry = h.get("retry")
    if isinstance(retry, int) and now < retry:
        notes.append(f"{who}{extra}: kept sealed; {_plan_words(plan)}; stage: the last try was shut "
                     f"{max(1, (retry - now) // TICKS_PER_DAY)} day(s) before the next")
        return False
    if not plan["ready"]:
        h["stage"] = "trap"
        miss = "; ".join(plan.get("missing") or [])
        notes.append(f"{who}{extra}: kept sealed ({plan.get('why')}); {_plan_words(plan)}; stage: holding it"
                     + (f"; missing: {miss}" if miss else ""))
        return False
    if down:
        notes.append(f"{who}: {_plan_words(plan)} ({plan.get('why')}); stage: ready, waits until the citizens "
                     "are out of the caverns")
        return False
    others = [i for i in reachable_threats(s, _traits(s), cfg) if i != b.get("id")]
    if others:
        notes.append(f"{who}: {_plan_words(plan)}; stage: ready, waits while {len(others)} other threat(s) "
                     "can reach the dwarves")
        return False
    if any(isinstance(r, dict) and r.get("open") for r in _l(_d(s.get("lures")).get("lures"))):
        notes.append(f"{who}: {_plan_words(plan)}; stage: ready, waits while the lure is open")
        return False
    sq = {q.get("id"): q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict)}
    ids = [i for i in plan["squads"] if i in sq]
    if not ids:
        return False
    if plan["tactic"] == "melee":
        at = plan["door"]
        posted = [i for i in ids if {k: _d(sq[i].get("stationed")).get(k) for k in ("x", "y", "z")} == at]
        todo = [i for i in ids if i not in posted]
        where = f"the cavern door at x{at['x']} y{at['y']} z{at['z']}"
    else:
        e = plan["post"]
        posted = [i for i in ids if sq[i].get("guarding")]
        todo = [i for i in ids if i not in posted]
        where = f"the fortifications by the cavern opening at x{e.get('x')} y{e.get('y')} z{e.get('z')}"
    if todo:
        h.update(stage="posting", squads=ids)
        if plan["tactic"] == "melee":
            for i in todo:
                proposals.append(Proposal("beast_hunt", {"type": "squad_station", "squad_id": i, **at,
                                                         "what": f"cavern door, to fight {who}"[:60]},
                                          f"{who}: {_plan_words(plan)} ({plan.get('why')}): "
                                          f"{sq[i].get('name') or 'the squad'} takes its post at {where}", 1))
        else:
            proposals.append(Proposal("beast_hunt", {"type": "archer_post", "entrance_id": e["id"], "squads": todo[:6]},
                                      f"{who}: {_plan_words(plan)} ({plan.get('why')}): the crossbows take their "
                                      f"post behind {where}", 1))
        notes.append(f"{who}{extra}: {_plan_words(plan)}; stage: the squads take their posts at {where} "
                     "(the seal opens once they're there)")
        return False
    h.update(stage="open", opened=now, squads=ids)
    proposals.append(Proposal("beast_hunt", {"type": "seal_cavern", "layer": ALL_CAVERNS, "open": True},
                              f"{who}: {_plan_words(plan)} ({plan.get('why')}); the squads are posted at "
                              f"{where}: open the ways into the caverns for the fight", 1))
    if plan["tactic"] == "melee":
        for i in ids:
            proposals.append(Proposal("beast_hunt", {"type": "squad_orders", "squad_id": i, "kill": [b["id"]]},
                                      f"{who}: the seal opens for the fight: {sq[i].get('name') or 'the squad'} "
                                      "goes at it", 0))
    notes.append(f"{who}{extra}: {_plan_words(plan)}; stage: the squads are posted, the seal opens for the fight")
    return True


STAIRISH = ("STAIR", "RAMP")


def seal_lockable_rows(ops: list) -> list:
    """(r2h7) The openings the seal can lock, by the bridge's own test
    (ai-threats seal_lockable, which seal_cavern uses too): each row the
    openings report marks `lockable`. A row from an older bridge (no such
    field) is judged as 0.105.51 did: a door or hatch, not a cavern well's
    shaft hatch, not a well door the seal leaves open or a dwarf is beyond."""
    out = []
    for o in ops:
        if not isinstance(o, dict):
            continue
        if "lockable" in o:
            if o.get("lockable") is True:
                out.append(o)
        elif (o.get("kind") != "well" and o.get("building") in ("Door", "Hatch")
              and not o.get("seal_skip") and not o.get("well_blocked")):
            out.append(o)
    return out


SEAL_NONE_WHY = ("no door or hatch", "only cavern well doors")


def _seal_refused_none(memory, s) -> bool:
    """(0.105.51) The seal was refused "no door or hatch on the way down to
    lock" and its back-off still runs: not asked again meanwhile (R3: A 12,
    B 9, C 7, E 7, F 10 refusals) but the way down closed (a door built,
    _cavern_close_way) where the caverns are open to the fort."""
    for k, r in _d(getattr(memory, "refusals", None)).items():
        if (isinstance(k, str) and k.startswith("seal_cavern:") and isinstance(r, dict)
                and str(r.get("why") or "").startswith(SEAL_NONE_WHY)):
            until, now = r.get("until"), abs_tick(s)
            if isinstance(until, int) and isinstance(now, int) and now < until:
                return True
    return False


def _seal_has_lock(caverns: list) -> bool:
    """(item7) Is there anything seal_cavern could lock on the tiles it is
    given: a door or hatch in an open cavern's column, or junctions (the
    deep report doesn't say what stands on them: the bridge looks)."""
    for c in caverns:
        if not c.get("open"):
            continue
        if _l(c.get("junctions")):
            return True
        if any(isinstance(col, dict) and col.get("building") in ("Door", "Hatch") for col in _l(c.get("column"))):
            return True
    return False


CAVERN_SCAN_MAX_TILES = 250000          # lua/ai-gates.lua MAX_TILES: a map that stopped there is cut short


def cavern_way_state(s: dict) -> tuple[str, list]:
    """(item7) What the fort's own entrance map (the gates' walk from the
    citizens, through doors) says of the ways down to the caverns:
    ("stale", []) no map from today; ("none", []) the fort's ground reaches
    no cavern tile (a cavern 'open' to its walk is joined only through the
    cavern wells' lidded shafts or across the surface, behind the gates);
    ("closed", entrances) every cavern opening shut or being shut; ("open",
    entrances) the cavern openings nothing closes yet; ("unknown", []) the
    map stopped at its tile limit."""
    ent = _d(s.get("entrances"))
    st = ent.get("scanned_tick")
    if not isinstance(ent.get("entrances"), list) or not isinstance(st, int):
        return "stale", []
    if not 0 <= abs_tick(s) - st < TICKS_PER_DAY:
        return "stale", []
    if isinstance(ent.get("inside_tiles"), int) and ent["inside_tiles"] >= CAVERN_SCAN_MAX_TILES:
        return "unknown", []            # the map stopped at its limit: it can't say there is none
    cav = [e for e in ent["entrances"] if isinstance(e, dict) and e.get("kind") == "cavern"]
    if not cav:
        return "none", []
    open_ = [e for e in cav if not e.get("sealed") and not e.get("closing")]
    return ("open", open_) if open_ else ("closed", cav)


def _cavern_close_way(s, who, caverns, proposals, notes) -> None:
    """(item7) A great beast below and nothing on the way down to lock:
    the cavern openings the fort's walk finds get a door (lockable by a
    later seal) or, where no door can go, are walled for good (the bridge's
    sealed gate: refused while a citizen is beyond it, a cavern well or the
    cistern draws on that cavern, or the walls would cut the fort apart:
    nobody is shut out of drink or stranded); an older map is mapped anew
    first; with no way down from inside the fort, nothing is locked."""
    off = _d(s.get("map")).get("elevation_offset")
    off = off if isinstance(off, int) else 0
    state, ents = cavern_way_state(s)
    if state == "stale":
        if not any(p.action.get("type") == "scan_entrances" for p in proposals):
            proposals.append(Proposal("cavern_scan", {"type": "scan_entrances"},
                                      f"{who} is about and nothing on the way down to the caverns can be locked: "
                                      "map the entrances again to find the openings and close them", 1))
        return
    if state == "unknown":
        ask_player(notes, f"{who} is about and the fort is open to the caverns, but the entrance map stopped at "
                          "its limit before finding a way down; meanwhile the AI maps them again each day and puts a door "
                          "on any opening it finds")
        return
    if state == "none":
        names = ", ".join(str(c.get("name")) for c in caverns if c.get("open")) or "the caverns"
        notes.append(f"{who} is about: the fort's own ground has no way down to {names} (today's entrance map "
                     "finds none: the cavern joins the fort's walk only through the cavern wells' shafts, shut by "
                     "their lids, or across the surface, behind the fort's gates): nothing to lock")
        return
    if state == "closed":
        notes.append(f"{who} is about: the {len(ents)} cavern opening(s) are shut or being shut; the seal locks "
                     "their doors once built")
        return
    rules_ = player_rules(s)
    for e in ents:
        if e.get("id") is None:
            continue
        where = f"x{e.get('x')} y{e.get('y')} elevation {(e.get('z') or 0) + off}"
        if any(p.action.get("entrance_id") == e["id"] for p in proposals):
            return                       # the doors or a gate are asked for already this cycle
        if e.get("door_spots") and rules_.get("build_gate_doors", True):
            proposals.append(Proposal("cavern_openings", {"type": "build_gate_doors", "entrance_id": e["id"]},
                                      f"{who} is about and the cavern opening at {where} has nothing to lock: "
                                      f"{e['door_spots']} door(s) on it, for the seal to lock", 1))
        elif rules_.get("fortify_entrances", True):
            proposals.append(Proposal("cavern_openings", {"type": "fortify_entrance", "entrance_id": e["id"],
                                                          "style": "sealed"},
                                      f"{who} is about and the cavern opening at {where} ({e.get('width')} wide) "
                                      "takes no door: wall it up (not while a citizen is beyond it or the fort "
                                      "draws water from that cavern)", 1))
        else:
            notes.append(f"{who} is about and the cavern opening at {where} has nothing to lock; building doors "
                         "and gates is off on the Rules tab")
        return


def seal_tiles(c: dict) -> list:
    """(0.105.0 review) The tiles on the actual way down to a cavern: where
    it meets the fort (open_at), each junction (the fort's tile and the
    cavern's beside it), and the column above open_at only where it is a
    stair or ramp or holds a hatch - not every tile up to 6
    levels, whose doors may be any room's."""
    oa = _d(c.get("open_at"))
    out = [oa]
    for j in _l(c.get("junctions")):
        if isinstance(j, dict):
            out.append({k: j.get(k) for k in ("x", "y", "z")})
            if isinstance(j.get("cave"), dict):
                out.append({k: j["cave"].get(k) for k in ("x", "y", "z")})
    for col in _l(c.get("column")):
        if isinstance(col, dict) and (any(w in str(col.get("shape") or "").upper() for w in STAIRISH)
                                      or col.get("building") == "Hatch"):
            out.append({"x": oa.get("x"), "y": oa.get("y"), "z": col.get("z")})
    return out


def _rescue(s, cfg, t, proposals, notes):
    r = _d(t.get("rescue"))
    if r.get("error") or not isinstance(r.get("holders"), int):
        return
    if r["holders"] == 0 and r.get("mode") not in ("NobodyDoesThis", "EverybodyDoesThis"):
        proposals.append(Proposal("rescue_labor", {"type": "assign_labor", "job": "RECOVER_WOUNDED", "count": 2},
                                  "nobody outside the squads fetches the wounded (DF's Recover wounded labour): "
                                  "put 2 dwarves on it", 3 if r.get("down") else 5))
    if r.get("down"):
        notes.append(f"{r['down']} wounded dwarf/dwarves lie down waiting to be fetched "
                     f"({r['holders']} may fetch them)")


def _threat_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(0.105.0) Round 3's threats: fire, prisoners, thieves, the undead and
    evil weather, werebeasts, cavern beasts, surface dangers, the wounded."""
    t = _d(s.get("threats"))
    if not t or t.get("error"):
        return
    rules = threat_rules_of(s)
    for name, fn, args in (("fire", _fire, (s, cfg, t, proposals, notes)),
                           ("prisoners", _prisoners, (s, cfg, t, rules, proposals, notes)),
                           ("thieves", _thieves, (s, cfg, t, memory, proposals, notes)),
                           ("interrupters", _interrupters, (s, cfg, t, memory, proposals, notes)),
                           ("undead", _undead, (s, cfg, t, proposals, notes)),
                           ("were", _were, (s, cfg, t, rules, proposals, notes)),
                           ("caverns", _cavern_beasts, (s, cfg, memory, t, rules, proposals, notes)),
                           ("rescue", _rescue, (s, cfg, t, proposals, notes))):
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001  (one part failing leaves the others)
            notes.append(f"threat rule {name} failed ({type(e).__name__}: {str(e)[:100]})")
    # the alarm: up for the undead, an evil cloud or a surface beast; kept up while they last
    why = threat_alert(s, cfg)
    # (0.105.0 review) held at most threat_alarm_max_days: past that the AI lets
    # it down (0.105.35: said, not put to the player)
    if why:
        held = memory.threat_alarm if isinstance(getattr(memory, "threat_alarm", None), dict) else {}
        now = abs_tick(s)
        since = held.get("since")
        if not isinstance(since, int) or since > now:
            memory.threat_alarm = {"since": now, "why": why}
            since = now
        days = (now - since) // TICKS_PER_DAY
        if days >= _c(cfg, "threat_alarm_max_days"):
            notes.append(f"{why} for {days} days: the AI no longer holds the alarm for it (the fort can't "
                         "stay indoors for ever); the danger is still watched, and a new threat sounds it again")
            return
    else:
        memory.threat_alarm = {}
    if why.startswith("an evil cloud"):
        from planner_weather import keep_in_active
        if keep_in_active(memory):
            # (item4) the weather rule keeps the civilians in by the burrow: no alarm for the cloud
            notes.append(f"{why}: the civilians are kept inside by the weather rule (no alarm)")
            return
    if why:
        proposals[:] = [p for p in proposals if p.action != {"type": "civ_alert", "on": False}]
        if not s.get("civ_alert") and not any(p.action == {"type": "civ_alert", "on": True} for p in proposals):
            if s.get("civ_alert_ready") is True:
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                          f"{why}: sound the alarm (everyone inside, no work on the surface)", 0))
            else:
                from planner_military import no_shelter
                no_shelter(s, memory, why, proposals, notes)        # (0.105.35) the AI makes one
