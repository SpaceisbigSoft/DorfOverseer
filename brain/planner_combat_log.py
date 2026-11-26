"""(R29 W6) The result of each hunt, lure and sortie, journalled once.

Why: by 25 Nov 21:30 the six forts had sent 26 hunts (A 2, E 24: two kills,
a Giant Black Bear and an Agitated Giant Wren, the rest called back after 3
days), F one sortie (16:45, three squads out through the opened gates at a
Cyclops, killed 16:46 by an axedwarf) and no lure, yet none of it showed in
the journal: the hunt's history lived only in the report (`hunt.history`,
the last 20), the sortie's only in memory.atlas until the gates shut, and
nothing at all said how either ended. Each now leaves one journal record
(kind `combat_result`, overseer_cycle's journals step):

  {of: hunt | lure | sortie, target, target_id(s), squad(s), outcome, lost,
   days, text}

outcome: `killed` (the target died), `caught` (caged), `shut in` (a lure
pocket closed on it), `fled` (it left the map or the lure's reach), `lost`
(the party came back having lost soldiers, the target alive), `back` (came
home with no loss, the target alive: a hunt called back, an empty lure).

Its own bookkeeping is kept in memory.hunt_seen (planner_hunt's dict, saved
with the fort's memory): `logged` (hunt history keys), `sortie` (the sortie
under way: targets, squads, deaths seen), `lures` (each pocket's last phase).
Reads only; proposes nothing.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import TICKS_PER_DAY, abs_tick
from planner_hunt import hunt_rows, hunt_seen
from util import trunc_or_zero as _int

__all__ = ["combat_journal", "sortie_party", "hunt_outcome", "LOGGED_KEEP"]

LOGGED_KEEP = 120          # hunt history keys remembered (the bridge keeps 20)


def _deaths(events) -> list:
    return [e for e in _l(events) if isinstance(e, dict) and e.get("kind") == "death" and not e.get("again")]


def hunt_outcome(e: dict) -> str:
    """The bridge's hunt outcome (won | caged | gone | dropped | recalled) as a result."""
    out = e.get("outcome") if e.get("outcome") is not None else e.get("result")
    if out == "won" or e.get("target_dead") is True:
        return "killed"
    if out == "caged":
        return "caught"
    if out == "gone":
        return "fled"
    lost = _int(e.get("soldiers_lost")) if e.get("soldiers_lost") is not None else _int(e.get("lost"))
    return "lost" if lost > 0 else "back"


def _hunt_results(s: dict, seen: dict) -> list:
    rows = hunt_rows(s)
    if rows is None:
        return []
    _t, squads, _h, hist = rows
    names = {q["id"]: q.get("name") for q in squads}
    logged = [k for k in _l(seen.get("logged")) if isinstance(k, str)]
    out = []
    for e in hist:
        end = e.get("end_tick") if e.get("end_tick") is not None else e.get("tick")
        sid, tid = e.get("squad_id"), e.get("target_id")
        key = f"{sid}:{tid}:{end}:{e.get('outcome') or e.get('result')}"
        if key in logged:
            continue
        logged.append(key)
        res = hunt_outcome(e)
        lost = _int(e.get("soldiers_lost")) if e.get("soldiers_lost") is not None else _int(e.get("lost"))
        n = _int(e.get("soldiers_at_start")) or _int(e.get("of"))
        days = (round((_int(end) - _int(e.get("since_tick"))) / TICKS_PER_DAY, 1)
                if isinstance(end, int) and isinstance(e.get("since_tick"), int) else None)
        who = str(e.get("target_name") or f"target {tid}")
        squad = str(names.get(sid) or f"squad {sid}")
        text = (f"hunt: {squad} ({n} soldiers) after {who}: {res}"
                + (f", {lost} soldier(s) lost" if lost else "")
                + (f", {days} day(s) out" if days is not None else "")
                + (f" ({e.get('reason')})" if isinstance(e.get("reason"), str) and e.get("reason") else ""))
        out.append({"of": "hunt", "target": who, "target_id": tid, "squad": squad, "squad_id": sid,
                    "outcome": res, "df_outcome": e.get("outcome"), "soldiers": n, "lost": lost, "days": days,
                    "text": text})
    seen["logged"] = logged[-LOGGED_KEEP:]
    return out


def sortie_party(s: dict, ids) -> dict:
    """The sortie's targets {id (str): name} and squads {id (str): soldiers}:
    the AI squads whose kill orders name one of `ids` (planner_gates_lockdown
    keeps this in memory.atlas["sortie"] when it opens the gates)."""
    want = {i for i in _l(ids) if isinstance(i, int)}
    rows = {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    targets = {str(i): str(_d(rows.get(i)).get("name") or f"enemy {i}") for i in sorted(want)}
    squads = {}
    for q in _l(_d(s.get("military")).get("squads")):
        if isinstance(q, dict) and q.get("ai_orders") and isinstance(q.get("kill_ids"), list) \
                and want & {x for x in q["kill_ids"] if isinstance(x, int)} and q.get("id") is not None:
            squads[str(q["id"])] = _int(q.get("members")) or _int(q.get("size"))
    return {"targets": targets, "squads": squads}


def _sortie_results(s: dict, memory, seen: dict, events) -> list:
    atlas = getattr(memory, "atlas", None)
    a = _d(atlas.get("sortie")) if isinstance(atlas, dict) else {}
    rec = seen.get("sortie") if isinstance(seen.get("sortie"), dict) else None
    if a and rec is None:
        rec = {"since": a.get("since"), "targets": {}, "squads": {}, "killed": [], "lost": 0}
    if rec is None:
        return []
    for k, v in _d(a.get("targets")).items():
        rec["targets"].setdefault(str(k), v)
    for k, v in _d(a.get("squads")).items():
        rec["squads"][str(k)] = max(_int(v), _int(rec["squads"].get(str(k))))
    tids = {int(k) for k in rec["targets"] if str(k).lstrip("-").isdigit()}
    for e in _deaths(events):
        if e.get("unit_id") in tids and e.get("unit_id") not in rec["killed"]:
            rec["killed"].append(e["unit_id"])
        elif e.get("killer_id") in tids and not e.get("animal") and not e.get("hostile"):
            rec["lost"] = _int(rec.get("lost")) + 1      # one of the fort's people killed by a target
    if a:
        seen["sortie"] = rec
        return []
    # the gates' record is gone: the squads are back (or no squad is out at them)
    seen.pop("sortie", None)
    if not rec["targets"]:
        return []
    here = {t.get("id") for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    killed = [i for i in tids if i in rec["killed"]]
    left = [i for i in tids if i in here and i not in killed]
    lost = _int(rec.get("lost"))
    if killed and not left:
        res = "killed"
    elif lost:
        res = "lost"
    elif left:
        res = "back"
    else:
        res = "fled"
    since = rec.get("since")
    days = round((abs_tick(s) - since) / TICKS_PER_DAY, 1) if isinstance(since, int) else None
    who = ", ".join(rec["targets"].values())
    squads = sorted(rec["squads"])
    text = (f"sortie: {len(squads)} squad(s) ({', '.join(squads) or '?'}) out through the gates at {who}: {res}"
            + (f" ({len(killed)} of {len(tids)} killed)" if len(tids) > 1 else "")
            + (f", {lost} of the fort's people killed" if lost else "")
            + (f", {days} day(s)" if days is not None else ""))
    return [{"of": "sortie", "target": who, "target_ids": sorted(tids), "squad": squads,
             "soldiers": sum(_int(v) for v in rec["squads"].values()), "outcome": res, "killed": len(killed),
             "lost": lost, "days": days, "text": text}]


def _lure_results(s: dict, seen: dict, events) -> list:
    L = _d(s.get("lures"))
    if not isinstance(L.get("lures"), list):
        return []
    dead = {e.get("unit_id") for e in _deaths(events)}
    last = seen.get("lures") if isinstance(seen.get("lures"), dict) else {}
    now = {}
    out = []
    for r in _l(L.get("lures")):
        if not isinstance(r, dict) or not isinstance(r.get("key"), str):
            continue
        key, ph = r["key"], r.get("phase")
        p = _d(last.get(key))
        who = str(r.get("beast_name") or r.get("beast_kind") or "the beast")
        cur = {"phase": ph, "open": bool(r.get("open")), "beast": r.get("beast_id"), "gone": bool(r.get("beast_gone")),
               "logged": p.get("logged") if p.get("beast") == r.get("beast_id") else None}
        res = None
        if (ph == "caught" or r.get("caught") or _d(r.get("done")).get("how") == "caught") and cur["logged"] != "caught":
            res = "caught"
        elif (ph == "shut_in" or _d(r.get("done")).get("how") == "shut_in") and cur["logged"] not in ("shut in",
                                                                                                         "caught"):
            res = "shut in"
        elif r.get("beast_gone") and p and not p.get("gone") and cur["logged"] not in ("caught", "shut in"):
            res = "killed" if r.get("beast_id") in dead else "fled"
        elif p.get("open") and not r.get("open") and ph in ("ready", "building") and not r.get("beast_gone"):
            res = "back"                                   # open its time, shut: nothing came
        if res:
            if res != "back":
                cur["logged"] = res
            o = _d(r.get("opening"))
            text = (f"lure: the pocket behind the cavern door at x{o.get('x')} y{o.get('y')} z{o.get('z')} for "
                    f"{who}: {res}" + (" (open its time, nothing came; locked again)" if res == "back" else ""))
            out.append({"of": "lure", "target": who, "target_id": r.get("beast_id"), "squad": None,
                        "lure": key, "outcome": res, "text": text})
        now[key] = cur
    seen["lures"] = now
    return out


def combat_journal(s: dict, memory, events=None) -> list[dict]:
    """The results to journal this cycle (each once): hunts from the bridge's
    history, the sortie once the gates' record of it goes, the lure pockets'
    catches, escapes and empty openings."""
    if memory is None or not isinstance(s, dict):
        return []
    seen = hunt_seen(memory)
    out = []
    for fn, args in ((_hunt_results, (s, seen)), (_sortie_results, (s, memory, seen, events)),
                     (_lure_results, (s, seen, events))):
        try:
            out += fn(*args)
        except Exception:  # noqa: BLE001  (one reader failing leaves the others)
            continue
    return out
