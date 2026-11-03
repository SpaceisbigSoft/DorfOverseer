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
  6. great beasts in an open cavern the squads can't take: the doors and
     hatches on the way down locked; unlocked once it has gone;
  7. a great danger on the surface near dwarves out there: the alarm;
  8. nobody has DF's Recover wounded labour: two dwarves put on it.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, PLANNER_CONFIG, Proposal, STEER_PROTECTED, TICKS_PER_DAY, abs_tick, ask_player,
                          can_fight, reachable_threats, _traits)

__all__ = ["_threat_rules", "threat_alert", "threat_rules_of", "moon_due", "PRISONER_CHOICES", "THREAT_CONFIG"]

PRISONER_CHOICES = ("keep", "release", "kill")

# (0.105.0) the round's own settings, added to the planner's (cooldowns are read from there by select())
THREAT_CONFIG = {
    "fire_guard_cooldown_ticks": 100,        # the fire guard every ~2 hours while it burns
    "fire_guard_near": 40,                   # a fire this close to the dwarves (levels count 3) is guarded
    "fire_guard_radius": 6,
    "fire_guard_jobs": 40,                   # jobs beside the fire taken off at most each time
    "prisoner_room_cooldown_ticks": 7 * 1200,
    "thief_traps": 3,                        # cage traps at a gate once thieves or snatchers were seen
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
    "rescue_labor_cooldown_ticks": 14 * 1200,
}
PLANNER_CONFIG.update({k: v for k, v in THREAT_CONFIG.items() if k not in PLANNER_CONFIG})

# (0.105.0) the fire guard and the moon cells wait for no action slot, and the strategist never holds them
LIMIT_EXEMPT.update({"fire_guard", "moon_cell"})
STEER_PROTECTED.update({"fire_guard", "moon_cell", "seal_cavern"})

AGENDA_THEMES.update({"fire_guard": "keep the dwarves away from the fire", "prisoners": "a cage room for prisoners",
                      "thieves": "keep thieves and snatchers out", "undead": "keep the dwarves in from the dead",
                      "reanimation": "rot the bodies an evil land would raise",
                      "moon_cell": "lock the werebeasts in for the full moon",
                      "seal_cavern": "seal the cavern against a beast", "rescue_labor": "fetch the wounded"})


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
    surface, a great danger on the surface near those out there."""
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
        if not _num(x.get("distance")) or x["distance"] <= _c(cfg, "undead_near"):
            return f"the walking dead ({x.get('name') or 'undead'}) near the dwarves"
    if _num(u.get("cloud_outside_near")) and u["cloud_outside_near"] <= _c(cfg, "evil_cloud_near"):
        return (f"an evil cloud{' of ' + str(u['cloud_material']) if u.get('cloud_material') else ''} "
                f"{u['cloud_outside_near']} tiles from dwarves on the surface")
    for x in _l(_d(t.get("surface")).get("list")):
        if (isinstance(x, dict) and x.get("great") and _num(x.get("distance_outside"))
                and x["distance_outside"] <= _c(cfg, "surface_danger_near")):
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
    if choice == "keep":
        notes.append(f"{n} prisoner(s) kept in their cages (Rules tab: prisoners)")
    else:
        what = "released outside" if choice == "release" else "put to death"
        notes.append(f"{n} prisoner(s) to be {what} (Rules tab), but DFHack offers no safe way to do it: "
                     "they stay caged (a pit zone over a drop, or a cage opened by a lever, is yours to build)")


def _thieves(s, cfg, t, memory, proposals, notes):
    th = _d(t.get("thieves"))
    rows = [x for x in _l(th.get("list")) if isinstance(x, dict) and x.get("id") is not None]
    inside = [x for x in rows if x.get("inside") or x.get("can_reach_dwarves") is True]
    if inside:
        able = _able_squads(s, cfg)
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
        else:
            notes.append(f"{names} in the fort" + (" and no squad free to send" if not able else
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


def _cavern_beasts(s, cfg, memory, t, rules, proposals, notes):
    d = _d(s.get("deep"))
    sealed = _d(t.get("sealed"))
    dangers = [x for x in _l(d.get("dangers")) if isinstance(x, dict) and not x.get("caged")
               and x.get("kind") in ("forgotten beast", "titan", "megabeast", "demon")]
    for c in [c for c in _l(d.get("caverns")) if isinstance(c, dict)]:
        name = c.get("name")
        here = [x for x in dangers if x.get("layer") == name]
        if here and c.get("open") and rules["seal_caverns"]:
            from planner_military import fight_or_hide
            mil = _d(s.get("military"))
            able = [q for q in _l(mil.get("squads")) if isinstance(q, dict) and can_fight(q, cfg)]
            th = {str(o.get("id")): o for o in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(o, dict)}
            great = [th.get(str(x.get("id"))) or {"name": x.get("name")} for x in here]
            try:
                fight, verdict = fight_or_hide(s, memory, cfg, great, able)
            except Exception:  # noqa: BLE001
                fight, verdict = False, "the squads' strength unknown"
            if fight and player_attack(s) != "never":
                notes.append(f"{here[0].get('name')} ({here[0].get('kind')}) in {name}: the squads are strong "
                             f"enough ({verdict}); the cavern is left open for them")
                continue
            tiles = [p for p in seal_tiles(c) if all(_num(p.get(k)) for k in ("x", "y", "z"))]
            if tiles and name not in sealed:
                act = {"type": "seal_cavern", "layer": name, "tiles": tiles[:12]}
                # (0.105.0 review) the cavern's levels: the bridge refuses while a dwarf is down there
                if _num(c.get("z_top")) and _num(c.get("z_bottom")):
                    act["z1"], act["z2"] = int(c["z_bottom"]), int(c["z_top"])
                proposals.append(Proposal("seal_cavern", act,
                                          f"{here[0].get('name')} ({here[0].get('kind')}) is in {name}, open to the "
                                          f"fort, and the squads can't take it ({verdict}): lock the doors and "
                                          "hatches on the way down", 1))
            elif not tiles and name not in sealed:
                ask_player(notes, f"{here[0].get('name')} is in {name}, open to the fort, and no door or hatch "
                                  "known on the way down: wall it off")
        elif name in sealed and not here:
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                      f"no great beast left in {name}: unlock the way down again", 3))
    # (0.105.0 review) a sealed layer the deep report no longer lists: unlocked after some days
    names = {c.get("name") for c in _l(d.get("caverns")) if isinstance(c, dict)}
    for name, rec in sealed.items():
        days = _d(rec).get("days")
        if (rules["seal_caverns"] and name not in names and _num(days)
                and days >= _c(cfg, "seal_missing_days")):
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                      f"{name} sealed {days} days and no longer in the deep report: unlock the way down", 3))
    if not rules["seal_caverns"]:
        for name in sealed:
            proposals.append(Proposal("seal_cavern", {"type": "seal_cavern", "layer": name, "open": True},
                                      "sealing the caverns is off on the Rules tab: unlock the way down", 3))


STAIRISH = ("STAIR", "RAMP")


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


def player_attack(s: dict) -> str:
    st = s.get("settings") if isinstance(s.get("settings"), dict) else {}
    return st.get("attack_policy") if st.get("attack_policy") in ("all", "ordinary", "never") else "ordinary"


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
    # (0.105.0 review) held at most threat_alarm_max_days: past that it is the player's call
    if why:
        held = memory.threat_alarm if isinstance(getattr(memory, "threat_alarm", None), dict) else {}
        now = abs_tick(s)
        since = held.get("since")
        if not isinstance(since, int) or since > now:
            memory.threat_alarm = {"since": now, "why": why}
            since = now
        days = (now - since) // TICKS_PER_DAY
        if days >= _c(cfg, "threat_alarm_max_days"):
            ask_player(notes, f"{why} for {days} days: the AI no longer holds the alarm for it "
                              "(sound it, or wall the danger off, yourself)")
            return
    else:
        memory.threat_alarm = {}
    if why:
        proposals[:] = [p for p in proposals if p.action != {"type": "civ_alert", "on": False}]
        if not s.get("civ_alert") and not any(p.action == {"type": "civ_alert", "on": True} for p in proposals):
            if s.get("civ_alert_ready") is True:
                proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                          f"{why}: sound the alarm (everyone inside, no work on the surface)", 0))
            else:
                ask_player(notes, f"{why}, and no civilian-alert burrow is set up to keep the dwarves inside")
