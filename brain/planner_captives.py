"""(item6) Prisoners' outcomes and necromancer sieges.

The `captives` report (lua/ai-captives.lua) lists every creature caged that
isn't the fort's own, one row each, and the AI's pit; the `necro` report
says what a necromancer siege brings: the walking dead on the map, the
raisers among the living, bodies lying outside while the dead are about,
and the necromancer towers near the fort on the world map.

Prisoners, one by one, by the Rules tab's choice (`prisoners`: keep, the
safe default; release; kill):

  * a great danger (a titan, a forgotten beast...) never leaves its cage;
  * a wild creature (no invader, no thief, no thinking being) is kept caged
    for the zoo (the cage room, planner_threats) whatever the choice;
  * keep: kept caged;
  * release: DFHack has no safe way to open a cage, and an invader let out
    fights again: kept caged, and said so;
  * kill: invaders and thieves go to the AI's pit (DF's own Pit/Pond zone:
    the dwarves carry each to the edge and drop it), never while enemies
    can reach the dwarves or the alarm is up. The pit is a zone placed over
    a drop already there (make_pit: the AI digs none); the first assignment
    is a dry run (pit_prisoners trial), then for real a few at a time. The
    emptied cage goes back into its trap by the game's own LoadCageTrap job
    (the cage-trap re-arming rule in planner_military makes cages if short).

Convicts serving time are the justice rules' (planner_building's jail,
probe_justice): only said here.

A necromancer siege: the walking dead who can reach the dwarves or came as
invaders, counted against the fort's armed soldiers. Past
undead_overwhelm_min and undead_per_soldier dead to a soldier (fewer with a
raiser on the map: each soldier who falls rises against the fort), no squad
goes at them (the squads' kill orders on them dropped, squads already out
called back), the alarm goes up (everyone inside; the gate rules shut the
gates on any threat in reach), unless the Rules tab says attack everything.
While the dead or a raiser are about, bodies and parts lying outside rot
away (prune_remains: DFHack's deteriorate, no dwarf goes out). A
necromancer tower near the fort is said once a year and with every siege.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, Proposal, TICKS_PER_DAY, abs_tick, can_fight, player_rules, reachable_threats, _traits

__all__ = ["CAPTIVES_KEYS", "decide", "_captives_rule", "_necro_rule", "note_captives", "undead_odds"]

# (the tuning numbers are in PLANNER_CONFIG, brain/planner_config.py: pit_*, undead_*, necro_*)
CAPTIVES_KEYS = ("pit_min_drop", "pit_batch", "undead_overwhelm_min", "undead_per_soldier",
                 "undead_per_soldier_raiser", "necro_corpses_min", "necro_tower_near")

YEAR = 336 * TICKS_PER_DAY


def _c(cfg: dict, k: str):
    return cfg[k] if k in cfg else PLANNER_CONFIG[k]


def _seen(memory) -> dict:
    if memory is None:
        return {}
    if not isinstance(getattr(memory, "captives_seen", None), dict):
        memory.captives_seen = {}
    return memory.captives_seen


def _choice(s: dict) -> str:
    from planner_threats import threat_rules_of
    return threat_rules_of(s)["prisoners"]


def decide(row: dict, choice: str) -> tuple[str, str]:
    """One prisoner's outcome: ("keep" | "pit" | "assigned", why)."""
    if row.get("great"):
        return "keep", "a great danger: never taken out of its cage"
    hostile = bool(row.get("invader") or row.get("thief") or (row.get("danger") and row.get("intelligent")))
    if not hostile:
        return "keep", "a wild creature: kept caged for the zoo"
    if choice == "kill":
        if row.get("zone") is not None:
            return "assigned", "on its way to the pit"
        return "pit", "to the pit (Rules tab: put to death)"
    if choice == "release":
        return "keep", ("can't be let out: DFHack has no safe way to open a cage, and an invader let out "
                        "fights again (Rules tab: release)")
    return "keep", "kept caged (Rules tab: keep)"


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


def _captives_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    c = _d(s.get("captives"))
    rows = [r for r in _l(c.get("list")) if isinstance(r, dict) and r.get("id") is not None]
    j = _d(_d(s.get("justice")).get("punish"))
    if _int(j.get("prison")):
        notes.append(f"{_int(j['prison'])} convict(s) sentenced to jail time: the justice rules see to them")
    if not rows:
        return
    choice = _choice(s)
    out: dict[str, list] = {"keep": [], "pit": [], "assigned": []}
    whys: dict[str, int] = {}
    for r in rows:
        v, why = decide(r, choice)
        out[v].append(r)
        if v == "keep":
            whys[why] = whys.get(why, 0) + 1
    parts = [f"{n} {why}" for why, n in sorted(whys.items(), key=lambda kv: -kv[1])]
    if out["assigned"]:
        parts.append(f"{len(out['assigned'])} on their way to the pit")
    if out["pit"]:
        parts.append(f"{len(out['pit'])} for the pit")
    notes.append(f"{_int(c.get('caged')) or len(rows)} prisoner(s) in cages: " + "; ".join(parts))
    if not out["pit"]:
        return
    if reachable_threats(s, _traits(s), cfg) or s.get("civ_alert"):
        notes.append(f"{len(out['pit'])} prisoner(s) wait for the pit: enemies are about (the dwarves would "
                     "carry them out under attack)")
        return
    need = _c(cfg, "pit_min_drop")
    pits = [p for p in _l(c.get("pits")) if isinstance(p, dict)]
    if not pits:
        proposals.append(Proposal("prisoner_pit", {"type": "make_pit", "min_drop": need},
                                  f"{len(out['pit'])} prisoner(s) to be put to death (Rules tab) and the AI has no "
                                  f"pit: a pit zone over a drop of {need}+ levels near the dwarves (none is dug)", 6))
        return
    good = [p for p in pits if _int(p.get("drop")) >= need]
    if not good:
        notes.append(f"the AI pit drops {_int(pits[0].get('drop'))} level(s), under the {need} that kill: "
                     "the prisoners stay caged")
        return
    ids = [r["id"] for r in out["pit"]][:_c(cfg, "pit_batch")]
    names = ", ".join(str(r.get("name") or r["id"]) for r in out["pit"][:3])
    action = {"type": "pit_prisoners", "ids": ids, "max": _c(cfg, "pit_batch"), "min_drop": need}
    if not _seen(memory).get("pit_trial"):
        proposals.append(Proposal("pit_prisoners", {**action, "dry_run": True},
                                  f"a trial first (changes nothing): {names} to the AI pit", 6))
    else:
        proposals.append(Proposal("pit_prisoners", action,
                                  f"{names} to the AI pit (Rules tab: put to death); the empty cages go back "
                                  "into their traps", 6))


def note_captives(p, r: dict, memory, now: int) -> None:
    """After a pit_prisoners call: the trial marked done (the real call follows)."""
    a = _d(getattr(p, "action", None))
    if a.get("type") != "pit_prisoners" or memory is None:
        return
    r = _d(r)
    seen = _seen(memory)
    if a.get("dry_run") and r.get("ok") is True:
        seen["pit_trial"] = now
    elif not a.get("dry_run") and r.get("ok") is True:
        seen["pitted"] = _int(seen.get("pitted")) + _int(r.get("assigned"))


# --- necromancer sieges -----------------------------------------------------------------

def undead_odds(s: dict, cfg: dict) -> dict:
    """The walking dead of a siege (in reach of the dwarves or invaders) and
    the fort's armed soldiers: {ids, n, soldiers, raisers, per, overwhelming}."""
    threats = [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)]
    dead = [t for t in threats if "Undead" in _l(t.get("kinds"))
            and (t.get("can_reach_dwarves") is True or t.get("invader"))]
    raisers = [x for x in _l(_d(s.get("necro")).get("raisers")) if isinstance(x, dict)]
    soldiers = 0
    for q in _l(_d(s.get("military")).get("squads")):
        if isinstance(q, dict) and can_fight(q, cfg):
            armed = _d(q.get("power")).get("armed")
            soldiers += _int(armed) if isinstance(armed, int) and not isinstance(armed, bool) else _int(q.get("members"))
    per = _c(cfg, "undead_per_soldier_raiser") if raisers else _c(cfg, "undead_per_soldier")
    n = len(dead)
    return {"ids": [t.get("id") for t in dead if t.get("id") is not None], "n": n, "soldiers": soldiers,
            "raisers": raisers, "per": per,
            "invaders": any(t.get("invader") for t in dead),
            "overwhelming": n >= _c(cfg, "undead_overwhelm_min") and n > soldiers * per}


def _towers(s: dict, cfg: dict) -> list:
    return [t for t in _l(_d(s.get("necro")).get("towers")) if isinstance(t, dict)
            and _int(t.get("dist")) <= _c(cfg, "necro_tower_near")]


def _tower_words(t: dict) -> str:
    return (f"a necromancer tower{' (' + str(t['name']) + ')' if t.get('name') else ''} "
            f"{_int(t.get('dist'))} world tile(s) {t.get('way') or 'away'}")


def _necro_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    nec = _d(s.get("necro"))
    odds = undead_odds(s, cfg)
    seen = _seen(memory)
    now = abs_tick(s)
    towers = _towers(s, cfg)
    siege = bool(odds["raisers"]) or (odds["n"] > 0 and odds["invaders"])
    if towers and isinstance(now, int):
        year = now // YEAR
        if siege or seen.get("tower_year") != year:
            notes.append(f"{_tower_words(towers[0])}: the dead may come from there")
            seen["tower_year"] = year
    if not siege:
        if seen.get("siege"):
            seen["siege"] = {}
        return
    rec = seen.get("siege") if isinstance(seen.get("siege"), dict) else {}
    if not rec:
        rec = {"since": now, "peak": 0}
    rec["peak"] = max(_int(rec.get("peak")), odds["n"])
    seen["siege"] = rec
    raised = (f"; {len(odds['raisers'])} raiser(s) among them ({', '.join(str(x.get('name')) for x in odds['raisers'][:2])})"
              if odds["raisers"] else "")
    policy = player_rules(s)["attack_policy"]
    if odds["overwhelming"] and policy != "all":
        ids = set(odds["ids"])
        squads = {q.get("id"): q for q in _l(_d(s.get("military")).get("squads"))
                  if isinstance(q, dict) and q.get("id") is not None}
        kept = []
        for p in proposals:
            a = p.action
            if a.get("type") == "squad_orders" and isinstance(a.get("kill"), list) and ids & set(a["kill"]):
                rest = [i for i in a["kill"] if i not in ids]
                if not rest:
                    continue
                p.action = dict(a, kill=rest)
                p.reason += " (not the walking dead: too many of them)"
            kept.append(p)
        ordered = {p.action.get("squad_id") for p in kept if p.action.get("type") == "squad_orders"}
        for q in squads.values():
            on = {x for x in _l(q.get("kill_ids")) if isinstance(x, int)} & ids
            if q.get("ai_orders") and on and q["id"] not in ordered:
                kept.append(Proposal("squad_recall", {"type": "squad_orders", "squad_id": q["id"], "clear": True},
                                     f"{odds['n']} walking dead against {odds['soldiers']} armed soldier(s): "
                                     f"{q.get('name') or 'the squad'} comes back inside", 0))
        proposals[:] = kept
        if (not s.get("civ_alert") and s.get("civ_alert_ready") is True
                and not any(p.action == {"type": "civ_alert", "on": True} for p in proposals)):
            proposals[:] = [p for p in proposals if p.action != {"type": "civ_alert", "on": False}]
            proposals.append(Proposal("threat_alert", {"type": "civ_alert", "on": True},
                                      f"a necromancer siege: {odds['n']} walking dead: sound the alarm "
                                      "(everyone inside)", 0))
        notes.append(f"a necromancer siege: {odds['n']} walking dead against {odds['soldiers']} armed soldier(s)"
                     f"{raised}: too many to fight (more than {odds['per']:g} a soldier); no squad goes out, the "
                     "gates stay shut and everyone stays in")
    elif odds["overwhelming"]:
        notes.append(f"a necromancer siege: {odds['n']} walking dead{raised}: the squads go all the same "
                     "(Rules tab: attack everything)")
    else:
        notes.append(f"a necromancer siege: {odds['n']} walking dead against {odds['soldiers']} armed "
                     f"soldier(s){raised}: the squads can take them")
    n = _int(nec.get("surface_corpses"))
    if n >= _c(cfg, "necro_corpses_min") and not any(p.action.get("type") == "prune_remains" for p in proposals):
        proposals.append(Proposal("necro_corpses", {"type": "prune_remains"},
                                  f"{n} bodies and parts lie outside with the dead about: rot them away before "
                                  "they are raised (no dwarf goes out; entombed and unburied citizens kept)", 2))
