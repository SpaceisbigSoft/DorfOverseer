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

The Rules' "Invite a siege (test)" (lua/ai-siege.lua invite_siege) leaves
its record in field_watch.invited; note_invite() turns the action's answer
into a journal line, and an invitation no army followed in
`invite_wait_days` is said once.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import PLANNER_CONFIG, TICKS_PER_DAY, abs_tick
from util import int_or_none as _int

__all__ = ["note_siege_watch", "note_invite", "siege_journal", "siege_summary", "invaders", "WATCH_CONFIG"]

WATCH_CONFIG = {
    "siege_watch_end_ticks": TICKS_PER_DAY // 2,     # no invader seen this long: the siege is over
    "invite_wait_days": 30,                          # an invitation with no army after this: said once
    "siege_watch_ids_max": 400,
}
for _k, _v in WATCH_CONFIG.items():
    PLANNER_CONFIG.setdefault(_k, _v)

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
            h.setdefault("invited", dict(inv_rec))["came"] = now
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
        if e.get("closed") or e.get("closing"):
            if not g.get("closed"):
                g["closed"], g["closed_tick"] = True, now
                g["closed_near"] = near
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


def note_invite(p, r: dict, state: dict, memory, now: int) -> None:
    """After acting (note_holdfast): the invitation's answer as a journal
    line, and its record kept for the watch."""
    a = p.action if isinstance(getattr(p, "action", None), dict) else {}
    if memory is None or a.get("type") != "invite_siege" or a.get("dry_run") or not isinstance(r, dict):
        return
    h = _hold(memory)
    if r.get("ok"):
        civ = r.get("civ_name") or (f"civ {r.get('civ_id')}" if r.get("civ_id") is not None else None)
        h["invited"] = {"tick": r.get("tick") if isinstance(r.get("tick"), int) else now, "civ_name": civ,
                        "civ_id": r.get("civ_id"), "race": r.get("race"), "relation": r.get("relation"),
                        "how": r.get("how")}
        text = (f"Siege invited (the Rules' test switch): DFHack's force queued DF's army event ({r.get('event')}, "
                f"by {r.get('how')})" + (f" for {civ} ({r.get('race')}, {r.get('relation')})" if civ else
                                         ", no civ at war found: DF picks the attacker")
                + "; recorded in the save (never again at this fort) and the switch turned off")
        _queue(h, {"what": "siege_invited", "civ": civ, "race": r.get("race"), "relation": r.get("relation"),
                   "how": r.get("how"), "event": r.get("event"), "text": text})
    elif r.get("done") or r.get("rejected"):
        _queue(h, {"what": "siege_invite_refused", "text": f"Siege invitation refused: {str(r.get('error'))[:200]}"})
    else:
        _queue(h, {"what": "siege_invite_failed", "text": f"Siege invitation failed: {str(r.get('error'))[:200]}"})


def _invite_wait(s: dict, memory, h: dict, now: int, cfg) -> None:
    """An invitation no army followed in `invite_wait_days`: said once."""
    rec = _invited(s, memory)
    if not rec:
        return
    mine = h.setdefault("invited", dict(rec))
    if mine.get("came") or mine.get("no_show") or h.get("siege_watch"):
        return
    if now - rec["tick"] > int(_c(cfg, "invite_wait_days")) * TICKS_PER_DAY:
        mine["no_show"] = now
        _queue(h, {"what": "siege_no_show", "civ": rec.get("civ_name"),
                   "text": f"No army came in {_c(cfg, 'invite_wait_days')} days of the invited siege "
                           f"({rec.get('civ_name') or 'no civ named'}, by {rec.get('how')}): DF's army event "
                           "found no army to send, or it is still on its way"})


def siege_journal(memory) -> list:
    """The journal entries waiting (each written once)."""
    if memory is None:
        return []
    h = _hold(memory)
    out = [e for e in _l(h.get("journal")) if isinstance(e, dict)]
    h["journal"] = []
    return out
