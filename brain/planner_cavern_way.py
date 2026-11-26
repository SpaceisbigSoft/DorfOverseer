"""(item3, the player's yes 25 Nov 22:38) The guarded cavern way.

No fort reached real cavern floor: the silk webs (3,300-13,200 a fort) lay
out of reach, the lure had no pocket spot (only the wells' hatches reach the
caverns: planner_lure), cavern hunts failed `no_path`/`seal`
(planner_hunt), and cavern logging had nothing to walk on. So the fort gets
ONE way of the AI's own onto the first cavern's floor (lua/ai-cavern-way.lua):
a stair down from one of the fort's deepest levels and a straight tunnel to
the cavern, a plain door at its cavern end (on ai-threats' openings record:
the seal locks it, a lure pocket fits in the tunnel behind it) and a hatch
on a lever over the stair's top: the GATE.

  * built (`cavern_way_build`, step build, a step a call) once the fort is
    past young and has `cavern_way_min_citizens`, while no enemy can reach
    the dwarves and the caverns aren't sealed. Its top goes on the deepest
    level the fort's character allows: Caution 50+ never under its homes.
    A cavern nobody has found only when the Rules' `open_caverns` would let
    a cavern well open it (always, or the AI's own call).
  * the gate stays SHUT. It opens (`cavern_way_open`) for a job:
      silk     the fort wants silk (planner_mood_help.silk_wanted), it has a
               Loom and loose webs lie on the cavern side;
      hunt     a cavern target the hunt rule would go after (not a great
               danger, the way to it blocked), the hunt allowed and a squad
               free; held while a hunt after a cavern target goes on;
      lure     a lure pocket is being built behind the way's door (the door
               locked by the seal: the builders go down the stair);
      logging  wood short, few surface trees, cavern trees standing (or the
               woodcutters' marks still there);
      stranded a citizen is beyond the gate: opened to let them back;
    only while no danger is near: no hostile within `cavern_way_danger_tiles`
    of the door (the hunt's own target aside), no enemy that can reach the
    dwarves, no lure holding the door open, and, with `seal_caverns` on, no
    great beast in the caverns (seen or not) and no seal up (the lure's
    job aside: its door is locked).
  * it shuts (`cavern_way_shut`, a safety step: no limit, never held) when
    a danger shows (within `cavern_way_close_tiles` whoever is out; further
    only once nobody is beyond: "gates close late"), when the job ends, when
    it was open `cavern_way_open_days` (then that job rests
    `cavern_way_rest_days`), or the Rules switch goes off. The bridge's
    watcher shuts it between reports too (a danger within 12 of the door,
    or within 20 with nobody out).
Rules switch `cavern_way` (on by default). Without the section (an older
bridge, the fixtures) nothing is proposed.
"""

from __future__ import annotations

from digest import _d, _l, game_text
from planner_core import (AGENDA_THEMES, LIMIT_EXEMPT, PLANNER_CONFIG, STEER_PROTECTED, TICKS_PER_DAY, Proposal,
                          _has_shop, _traits, abs_tick, player_rules, queued, young_fort)

__all__ = ["CAVERN_WAY_CONFIG", "cavern_way", "way_jobs", "way_danger", "_cavern_way_rule"]

CAVERN_WAY_CONFIG = {
    "cavern_way_min_citizens": 20,       # the fort this big before it digs its way to the caverns
    "cavern_way_danger_tiles": 25,       # a hostile this near the door: the gate isn't opened (and shuts)
    "cavern_way_close_tiles": 12,        # ...this near: shut whoever is out ("gates close late")
    "cavern_way_open_days": 3,           # open this long for one job at most...
    "cavern_way_rest_days": 4,           # ...then that job rests this long
    "cavern_way_clear_days": 0.5,        # no danger seen this long before it opens again
    "cavern_way_build_cooldown_ticks": 600,
    "cavern_way_open_cooldown_ticks": 300,
    "cavern_way_shut_cooldown_ticks": 25,    # shutting is safety: soon again if it didn't take
}
PLANNER_CONFIG.update({k: v for k, v in CAVERN_WAY_CONFIG.items() if k not in PLANNER_CONFIG})

LIMIT_EXEMPT.update({"cavern_way_shut"})
STEER_PROTECTED.update({"cavern_way_shut"})
AGENDA_THEMES.update({"cavern_way_build": "a guarded way onto the cavern floor",
                      "cavern_way_open": "work in the caverns through the guarded way",
                      "cavern_way_shut": "work in the caverns through the guarded way"})

BUILDING = ("dig", "digging", "lever", "lever_building", "hatch", "hatch_building", "link", "linking",
            "breach", "breaching", "door", "door_building")
GREAT_KINDS = ("forgotten beast", "titan", "megabeast", "demon", "cave dragon")
JOB_WORDS = {"silk": "the silk webs", "hunt": "a hunt in the caverns", "lure": "the lure pocket behind its door",
             "logging": "the cavern trees", "stranded": "the citizens beyond it to come back"}


def _way_conf(cfg: dict, k: str):
    return cfg.get(k, CAVERN_WAY_CONFIG.get(k))


def cavern_way(s: dict) -> dict | None:
    """The bridge's `cavern_way` section, or None (none, failed, an older bridge)."""
    d = s.get("cavern_way")
    if not isinstance(d, dict) or not d or "error" in d or "cavern_way" in _d(s.get("_errors")):
        return None
    return d


from util import int_or_zero as _int  # noqa: E402  (the shared helper: 0 for none or a non-int)


def _great_in_caverns(s: dict, layer: str | None) -> str:
    """A great danger loose in the caverns (seen, or unseen in the way's layer): its name, else ''."""
    for x in _l(_d(s.get("deep")).get("dangers")):
        if isinstance(x, dict) and not x.get("caged"):
            lay = str(x.get("layer") or "")
            if not lay or lay.lower().startswith("cavern"):
                return str(x.get("name") or "a great danger")
    for x in _l(_d(s.get("deep")).get("unseen")):
        if isinstance(x, dict) and (x.get("layer") == layer or (layer is None and str(x.get("layer", "")).startswith("Cavern"))) \
                and str(x.get("kind") or "") in GREAT_KINDS:
            return str(x.get("name") or x.get("kind"))
    for x in _l(_d(s.get("lures")).get("beasts")):
        if isinstance(x, dict) and not x.get("caged") and not x.get("dead"):
            return str(x.get("name") or x.get("kind") or "a great beast")
    return ""


def _sealed(s: dict) -> bool:
    return any(isinstance(v, dict) for v in _d(_d(s.get("threats")).get("sealed")).values())


def _lure_rows(s: dict, door_key: str | None) -> list:
    return [r for r in _l(_d(s.get("lures")).get("lures"))
            if isinstance(r, dict) and door_key is not None and r.get("key") == door_key]


def _door_key(w: dict) -> str | None:
    p = _d(w.get("door"))
    if all(isinstance(p.get(k), int) for k in ("x", "y", "z")):
        return f"{p['x']},{p['y']},{p['z']}"
    return None


def _hunt_targets(s: dict, cfg: dict, memory, w: dict) -> tuple[list, bool]:
    """(cavern targets the hunt would go after through the way, a cavern hunt under way)."""
    try:
        from planner_hunt import _blocked, hunt_mode, hunt_off_ids, hunt_rows
    except Exception:  # noqa: BLE001
        return [], False
    rows = hunt_rows(s)
    if rows is None:
        return [], False
    targets, squads, hunts, _h = rows
    by_id = {t.get("id"): t for t in targets}
    under_way = any(_d(by_id.get(h.get("target_id"))).get("region") == "cavern" for h in hunts)
    mode = hunt_mode(s)
    if mode != "ai" and mode != "small":
        return [], under_way
    if _blocked(s, memory, cfg, player_rules(s), mode) is not None:
        return [], under_way
    off = hunt_off_ids(s, memory, cfg)
    min_armed = int(cfg.get("min_squad_to_fight", 3))
    free = [q for q in squads if q.get("at_home") is True and q.get("hunting") is None and not q.get("sheltering")
            and _int(q.get("soldiers")) >= min_armed]
    if not free:
        return [], under_way
    out = []
    for t in targets:
        r = _d(t.get("route"))
        if (t.get("region") != "cavern" or r.get("ok") or r.get("blocked_by") not in ("no_path", "gate")
                or t.get("great_danger") or t.get("kill_ok") is False or t.get("id") in off
                or t.get("can_reach_dwarves") is True):
            continue
        if mode == "small" and not (t.get("thief") or t.get("ambush") or t.get("wounded_visitor")):
            continue
        if w.get("layer") and t.get("layer") and t.get("layer") != w.get("layer"):
            continue
        out.append(t)
    return out, under_way


def way_jobs(s: dict, cfg: dict, memory, w: dict) -> dict:
    """The jobs the way could open for now: {job: words}, in their order."""
    jobs: dict = {}
    if _int(w.get("beyond")) > 0:
        jobs["stranded"] = f"{w.get('beyond_first') or 'a citizen'} is beyond the gate"
    for r in _lure_rows(s, _door_key(w)):
        if r.get("phase") == "building":
            jobs["lure"] = "a lure pocket is being built behind its door"
    rules_ = player_rules(s)
    webs = _int(w.get("webs"))
    if webs > 0 and _has_shop(_d(s.get("buildings")), "Loom"):
        try:
            from planner_mood_help import silk_wanted
            why = silk_wanted(s, cfg)
        except Exception:  # noqa: BLE001
            why = ""
        if why:
            jobs["silk"] = f"{why}; {webs} loose web(s) on the cavern side"
    targets, under_way = _hunt_targets(s, cfg, memory, w)
    if under_way:
        jobs["hunt"] = "a hunt in the caverns is under way"
    elif targets:
        t = targets[0]
        jobs["hunt"] = f"{t.get('name') or t.get('kinds') or 'a creature'} in the caverns can be hunted through it"
    f = _d(s.get("forestry"))
    if f and "error" not in f and rules_.get("cavern_logging") is not False:
        cave = _d(f.get("cavern"))
        marked = _int(f.get("ai_marked"))
        if marked > 0 and w.get("gate") == "open":
            jobs["logging"] = f"{marked} cavern tree(s) marked for the woodcutters"
        elif _int(cave.get("trees")) > 0:
            try:
                from planner_forestry import _wood_short
                citizens = _int(_d(s.get("dwarves")).get("total"))
                short, wood = _wood_short(s, cfg, citizens)
            except Exception:  # noqa: BLE001
                short, wood = False, 0
            grove = _int(_d(f.get("grove")).get("trees"))
            surface_left = _int(_d(f.get("surface")).get("trees")) - grove
            # shut: only trees no other way reaches; open: held while the wood is short
            reach = _int(cave.get("reachable")) == 0 or w.get("gate") == "open"
            if short and reach and surface_left < int(cfg.get("cavern_logging_surface_min", 20)):
                jobs["logging"] = f"wood is short ({wood}) and {cave.get('trees')} cavern tree(s) stand"
    return jobs


def way_danger(s: dict, cfg: dict, w: dict, job: str | None, ignore: set | None = None) -> tuple[str, int | None]:
    """Why the gate must not be open for this job now ('' if it may), and the
    nearest hostile's distance to the door (None: none near)."""
    ignore = ignore or set()
    near = [x for x in _l(w.get("dangers")) if isinstance(x, dict) and x.get("id") not in ignore
            and isinstance(x.get("d"), (int, float))]
    near.sort(key=lambda x: x["d"])
    dmax = int(_way_conf(cfg, "cavern_way_danger_tiles"))
    first = near[0] if near else None
    dist = int(first["d"]) if first else None
    if job == "lure":
        # the door is locked by the seal: only a danger right at it (or in the way) keeps the stair shut
        if not w.get("door_locked"):
            return "the way's door isn't locked (the lure's builders go down only behind a locked door)", dist
        if first and first["d"] <= int(_way_conf(cfg, "cavern_way_close_tiles")):
            return f"{first.get('name') or 'a hostile'} is {first['d']} tile(s) from its door", dist
        return "", dist
    if first and first["d"] <= dmax:
        return f"{first.get('name') or 'a hostile'} is {first['d']} tile(s) from its door", dist
    if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves"):
        return "enemies can reach the dwarves", dist
    if w.get("door_locked"):
        return "its door is locked (the seal or a lure holds it)", dist
    if any(r.get("open") for r in _lure_rows(s, _door_key(w))):
        return "a lure holds its door open", dist
    if _d(s.get("settings")).get("seal_caverns") is not False:
        if _sealed(s):
            return "the caverns are sealed against a great beast", dist
        great = _great_in_caverns(s, w.get("layer"))
        if great:
            return f"{great} is in the caverns (the Rules keep them sealed against it)", dist
    return "", dist


def _mem(memory) -> dict:
    m = getattr(memory, "cavern_way", None) if memory is not None else None
    if not isinstance(m, dict):
        m = {}
        if memory is not None:
            try:
                memory.cavern_way = m
            except Exception:  # noqa: BLE001
                pass
    return m


LINK_MECHANISMS = 2                      # a lever's link takes two (lua/ai-cavern-way.lua's link step)
DOOR_RECIPES = {"stone_door", "wooden_door", "metal_door", "glass_door"}


def _parts_wait(s: dict, w: dict, state: str, proposals: list, notes: list) -> bool:
    """(item6, R32 e) A step that waits for parts: the parts got, and the step
    not asked for until they are (True). D's link was refused 69 times ("2 free
    mechanisms are needed for the link"), C's breach waited for a door in
    store: the bridge said so every cycle and nothing made one.
      * the link: the mechanisms go into planner_mechanisms' demand ("cavern
        way"), so its rule orders them at the Mechanic's workshop (one dug and
        built if there is none, the Mechanics labour given, a quarry when no
        ordinary stone is left) with the other links' and a reserve;
      * the breach (the last tile into the cavern is dug only with a door in
        store for its end): a stone door ordered at the Mason's workshop when
        none is free and none is on order."""
    if state == "link":
        have = w.get("mechanisms")
        if isinstance(have, int) and not isinstance(have, bool) and have < LINK_MECHANISMS:
            notes.append(f"the cavern way's gate waits for its lever link: {LINK_MECHANISMS} free mechanisms wanted, "
                         f"{have} free; the mechanisms rule has them made at the Mechanic's workshop, and the link "
                         "is asked for once they are in store")
            return True
        return False
    if state != "breach":
        return False
    have = w.get("doors_free")
    if not isinstance(have, int) or isinstance(have, bool) or have >= 1:
        return False
    on_order = queued(s, DOOR_RECIPES) if isinstance(s.get("orders"), list) else 0
    if on_order or any(_d(p.action).get("type") == "work_order" and _d(p.action).get("recipe") in DOOR_RECIPES
                       for p in proposals):
        notes.append(f"the cavern way waits for a door before its last tile into the cavern is dug: "
                     f"{on_order or 1} door(s) on order")
        return True
    b = _d(s.get("buildings"))
    if "workshops" in b and not _has_shop(b, "Masons"):
        if _has_shop(b, "Carpenters"):
            recipe, shop = "wooden_door", "Carpenter's"
        else:
            notes.append("the cavern way waits for a door before its last tile into the cavern is dug, and the "
                         "fort has no Mason's or Carpenter's workshop to make one")
            return True
    else:
        recipe, shop = "stone_door", "Mason's"
    proposals.append(Proposal("cavern_way_build", {"type": "work_order", "recipe": recipe, "amount": 1},
                              f"the cavern way's last tile into the cavern is dug only with a door in store for "
                              f"its end, and no door is free: make one at the {shop} workshop", 5, True))
    return True


def _cavern_way_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    w = cavern_way(s)
    if w is None:
        return
    on = player_rules(s).get("cavern_way", True) is not False
    state = w.get("state")
    now = abs_tick(s)
    m = _mem(memory)
    gate = w.get("gate")
    beyond = _int(w.get("beyond"))

    def shut(why: str, p: int = 1) -> None:
        proposals.append(Proposal("cavern_way_shut", {"type": "cavern_way", "step": "shut", "shut": True,
                                                      "why": why[:60]}, f"the cavern way's gate: {why}", p))

    # --- not built yet --------------------------------------------------------------
    if state in (None, "none", "refused"):
        if state == "refused":
            notes.append(f"no cavern way: {game_text(w.get('why'), 120)} (looked for again in "
                         f"{max(1, _int(w.get('retry_ticks')) // TICKS_PER_DAY)} day(s))")
            return
        if not on:
            return
        citizens = _int(_d(s.get("dwarves")).get("total"))
        if young_fort(s, cfg) or citizens < int(_way_conf(cfg, "cavern_way_min_citizens")):
            return
        if _d(s.get("others_on_map")).get("threats_that_can_reach_dwarves") or _sealed(s):
            return
        mode = player_rules(s).get("open_caverns", "ai")
        unfound_ok = mode == "always"
        if mode == "ai":
            try:
                from planner_wells_caverns import ai_opens_cavern
                unfound_ok = bool(ai_opens_cavern(s, cfg)[0])
            except Exception:  # noqa: BLE001
                unfound_ok = False
        caution = _traits(s).get("caution", 0) or 0
        proposals.append(Proposal("cavern_way_build", {"type": "cavern_way", "step": "build", "caution": caution,
                                                       "unfound_ok": unfound_ok},
                                  "one guarded way onto the first cavern's floor (a stair and a tunnel, a door at "
                                  "its end, a hatch on a lever as its gate, kept shut): the silk webs, cavern "
                                  "hunts, a lure pocket and the cavern trees within reach"
                                  + (" (its top away from the homes: Caution)" if caution >= 50 else ""), 6))
        return
    if state in BUILDING:
        if gate == "open":
            dist = way_danger(s, cfg, w, None)[1]
            if dist is not None and dist <= int(_way_conf(cfg, "cavern_way_close_tiles")):
                shut(f"a danger {dist} tile(s) from the way being built", 0)
                return
            if not on and not beyond:
                shut("the cavern way is switched off on the Rules tab")
                return
        if not on:
            return
        if state in ("digging", "lever_building", "hatch_building", "linking", "breaching", "door_building"):
            return
        if _parts_wait(s, w, state, proposals, notes):
            return
        proposals.append(Proposal("cavern_way_build", {"type": "cavern_way", "step": "build"},
                                  f"the cavern way's next step ({state.replace('_', ' ')})", 6))
        return
    if state != "ready":
        return
    # --- built: the gate --------------------------------------------------------------
    jobs = way_jobs(s, cfg, memory, w) if on else ({"stranded": "a citizen is beyond the gate"} if beyond else {})
    rest = _d(m.get("rest"))
    hunt_ids = set()
    if "hunt" in jobs:
        targets, _u = _hunt_targets(s, cfg, memory, w)
        hunt_ids = {t.get("id") for t in targets}
        hunted = _d(s.get("hunt"))
        hunt_ids |= {h.get("target_id") for h in _l(hunted.get("hunts")) if isinstance(h, dict)}
    for x in _l(w.get("dangers")):
        if isinstance(x, dict) and x.get("id") not in hunt_ids and isinstance(x.get("d"), (int, float)) \
                and x["d"] <= int(_way_conf(cfg, "cavern_way_danger_tiles")):
            m["danger_seen"] = now
    if gate == "open":
        job = w.get("open_for") or m.get("job")
        opened = w.get("opened_tick") if isinstance(w.get("opened_tick"), int) else m.get("opened", now)
        if any(r.get("open") for r in _lure_rows(s, _door_key(w))):
            shut("a lure opened its door: the stair shut behind it", 0)
            return
        why, dist = way_danger(s, cfg, w, job if job in jobs else None, hunt_ids if job == "hunt" else None)
        if why:
            close = int(_way_conf(cfg, "cavern_way_close_tiles"))
            if beyond and (dist is None or dist > close) and "tile(s) from its door" in why:
                notes.append(f"the cavern way stays open while {w.get('beyond_first') or 'a citizen'} "
                             f"({beyond} beyond it) comes back: {why}; it shuts when it comes within {close}")
                return
            if beyond and dist is None:
                notes.append(f"the cavern way stays open while {beyond} citizen(s) come back ({why})")
                return
            shut(why + (f" ({beyond} citizen(s) still beyond it)" if beyond else ""), 0)
            return
        if not on and not beyond:
            shut("the cavern way is switched off on the Rules tab")
            return
        live = job if job in jobs else next(iter(jobs), None)
        if live is None:
            shut(f"its job ({JOB_WORDS.get(job, job or 'the work')}) is done", 2)
            m.pop("job", None)
            return
        if live != "stranded" and isinstance(opened, int) and now - opened >= float(
                _way_conf(cfg, "cavern_way_open_days")) * TICKS_PER_DAY and not beyond:
            days = int(_way_conf(cfg, "cavern_way_rest_days"))
            rest[live] = now + days * TICKS_PER_DAY
            m["rest"] = rest
            shut(f"open {int((now - opened) // TICKS_PER_DAY)} day(s) for {JOB_WORDS.get(live, live)}: shut, "
                 f"that work rests {days} day(s)", 2)
            return
        m["job"] = live
        notes.append(f"the cavern way is open for {JOB_WORDS.get(live, live)} ({jobs[live]})")
        return
    if gate == "pulling":
        return
    # shut: opened for a job, when safe
    m.pop("opened", None)
    if not jobs:
        return
    ready = [j for j in jobs if not (isinstance(rest.get(j), int) and now < rest[j])]
    if not ready:
        j = next(iter(jobs))
        notes.append(f"the cavern way stays shut: {JOB_WORDS.get(j, j)} rests "
                     f"{max(1, (rest[j] - now) // TICKS_PER_DAY)} more day(s)")
        return
    job = ready[0]
    why, _dist = way_danger(s, cfg, w, job, hunt_ids if job == "hunt" else None)
    if why:
        notes.append(f"the cavern way stays shut ({JOB_WORDS.get(job, job)} waits): {why}")
        return
    seen = m.get("danger_seen")
    clear = float(_way_conf(cfg, "cavern_way_clear_days")) * TICKS_PER_DAY
    if isinstance(seen, int) and 0 <= now - seen < clear and job != "stranded":
        notes.append(f"the cavern way stays shut a while: a danger was near its door "
                     f"{max(0, (now - seen) // (TICKS_PER_DAY // 24 or 1))} hour(s) ago")
        return
    m.update({"job": job, "opened": now})
    door = _d(w.get("door"))
    proposals.append(Proposal("cavern_way_open", {"type": "cavern_way", "step": "open", "why": job},
                              f"open the cavern way (door at elevation {door.get('elevation', '?')}) for "
                              f"{JOB_WORDS.get(job, job)}: {jobs[job]}; no danger near its door", 3))
