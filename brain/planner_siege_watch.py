"""(R29 W2, Phase 11) A siege watched from its first invader to its end, and
the record of it: the per-gate records, the alarm, the shelter, the squads,
the kill zones and the field watch, then one `siege` journal entry.

No real siege had come to any fort before R29 (the exit test of Phase 11:
"the fort survives a siege on its own and the per-gate records fill in"),
so nothing showed whether the defence's pieces worked together. This keeps,
while invaders (not thieves) are on the map, memory.holdfast.siege_watch:

    {since, last, pop0, ids (every invader seen), peak, reach (the most that
     could reach the dwarves at once), nearest, alarm (raised while it went
     on), shelter (the alert's burrow), invited ({tick, civ} when the Rules'
     test switch called it), gates {entrance id: {x, y, z, closed (seen
     shut), closed_near (the nearest invader's distance from it when first
     seen shut: the "gates close late" rule shows in it), near (the nearest
     invader ever), killzone (the kill zone's state)}}, squads {squad id:
     name} (on a kill order at the invaders, or holding a gate), caravan
     (field_watch's hostiles near a merchant at most)}

and once no invader has been seen for half a day: the summary (survived or
not, the citizens at the start and at the end, the deaths and the kills
from the atlas' located events in the siege's span, each gate's threats,
deaths and kills from the same events) goes to memory.holdfast.journal,
which siege_journal() empties into the fort's journal (kind "siege").

The Rules' "Invite a siege (test)" (lua/ai-siege-invite.lua invite_siege)
leaves its record in field_watch.invited; note_invite() turns the action's
answers into journal lines (invited, with the civs ranked by reach and
whether the event's civ held; its army set out; no army in 7 days, the next
civ; "DF sent no army: tried X, Y, Z"; the fallback's war party: "No army
came: placed N goblins of X at the map edge (the siege test)", which the
watch then takes as the siege it is), and an invitation no army reached
the map from in `invite_wait_days` is said once, with the civs tried.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick
from util import int_or_none as _int

__all__ = ["note_siege_watch", "note_invite", "siege_journal", "siege_summary", "invaders", "WATCH_CONFIG",
           "gate_they_come_at", "HEADING_CYCLES"]

WATCH_CONFIG = {
    "siege_watch_end_ticks": TICKS_PER_DAY // 2,     # no invader seen this long: the siege is over
    "invite_wait_days": 30,                          # an invitation with no army after this: said once
    "siege_watch_ids_max": 400,
}
for _k, _v in WATCH_CONFIG.items():
    PLANNER_CONFIG.setdefault(_k, _v)

HEADING_CYCLES = 2      # (R32 d) an enemy's walk projected this many brain cycles ahead to name its gate
HEADING_STEP_MAX = 40   # (R32 d) tiles a cycle at most (a fast or teleported unit's leap is not a heading)
GATE_REACH = 3          # an atlas event this near an entrance (same level) is that gate's (defence.REACH)
JOURNAL_MAX = 10


# (r6 c2) kept local: unlike util's helpers (WATCH_CONFIG)
def _c(cfg: dict | None, k: str):
    return (cfg or {}).get(k, WATCH_CONFIG[k])


def _hold(memory) -> dict:
    from planner_holdfast import holdfast
    return holdfast(memory)


def invaders(s: dict) -> list:
    """The invaders on the map now (an army's soldiers, not a thief or a
    sneaker, nor an animal), any reach."""
    th = _d(s.get("threats"))
    thieves = {x.get("id") for x in _l(_d(th.get("thieves")).get("list")) if isinstance(x, dict)}
    return [t for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and t.get("invader") and not t.get("thief") and not t.get("animal")
            and _int(t.get("id")) is not None and t.get("id") not in thieves]


def _cheb(a: dict, b: dict):
    try:
        if abs(int(a["z"]) - int(b["z"])) > GATE_REACH:
            return None
        return max(abs(int(a["x"]) - int(b["x"])), abs(int(a["y"]) - int(b["y"])))
    except (KeyError, TypeError, ValueError):
        return None


def _invited(s: dict, memory) -> dict | None:
    rec = _d(_d(s.get("field_watch")).get("invited")) or _d(_hold(memory).get("invited"))
    return rec if isinstance(rec.get("tick"), int) else None


def note_siege_watch(s: dict, memory, cfg: dict | None = None) -> None:
    """Bookkeeping each cycle (note_holdfast_cycle): the watch kept while
    invaders are on the map; its summary queued when they are gone."""
    if memory is None or "others_on_map" in _d(s.get("_errors")) \
            or not isinstance(_d(s.get("others_on_map")).get("threats"), list):
        return
    h = _hold(memory)
    now = abs_tick(s)
    _invite_wait(s, memory, h, now, cfg)
    inv = invaders(s)
    w = h.get("siege_watch") if isinstance(h.get("siege_watch"), dict) else None
    if w is not None and (not isinstance(w.get("since"), int) or now < w["since"]):
        w = None                                   # an older save or a reload from before it
        h.pop("siege_watch", None)
    if not inv:
        if w and now - int(w.get("last") or 0) > _c(cfg, "siege_watch_end_ticks"):
            entry = siege_summary(s, memory, w, now)
            if entry:
                _queue(h, entry)
            h.pop("siege_watch", None)
        return
    if w is None:
        dw = _d(s.get("dwarves"))
        w = {"since": now, "pop0": dw.get("total"), "ids": [], "peak": 0, "reach": 0, "gates": {}, "squads": {},
             "killzones": {}, "alarm": False, "caravan": 0}
        inv_rec = _invited(s, memory)
        if inv_rec and 0 <= now - inv_rec["tick"] <= 60 * TICKS_PER_DAY:
            w["invited"] = {"tick": inv_rec["tick"], "civ": inv_rec.get("civ_name"), "race": inv_rec.get("race")}
            _mine(h, inv_rec)["came"] = now
    w["last"] = now
    ids = list(dict.fromkeys(_l(w.get("ids")) + [t["id"] for t in inv]))
    w["ids"] = ids[-int(_c(cfg, "siege_watch_ids_max")):]
    w["peak"] = max(int(w.get("peak") or 0), len(inv))
    w["reach"] = max(int(w.get("reach") or 0), sum(1 for t in inv if t.get("can_reach_dwarves")))
    dists = [int(t["distance_to_nearest_dwarf"]) for t in inv if _int(t.get("distance_to_nearest_dwarf")) is not None]
    if dists:
        w["nearest"] = min(dists + ([w["nearest"]] if isinstance(w.get("nearest"), int) else []))
    if s.get("civ_alert"):
        w["alarm"] = True
        if s.get("civ_alert_shelter"):
            w["shelter"] = s.get("civ_alert_shelter")
    sp = _d(s.get("shelter_plan"))
    if sp.get("burrow") or sp.get("pick"):
        w["shelter_plan"] = sp.get("burrow") or sp.get("pick")
    _track(w, inv, now)
    # each gate: seen shut, how near the invaders were then, the nearest ever
    pos = [_d(t.get("pos")) for t in inv]
    gates = w.setdefault("gates", {})
    for e in _l(_d(s.get("entrances")).get("entrances")):
        if not isinstance(e, dict) or _int(e.get("id")) is None or not all(_int(e.get(k)) is not None for k in "xyz"):
            continue
        g = gates.setdefault(str(e["id"]), {"x": e["x"], "y": e["y"], "z": e["z"], "kind": e.get("kind")})
        ds = [d for d in (_cheb(p, e) for p in pos) if d is not None]
        near = min(ds) if ds else None
        if near is not None:
            g["near"] = min(near, g["near"]) if isinstance(g.get("near"), int) else near
        # (R32 d) `closing` is the scan's "a gate being built here", not a shut
        # gate: never counted as shut. The watcher's own distance when it shut
        # it (ai-gates `closed_near`, read at its look) is the record's, the
        # brain's cycle comes up to a day later (A 26 Nov: "0 tiles off")
        if e.get("closed"):
            if not g.get("closed"):
                g["closed"], g["closed_tick"] = True, now
                wn = _int(e.get("closed_near"))
                g["closed_near"] = wn if wn is not None else near
                g["closed_near_by"] = "watcher" if wn is not None else "brain"
        elif g.get("closed"):
            g["opened"] = int(g.get("opened") or 0) + 1
    for k in _l(_d(s.get("killzones")).get("entrances")):
        if isinstance(k, dict) and _int(k.get("id")) is not None and k.get("state"):
            w.setdefault("killzones", {})[str(k["id"])] = k.get("state")
    ids_now = {t["id"] for t in inv}
    for q in _l(_d(s.get("military")).get("squads")):
        if not isinstance(q, dict) or q.get("id") is None or not q.get("ai_orders"):
            continue
        kill = {x for x in _l(q.get("kill_ids")) if _int(x) is not None}
        if kill & ids_now or q.get("stationed") or q.get("sheltering"):
            w.setdefault("squads", {})[str(q["id"])] = str(q.get("name") or q["id"])[:40]
    fw = _d(s.get("field_watch"))
    w["caravan"] = max(int(w.get("caravan") or 0), len(_l(fw.get("caravan"))))
    h["siege_watch"] = w


def _track(w: dict, inv: list, now: int) -> None:
    """(R32 d) Each invader's last two positions read at different ticks
    (w["track"]: {id: {p, t, pp, pt}}), so a heading can be read whichever
    side of the plan this bookkeeping runs."""
    tr = w["track"] if isinstance(w.get("track"), dict) else {}
    keep = {}
    for t in inv:
        p = _d(t.get("pos"))
        if not all(_int(p.get(k)) is not None for k in "xyz"):
            continue
        k = str(t["id"])
        old = _d(tr.get(k))
        cur = [int(p["x"]), int(p["y"]), int(p["z"])]
        if isinstance(old.get("t"), int) and old["t"] < now:
            keep[k] = {"p": cur, "t": now, "pp": old.get("p"), "pt": old["t"]}
        elif isinstance(old.get("t"), int) and old["t"] == now:
            keep[k] = dict(old, p=cur)
        else:
            keep[k] = {"p": cur, "t": now}
    w["track"] = keep


def _prev_pos(memory, tid, now):
    """(R32 d) Where this invader was at the brain's last read before now (None unknown)."""
    if memory is None:
        return None
    w = _d(_d(getattr(memory, "holdfast", None)).get("siege_watch"))
    e = _d(_d(w.get("track")).get(str(tid)))
    if isinstance(e.get("t"), int) and isinstance(now, int) and e["t"] < now and isinstance(e.get("p"), list):
        return e["p"]
    if isinstance(e.get("pt"), int) and isinstance(now, int) and e["pt"] < now and isinstance(e.get("pp"), list):
        return e["pp"]
    return None


def gate_they_come_at(s: dict, rows: list, memory=None):
    """(R32 d) The surface entrance most of these enemies are heading to, and
    {entrance id: enemies heading to it}. Fort A (26 Nov): 25 goblins set down
    at the map edge, the squads held gate 3, nearest to the one goblin
    closest to any gate, while 31 came at gate 1. Now each enemy's gate is the
    one nearest to where it will be HEADING_CYCLES cycles on (its walk since
    the last cycle, siege_watch's track; where it stands without one), and the
    gate with the most wins (a tie: the one the squads hold already, then the
    nearest enemy, then the id). Read again each cycle, so the pick follows
    them as they move. (None, {}) without a gate or a position."""
    es = [e for e in _l(_d(s.get("entrances")).get("entrances")) if isinstance(e, dict)
          and e.get("kind") != "cavern" and all(_int(e.get(k)) is not None for k in ("x", "y", "z"))]
    if not es:
        return None, {}
    now = abs_tick(s)

    def dist(p, e):
        return max(abs(p[0] - e["x"]), abs(p[1] - e["y"])) + 3 * abs(p[2] - e["z"])

    counts, nearest = {}, {}
    for t in rows:
        p = _d(t.get("pos"))
        if not all(_int(p.get(k)) is not None for k in "xyz"):
            continue
        cur = [int(p["x"]), int(p["y"]), int(p["z"])]
        aim = cur
        prev = _prev_pos(memory, t.get("id"), now)
        if prev and len(prev) >= 3:
            dx, dy = cur[0] - int(prev[0]), cur[1] - int(prev[1])
            if max(abs(dx), abs(dy)) <= HEADING_STEP_MAX:
                aim = [cur[0] + HEADING_CYCLES * dx, cur[1] + HEADING_CYCLES * dy, cur[2]]
        g = min(es, key=lambda e: (dist(aim, e), dist(cur, e), e.get("id") or 0))
        counts[g["id"]] = counts.get(g["id"], 0) + 1
        d = dist(cur, g)
        nearest[g["id"]] = min(d, nearest.get(g["id"], d))
    if not counts:
        return None, {}
    # the gate a squad of the AI's already holds (stationed within 6 tiles): a tie keeps it
    held = None
    for q in _l(_d(s.get("military")).get("squads")):
        st = _d(q.get("stationed")) if isinstance(q, dict) and q.get("ai_orders") else {}
        if all(_int(st.get(k)) is not None for k in "xyz"):
            at = [int(st["x"]), int(st["y"]), int(st["z"])]
            g = min(es, key=lambda e: dist(at, e))
            if dist(at, g) <= 6:
                held = g["id"]
                break
    best = min(counts, key=lambda i: (-counts[i], 0 if i == held else 1, nearest[i], i if isinstance(i, int) else 0))
    return next(e for e in es if e["id"] == best), counts


def _queue(h: dict, entry: dict) -> None:
    j = h.get("journal") if isinstance(h.get("journal"), list) else []
    j.append(entry)
    h["journal"] = j[-JOURNAL_MAX:]


def _events(memory, start: int, end: int) -> list:
    a = _d(getattr(memory, "atlas", None))
    return [e for e in _l(a.get("events")) if isinstance(e, dict) and isinstance(e.get("t"), int)
            and start <= e["t"] <= end]


def _spot(near: str):
    try:
        x, y, z = (int(v) for v in near.split(":", 1)[1].split(","))
        return {"x": x, "y": y, "z": z}
    except (IndexError, ValueError):
        return None


def siege_summary(s: dict, memory, w: dict, now: int) -> dict | None:
    """The record of a siege that has ended (the watch `w`): one journal
    entry with every gate's numbers. None for a watch with no invader."""
    ids = _l(w.get("ids"))
    if not ids:
        return None
    start, end = int(w.get("since") or now), int(w.get("last") or now)
    evs = _events(memory, start, now)
    deaths = sum(1 for e in evs if e.get("k") == "death")
    kills = sum(1 for e in evs if e.get("k") in ("kill", "beast_slain"))
    pop = _d(s.get("dwarves")).get("total")
    survived = isinstance(pop, int) and pop > 0
    gates = []
    for gid, g in sorted(_d(w.get("gates")).items(), key=lambda kv: str(kv[0])):
        g = dict(_d(g), id=int(gid) if str(gid).lstrip("-").isdigit() else gid)
        here = [e for e in evs if str(e.get("near") or "").startswith("entrance:")
                and (lambda sp: sp is not None and _cheb(sp, g) is not None and _cheb(sp, g) <= GATE_REACH)(
                    _spot(str(e["near"])))]
        g["threats"] = sum(1 for e in here if e.get("k") == "threat_at_gate")
        g["deaths"] = sum(1 for e in here if e.get("k") == "death")
        g["kills"] = sum(1 for e in here if e.get("k") in ("kill", "beast_slain"))
        kz = _d(w.get("killzones")).get(str(gid))
        if kz:
            g["killzone"] = kz
        gates.append(g)
    days = round((end - start) / TICKS_PER_DAY, 1)
    inv = _d(w.get("invited"))
    who = f"{inv.get('civ') or 'an enemy civ'}'s army (invited by the Rules' test switch)" if inv else "a siege"
    shut = [g for g in gates if g.get("closed")]
    gate_words = "; ".join(
        f"gate {g['id']} x{g.get('x')} y{g.get('y')}: "
        + (f"shut with the nearest enemy {g['closed_near']} tiles off" if g.get("closed") and isinstance(g.get("closed_near"), int)
           else "shut" if g.get("closed") else "never shut")
        + f", {g['threats']} at it, {g['deaths']} died there, {g['kills']} killed there"
        + (f", kill zone {g['killzone']}" if g.get("killzone") else "")
        for g in gates if g.get("closed") or g["threats"] or g["deaths"] or g["kills"] or isinstance(g.get("near"), int)
    )[:600]
    squads = sorted(_d(w.get("squads")).values())
    text = (f"Siege over: {who}, {len(ids)} invaders (at most {w.get('peak')} at once, {w.get('reach')} in reach), "
            f"{days} days; the fort {'survived' if survived else 'fell'} ({w.get('pop0')} citizens at the start, "
            f"{pop} now); {deaths} citizens died, {kills} enemies killed; the alarm "
            + ("sounded" + (f" (shelter: {w['shelter']})" if w.get("shelter") else "") if w.get("alarm") else "never sounded")
            + f"; squads: {', '.join(squads) if squads else 'none sent'}; gates shut {len(shut)} of {len(gates)}"
            + (f" ({gate_words})" if gate_words else "")
            + (f"; {w['caravan']} hostile(s) at a caravan" if w.get("caravan") else ""))
    return {"what": "siege_summary", "invited": bool(inv) or None, "civ": inv.get("civ"), "since": start,
            "until": end, "days": days, "invaders": len(ids), "peak": w.get("peak"), "reach": w.get("reach"),
            "nearest": w.get("nearest"), "survived": survived, "citizens_start": w.get("pop0"), "citizens_end": pop,
            "deaths": deaths, "kills": kills, "alarm": bool(w.get("alarm")), "shelter": w.get("shelter"),
            "shelter_plan": w.get("shelter_plan"), "squads": squads, "gates": gates,
            "field_watch": {"caravan_hostiles": w.get("caravan") or 0}, "text": text}


def _mine(h: dict, rec: dict) -> dict:
    """memory's copy of the invitation `rec` (the bridge's record): a new
    invitation (another tick) replaces the copy of the one before."""
    mine = h.get("invited") if isinstance(h.get("invited"), dict) else None
    if mine is None or mine.get("tick") != rec.get("tick"):
        mine = dict(rec)
        h["invited"] = mine
    else:
        for k in ("state", "tries", "civ_name", "civ_id", "race", "relation", "how", "ranking"):
            if k in rec:
                mine[k] = rec[k]
    return mine


def _civ(t: dict) -> str:
    return str(t.get("civ_name") or (f"civ {t.get('civ_id')}" if t.get("civ_id") is not None else "no civ named"))


def _tried(r: dict) -> list:
    """The civs tried by an invitation, by name (the bridge's `tried`, or its tries)."""
    names = [str(x) for x in _l(r.get("tried")) if x]
    return names or [_civ(t) for t in _l(r.get("tries")) if isinstance(t, dict)]


def _ranking_words(r: dict) -> str:
    rows = [x for x in _l(r.get("ranking")) if isinstance(x, dict)]
    return "; ".join(f"{x.get('name') or x.get('id')} ({x.get('relation')}, "
                     + (f"{x['reach']} world tiles" if isinstance(x.get("reach"), int) else "reach unknown") + ")"
                     for x in rows[:5])


def _set_words(r: dict) -> str:
    if r.get("entity_set") is True:
        return "; the event's civ read back: set"
    if r.get("civ_id") is not None and r.get("entity_set") is False:
        return f"; the event's civ read back: NOT set (it holds {r.get('entity_read')})"
    return ""


def note_invite(p, r: dict, state: dict, memory, now: int) -> None:
    """After acting (note_holdfast): the invitation's answer as a journal
    line, and its record kept for the watch. (0.105.123) A daily look at a
    waiting invitation says nothing until its army sets out (came), the next
    civ is tried (retried) or it ends with none (gave_up)."""
    a = p.action if isinstance(getattr(p, "action", None), dict) else {}
    if memory is None or a.get("type") != "invite_siege" or a.get("dry_run") or not isinstance(r, dict):
        return
    h = _hold(memory)
    if not r.get("ok"):
        if r.get("done") or r.get("rejected"):
            _queue(h, {"what": "siege_invite_refused", "text": f"Siege invitation refused: {str(r.get('error'))[:200]}"})
        else:
            _queue(h, {"what": "siege_invite_failed", "text": f"Siege invitation failed: {str(r.get('error'))[:200]}"})
        return
    civ = r.get("civ_name") or (f"civ {r.get('civ_id')}" if r.get("civ_id") is not None else None)
    rec = {"tick": r.get("tick") if isinstance(r.get("tick"), int) else now, "civ_name": civ,
           "civ_id": r.get("civ_id"), "race": r.get("race"), "relation": r.get("relation"), "how": r.get("how"),
           "state": r.get("state"), "invitation": r.get("invitation")}
    if r.get("tried") is not None:
        rec["tried"] = _l(r.get("tried"))
    mine = _mine(h, rec)
    tried = _tried(r)
    if r.get("came"):
        mine["state"], mine["set_out"] = "came", now
        text = (f"The invited siege set out: {r.get('armies') or 0} army(ies) and {r.get('controllers') or 0} "
                f"army order(s) for this fort, {r.get('invaders') or 0} invader(s) on the map ({civ or 'no civ named'}"
                f"; tried {', '.join(tried) or 'none'}); the invitation is this fort's one")
        _queue(h, {"what": "siege_invite_came", "civ": civ, "tried": tried, "text": text})
    elif r.get("retried"):
        text = (f"DF sent no army from {r.get('no_army')} in 7 days of the invited siege: the next civ by reach, "
                f"{civ} ({r.get('race')}, {r.get('relation')}), invited (by {r.get('how')})" + _set_words(r)
                + f"; tried so far: {', '.join(tried)}")
        _queue(h, {"what": "siege_invite_retried", "civ": civ, "no_army": r.get("no_army"), "tried": tried,
                   "entity_set": r.get("entity_set"), "text": text})
    elif r.get("gave_up") and isinstance(r.get("spawned"), dict):
        sp = r["spawned"]
        mine["state"], mine["spawned"] = "came", dict(sp)
        race = str(sp.get("race") or "goblin").lower()
        text = (f"No army came: placed {sp.get('count')} {race}s of {sp.get('civ_name') or 'the enemy civ'} at the map "
                f"edge (the siege test), x{sp.get('x')} y{sp.get('y')} z{sp.get('z')}"
                + ("" if sp.get("equipped") else ", unarmed (create-unit's equipment failed)")
                + f"; DF sent no army: tried {', '.join(tried) or 'no civ'} (7 days each). Once a fort")
        _queue(h, {"what": "siege_spawned", "tried": tried, "spawned": dict(sp), "text": text})
    elif r.get("gave_up"):
        mine["state"] = "no_army"
        text = (f"DF sent no army: tried {', '.join(tried) or 'no civ'} (7 days each); the invitation ended"
                + (f" (no war party placed: {str(r.get('spawn_error'))[:120]})" if r.get("spawn_error") else "")
                + ". The Rules' \"Invite a siege (test)\" turned on again starts a new one")
        _queue(h, {"what": "siege_invite_no_army", "tried": tried, "spawn_error": r.get("spawn_error"),
                   "spawn_info": r.get("spawn_info"), "text": text})
    elif r.get("invited") or not r.get("waiting"):
        ranks = _ranking_words(r)
        text = (f"Siege invited (the Rules' test switch{', again' if r.get('reinvite') else ''}): DFHack's force "
                f"queued DF's army event ({r.get('event')}, by {r.get('how')})"
                + (f" for {civ} ({r.get('race')}, {r.get('relation')})" if civ else ", no civ at war found: DF picks the attacker")
                + _set_words(r)
                + (f"; ranked by reach: {ranks}" if ranks else "")
                + "; recorded in the save, its army looked for 7 days (then the next civ, 3 at most); the switch turned off")
        _queue(h, {"what": "siege_invited", "civ": civ, "race": r.get("race"), "relation": r.get("relation"),
                   "how": r.get("how"), "event": r.get("event"), "entity_set": r.get("entity_set"),
                   "ranking": _l(r.get("ranking"))[:5], "reinvite": r.get("reinvite"), "text": text})


def _invite_wait(s: dict, memory, h: dict, now: int, cfg) -> None:
    """An invitation no army reached the map from in `invite_wait_days`:
    said once, with the civs tried (an invitation that ended with no army
    said so itself: nothing more)."""
    rec = _invited(s, memory)
    if not rec:
        return
    mine = _mine(h, rec)
    if mine.get("came") or mine.get("no_show") or h.get("siege_watch") or rec.get("state") == "no_army":
        return
    if now - rec["tick"] > int(_c(cfg, "invite_wait_days")) * TICKS_PER_DAY:
        mine["no_show"] = now
        tried = _tried(rec) or [_civ(rec)]
        how = ("an army set out (DF's army order for this fort) but none reached the map"
               if rec.get("state") == "came" else
               "DF's army event found no army to send, or it is still on its way")
        _queue(h, {"what": "siege_no_show", "civ": rec.get("civ_name"), "tried": tried, "state": rec.get("state"),
                   "text": f"No army came in {_c(cfg, 'invite_wait_days')} days of the invited siege "
                           f"(tried {', '.join(tried)}; by {rec.get('how')}): {how}"})


def siege_journal(memory) -> list:
    """The journal entries waiting (each written once)."""
    if memory is None:
        return []
    h = _hold(memory)
    out = [e for e in _l(h.get("journal")) if isinstance(e, dict)]
    h["journal"] = []
    return out
