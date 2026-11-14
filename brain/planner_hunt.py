"""(0.105.45) Hunting: the fort's squads go out after a threat they can beat.

Why (the player, 14 Nov: "the dwarves can kill forgotten beasts and other
enemies: by offence"): until now the squads only met what came to them (the
military rules: threats that can reach the dwarves) and the dwarves hid from
great dangers. This rule judges a threat that can NOT yet reach the dwarves
against the fort's squads and, when they clearly win, sends a party after it,
with a reserve kept home and a retreat if it goes badly.

It reads the bridge's `hunt` section (lua/ai-hunt.lua, by H1):

  targets[]  id, name, kinds, great_danger, size, pos, layer, region
             (surface | cavern | inside), flier, fire_breather, ambush, thief,
             wounded_visitor, route {ok, length, blocked_by: none | seal |
             gate | no_path}, near_workers, seen_ticks, can_reach_dwarves
  squads[]   id, name, soldiers, power, armed, armored, ranged, at_home,
             hunting (target id or None), sheltering
  hunts[]    squad_id, target_id, since_tick, soldiers_at_start,
             soldiers_now, wounded, target_alive, target_pos
  history[]  the last 20 outcomes: kinds, outcome (won | caged | gone |
             dropped | recalled), lost (or soldiers_lost), of, tick (or
             end_tick), target_dead, reason

and proposes the bridge's two actions:

  {"type": "hunt_send", "squad_ids": [..], "target_id": N}     rule "hunt"
  {"type": "hunt_recall", "squad_ids": [..], "reason": str}    rule "squad_recall"

What it does:
  * which targets: one with a way to it (route.ok) that can't reach the
    dwarves yet (those are the military rules' fight: never sent twice).
    A cavern beast behind the AI's seal is left to the lure and cut-off
    rules (said). Never one whose fight or hunt was called off.
  * in what order: a wounded visitor who makes the dwarves drop their jobs
    and thieves first (cheap), then ambushes near workers, then the great
    dangers (forgotten beasts, titans, megabeasts) by the workers near them
    and their distance, then other hostiles; one hunt at a time for the
    great dangers, one new hunt a cycle.
  * judged: the party's summed power against planner_military.threat_power
    times what the fort learned of that kind (memory.fight_factor), at
    `hunt_ratio` (a hunt is optional: 1.5 times the defence's fight_ratio),
    raised by Caution and lowered by Militarism within bounds. A fire
    breather or a flier only with a party all of crossbows.
  * the party: the smallest set of squads at home (not sheltering, not on
    another order this cycle) that clears the ratio, while those left home
    are at least max(3, `hunt_reserve_share` of all soldiers) and, with two
    squads or more, one whole squad stays.
  * never during a siege or with invaders or great dangers in reach, in a
    crisis, with the alarm up, with a great danger's fight under way, with
    the Rules' attack policy "never" or the Rules switch `hunt` off. `small`
    hunts thieves, ambushes and wounded visitors only; `ai` (the default)
    the great dangers too, unless Militarism is very low or Caution very high.
  * the retreat: a hunt comes back when a third of its soldiers are lost,
    half of those left are wounded, it lasts over `hunt_max_days`, or the
    target turns out a fire breather or a flier the party can't handle; a
    lost one marks the target (never hunted again while it is on the map),
    a timed-out one rests it a few days. With the switch off or a siege,
    the hunters come home. (The bridge's `hunt` is in the full report only:
    the retreat is judged once a game day until `hunt` joins PULSE_SECTIONS.)
  * learning: each history entry once (memory.hunt_seen["learned"]): a won
    (or caged) hunt makes that kind 10% weaker in the AI's eyes, a lost or bloody one
    50% stronger (capped as planner_military's _fight_outcome); a target
    gone is no lesson.
Without the section (an older bridge, the fixtures) nothing is proposed or said.
"""

from __future__ import annotations

import itertools
import math

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, abs_tick, player_rules, reachable_threats, _traits
from planner_military import called_off_ids, fight_key, threat_power

__all__ = ["HUNT_MODES", "hunt_mode", "hunt_ratio", "hunt_rows", "hunt_seen", "hunt_off_ids", "party_for",
           "_hunt_rule", "note_hunt_cycle"]

HUNT_MODES = ("off", "small", "ai")
NOTE_MAX = 8            # targets said each cycle (the rest counted)
PARTY_SQUADS_MAX = 8    # squads looked at for a party (subsets of up to 2^8)


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _int(v) -> int:
    n = _num(v)
    return int(n) if n is not None else 0


def _id(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def hunt_mode(s: dict) -> str:
    """The Rules switch `hunt`: off / small / ai (the default)."""
    v = player_rules(s).get("hunt")
    if v not in HUNT_MODES:
        st = s.get("settings") if isinstance(s.get("settings"), dict) else {}
        v = st.get("hunt")
    return v if v in HUNT_MODES else "ai"


def hunt_seen(memory) -> dict:
    """memory.hunt_seen, made a dict if it isn't one (an old save):
    {off: {target id (str): {tick, why}}, learned: [keys]}."""
    h = getattr(memory, "hunt_seen", None) if memory is not None else None
    if not isinstance(h, dict):
        h = {}
        if memory is not None:
            try:
                memory.hunt_seen = h
            except AttributeError:
                pass
    return h


def hunt_off_ids(s: dict, memory, cfg: dict) -> dict:
    """Targets the hunt rule leaves alone: id -> why (a lost hunt: while on
    the map; a timed-out one: `hunt_rest_days`)."""
    out = {}
    now = abs_tick(s)
    rest = int(cfg.get("hunt_rest_days", 5)) * TICKS_PER_DAY
    for k, v in _d(hunt_seen(memory).get("off")).items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            continue
        v = _d(v)
        if v.get("why") == "time" and isinstance(v.get("tick"), int) and now - v["tick"] >= rest:
            continue
        out[i] = v.get("why") or "lost"
    return out


def hunt_rows(s: dict) -> tuple[list, list, list, list] | None:
    """(targets, squads, hunts, history) of the bridge's `hunt` section, or
    None without it (an older bridge, a failed read)."""
    h = s.get("hunt")
    if not isinstance(h, dict) or h.get("error") or "hunt" in _d(s.get("_errors")):
        return None
    targets = [t for t in _l(h.get("targets")) if isinstance(t, dict) and _id(t.get("id")) is not None]
    squads = [q for q in _l(h.get("squads")) if isinstance(q, dict) and _id(q.get("id")) is not None]
    hunts = [x for x in _l(h.get("hunts")) if isinstance(x, dict) and _id(x.get("squad_id")) is not None]
    hist = [x for x in _l(h.get("history")) if isinstance(x, dict)]
    return targets, squads, hunts, hist


def squad_power(q: dict) -> float:
    p = q.get("power")
    n = _num(p)
    if n is None:
        n = _num(_d(p).get("power"))
    return max(0.0, n or 0.0)


def _party_power(t: dict, squads) -> float:
    """The party's strength against target `t`: the squads' `power` summed.
    (0.105.45) One helper on purpose: H7's brain/planner_matchup.py
    squad_weights(t) (a fire breather: only crossbows count; a flier: melee
    0.6, ranged 1.25 by the squads' melee_power / ranged_power) is switched in
    here at the merge."""
    return sum(squad_power(q) for q in squads)


def is_ranged(q: dict) -> bool:
    """A squad of crossbows: `ranged` true, or at least half its soldiers."""
    r = q.get("ranged")
    if r is True:
        return True
    n = _num(r)
    return n is not None and n > 0 and n * 2 >= max(1, _int(q.get("soldiers")))


def hunt_ratio(s: dict, cfg: dict) -> float:
    """The bar a hunting party must clear: `hunt_ratio` (1.5 x fight_ratio),
    x2 at Caution +200 over Militarism -200... bounded by hunt_ratio_min/max."""
    tr = _traits(s)
    c, m = _num(tr.get("caution")) or 0.0, _num(tr.get("militarism")) or 0.0
    lean = max(-1.0, min(1.0, (c - m) / 200.0))
    r = float(cfg.get("hunt_ratio", 3.0)) * (2 ** (lean * float(cfg.get("hunt_slider_weight", 0.5))))
    lo = max(float(cfg.get("hunt_ratio_min", 2.4)), float(cfg.get("fight_ratio", 2.0)))
    return round(max(lo, min(float(cfg.get("hunt_ratio_max", 6.0)), r)), 2)


def need_of(t: dict, memory) -> float:
    f = _num(_d(getattr(memory, "fight_factor", None)).get(fight_key(t))) if memory is not None else None
    return threat_power(t) * (f if f and f > 0 else 1.0)


def _kind_class(t: dict, near: int) -> int:
    """0 cheap (wounded visitor, thief), 1 an ambush near workers, 2 a great
    danger, 3 any other hostile."""
    if t.get("wounded_visitor") or t.get("thief"):
        return 0
    if t.get("ambush") and near > 0:
        return 1
    if t.get("great_danger"):
        return 2
    return 3


def _what(t: dict) -> str:
    if t.get("wounded_visitor"):
        return "a wounded visitor the dwarves drop their jobs for"
    if t.get("thief"):
        return "a thief"
    if t.get("ambush"):
        return "an ambusher"
    kinds = [str(k) for k in _l(t.get("kinds")) if k]
    if t.get("great_danger"):
        return {"ForgottenBeast": "a forgotten beast", "Titan": "a titan", "Megabeast": "a megabeast",
                "Demon": "a demon", "SemiMegabeast": "a semi-megabeast"}.get(fight_key(t), "a great danger")
    return f"a hostile ({', '.join(kinds[:2])})" if kinds else "a hostile"


def _head(t: dict) -> str:
    where = {"surface": "on the surface", "cavern": "in the caverns", "inside": "inside the fort"}.get(
        t.get("region"), "on the map")
    r = _d(t.get("route"))
    far = f", {int(r['length'])} tiles away" if _num(r.get("length")) is not None and r.get("ok") else ""
    near = _int(t.get("near_workers"))
    workers = f", {near} worker(s) near" if near else ""
    return f"{t.get('name') or 'a creature'} ({_what(t)}) {where}{far}{workers}"


def party_for(t: dict, free: list, all_soldiers: int, home_squads: int, home_soldiers: int, need: float,
              ratio: float, cfg: dict) -> tuple[list | None, str]:
    """The smallest party of `free` squads that clears `ratio` x `need` and
    leaves the reserve home. (squads, why) - squads None with the why not."""
    if t.get("fire_breather") is True or t.get("flier") is True:
        pool = [q for q in free if is_ranged(q)]
        what = "breathes fire" if t.get("fire_breather") is True else "flies"
        if not pool:
            return None, f"it {what} and no free squad of crossbows can go (never melee at it)"
    else:
        pool = list(free)
    if not pool:
        return None, "no squad free at home (armed, not sheltering, on no other order)"
    pool = sorted(pool, key=lambda q: -squad_power(q))[:PARTY_SQUADS_MAX]
    reserve = max(int(cfg.get("hunt_reserve_min", 3)),
                  math.ceil(float(cfg.get("hunt_reserve_share", 0.34)) * all_soldiers))
    best, best_key, short_reserve, best_power = None, None, False, 0.0
    for n in range(1, len(pool) + 1):
        for combo in itertools.combinations(pool, n):
            power = _party_power(t, combo)
            best_power = max(best_power, power)
            if power < ratio * need:
                continue
            sent = sum(_int(q.get("soldiers")) for q in combo)
            left = home_soldiers - sent
            if left < reserve or (home_squads >= 2 and home_squads - n < 1) or home_squads - n < 0:
                short_reserve = True
                continue
            key = (sent, n, -power)
            if best_key is None or key < best_key:
                best, best_key = list(combo), key
    if best is not None:
        return best, ""
    if short_reserve:
        return None, (f"the squads strong enough would leave fewer than {reserve} soldiers (or no squad) at home "
                      "to guard the fort")
    return None, f"the squads free are too weak ({best_power:.0f} against {need:.0f}, {ratio:g}x needed)"


def _blocked(s: dict, memory, cfg: dict, rules_: dict, mode: str) -> str | None:
    """Why no new hunt may start now (None: it may)."""
    if mode == "off":
        return "hunting is off on the Rules tab"
    if rules_.get("attack_policy") == "never":
        return "the Rules tab sends squads against nothing"
    if s.get("halted") is True:
        return "the AI is halted in the game"
    if memory is not None and _d(getattr(memory, "crisis", None)).get("why"):
        return "the fort is in crisis"
    errors = _d(s.get("_errors"))
    if "civ_alert" in errors:
        return "the alarm couldn't be read"
    if s.get("civ_alert") is True or (memory is not None and getattr(memory, "ai_alert_raised", False)):
        return "the alarm is up"
    siege = _siege_why(s, cfg)
    if siege:
        return siege
    f = getattr(memory, "fight", None) if memory is not None else None
    if isinstance(f, dict) and f:
        return "a fight with a great danger is under way"
    return None


def _siege_why(s: dict, cfg: dict) -> str | None:
    """A siege or invaders on the map, or a threat that can reach the dwarves
    (the military rules' fight: the squads stay for it)."""
    if "others_on_map" in _d(s.get("_errors")):
        return "the threats on the map couldn't be read"
    threats = [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)]
    if any(t.get("invader") for t in threats) or any(
            isinstance(t, dict) and t.get("invader") for t in _l(_d(s.get("hunt")).get("targets"))):
        return "invaders are on the map (a siege)"
    try:
        reach = reachable_threats(s, _traits(s), cfg)
    except Exception:  # noqa: BLE001  (an odd others_on_map: no hunt rather than none of the rule)
        return "the threats on the map couldn't be read"
    if reach:
        return f"{len(reach)} enemy/enemies can reach the dwarves: the squads stay for them"
    return None


def _group_hunts(hunts: list) -> dict:
    out: dict = {}
    for h in hunts:
        tid = _id(h.get("target_id"))
        if tid is not None:
            out.setdefault(tid, []).append(h)
    return out


def _retreat(s: dict, memory, cfg: dict, targets: dict, squads: dict, hunts: list, proposals: list,
             notes: list, recall_all: str | None) -> set:
    """Each hunt under way: on, or called back. Returns the target ids hunted."""
    now = abs_tick(s)
    max_ticks = float(cfg.get("hunt_max_days", 3)) * TICKS_PER_DAY
    seen = hunt_seen(memory)
    hunted = set()
    for tid, hs in sorted(_group_hunts(hunts).items()):
        hunted.add(tid)
        if any(h.get("target_alive") is False for h in hs):
            notes.append(f"hunt: target {tid} is dead or gone; the bridge closes the hunt")
            continue
        t = targets.get(tid, {"id": tid, "name": f"target {tid}"})
        ids = [h["squad_id"] for h in hs]
        party = [squads[i] for i in ids if i in squads]
        start = sum(_int(h.get("soldiers_at_start")) for h in hs)
        left = sum(_int(h.get("soldiers_now")) for h in hs)
        hurt = sum(_int(h.get("wounded")) for h in hs)
        since = min([_int(h.get("since_tick")) for h in hs if _num(h.get("since_tick")) is not None] or [now])
        ranged = bool(party) and all(is_ranged(q) for q in party)
        why, kind = None, None
        if recall_all:
            why, kind = recall_all, None
        elif start and left * 3 <= start * 2:
            why, kind = f"{start - left} of the {start} soldiers who went are lost", "lost"
        elif left and hurt * 2 >= left:
            why, kind = f"{hurt} of the {left} soldiers left are wounded", "lost"
        elif left == 0 and start:
            why, kind = "no soldier of the party is left standing", "lost"
        elif t.get("fire_breather") is True and not ranged:
            why, kind = "it breathes fire and the party fights in melee", "ability"
        elif t.get("flier") is True and not ranged:
            why, kind = "it flies and the party has no crossbows", "ability"
        elif now - since > max_ticks:
            why, kind = f"the hunt has gone on over {cfg.get('hunt_max_days', 3)} days", "time"
        if why is None:
            notes.append(f"hunt: {', '.join(str(squads.get(i, {}).get('name') or i) for i in ids)} after "
                         f"{_head(t)}: {left} of {start} soldiers, {hurt} wounded, "
                         f"{max(0, now - since) // 50} hour(s) out")
            continue
        if kind and memory is not None:
            off = seen.get("off")
            if not isinstance(off, dict):
                off = seen["off"] = {}
            off.setdefault(str(tid), {"tick": now, "why": kind})
        then = {"lost": ": it is not hunted again while it is on the map",
                "ability": ": it is not hunted again while it is on the map",
                "time": f": it is left {cfg.get('hunt_rest_days', 5)} days before another try"}.get(kind, "")
        reason = f"call the hunt after {_head(t)} back: {why}{then}"
        proposals.append(Proposal("squad_recall", {"type": "hunt_recall", "squad_ids": ids, "reason": why[:120]},
                                  reason, 0, guard=True))
    return hunted


def _hunt_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    """The hunts under way kept or called back; at most one new hunt sent."""
    rows = hunt_rows(s)
    if rows is None:
        return
    targets_l, squads_l, hunts, _hist = rows
    if not (targets_l or hunts):
        return
    rules_ = player_rules(s)
    mode = hunt_mode(s)
    targets = {t["id"]: t for t in targets_l}
    squads = {q["id"]: q for q in squads_l}
    # the hunters come home with the switch off or a siege on the map
    recall_all = None
    if mode == "off":
        recall_all = "hunting is off on the Rules tab"
    else:
        sw = _siege_why(s, cfg)
        if sw and "couldn't be read" not in sw:
            recall_all = f"{sw}: the hunters come home"
    hunted = _retreat(s, memory, cfg, targets, squads, hunts, proposals, notes, recall_all)
    for q in squads_l:
        if _id(q.get("hunting")) is not None:
            hunted.add(q["hunting"])
    why_not = _blocked(s, memory, cfg, rules_, mode)
    if why_not:
        if targets_l:
            notes.append(f"hunt: {len(targets_l)} target(s) on the map, none hunted now: {why_not}")
        return
    # squads already sent this cycle (the military rules, the killers...) aren't free
    busy = {_id(p.action.get("squad_id")) for p in proposals if isinstance(p.action, dict)}
    for p in proposals:
        if isinstance(p.action, dict):
            busy.update(i for i in _l(p.action.get("squad_ids")) if _id(i) is not None)
    min_armed = int(cfg.get("min_squad_to_fight", 3))
    home = [q for q in squads_l if q.get("at_home") is True and _id(q.get("hunting")) is None
            and not q.get("sheltering")]
    free = [q for q in home if q["id"] not in busy and _int(q.get("soldiers")) >= min_armed
            and (_num(q.get("armed")) is None or _int(q.get("armed")) >= min_armed) and squad_power(q) > 0]
    all_soldiers = sum(_int(q.get("soldiers")) for q in squads_l)
    home_soldiers = sum(_int(q.get("soldiers")) for q in home)
    ratio = hunt_ratio(s, cfg)
    off_military = called_off_ids(s, memory)
    off_hunt = hunt_off_ids(s, memory, cfg)
    tr = _traits(s)
    great_ok = (mode == "ai" and (_num(tr.get("militarism")) or 0) > cfg.get("hunt_great_militarism_min", -100)
                and (_num(tr.get("caution")) or 0) < cfg.get("hunt_great_caution_max", 150))
    great_hunted = any(_d(targets.get(i)).get("great_danger") for i in hunted)

    said: list = []
    ranked = []
    for t in targets_l:
        tid, head = t["id"], _head(t)
        r = _d(t.get("route"))
        near = _int(t.get("near_workers"))
        cls = _kind_class(t, near)
        if tid in hunted:
            continue
        if t.get("can_reach_dwarves") is True:
            said.append(f"{head}: it can reach the dwarves: the military rules' fight, not a hunt")
            continue
        if t.get("kill_ok") is False:
            said.append(f"{head}: not one the squads may be sent to kill (the bridge's kill_ok)"
                        + (f": {t.get('why')}" if isinstance(t.get("why"), str) and t.get("why") else ""))
            continue
        if tid in off_military or off_hunt.get(tid) in ("lost", "ability"):
            said.append(f"{head}: a fight or hunt with it was called off; not hunted again while it is here")
            continue
        if tid in off_hunt:
            said.append(f"{head}: the last hunt ran out of time; it rests a few days before another")
            continue
        if not r.get("ok"):
            b = r.get("blocked_by")
            if b == "seal" and t.get("region") == "cavern":
                said.append(f"{head}: behind the AI's cavern seal; left to the lure and cut-off rules, not hunted")
            elif b == "gate":
                said.append(f"{head}: the way to it is behind a shut gate; not hunted")
            else:
                said.append(f"{head}: no way to walk to it; not hunted")
            continue
        if mode == "small" and cls not in (0, 1):
            said.append(f"{head}: the Rules' hunting is 'small' (thieves, ambushes, wounded visitors only)")
            continue
        if cls == 2 and not great_ok:
            said.append(f"{head}: great dangers are hunted only with Militarism above "
                        f"{cfg.get('hunt_great_militarism_min', -100)} and Caution below "
                        f"{cfg.get('hunt_great_caution_max', 150)}")
            continue
        if cls == 2 and great_hunted:
            said.append(f"{head}: one great danger is hunted at a time")
            continue
        length = _num(r.get("length"))
        ranked.append(((cls, -near, length if length is not None else 1e9, tid), t))
    ranked.sort(key=lambda x: x[0])
    sent = False
    for _, t in ranked:
        head = _head(t)
        need = need_of(t, memory)
        if sent:
            said.append(f"{head}: waits; one new hunt a cycle")
            continue
        party, why = party_for(t, free, all_soldiers, len(home), home_soldiers, need, ratio, cfg)
        if party is None:
            said.append(f"{head}: not hunted: {why}")
            continue
        power = _party_power(t, party)
        n = sum(_int(q.get("soldiers")) for q in party)
        names = ", ".join(str(q.get("name") or q["id"]) for q in party)
        stay = home_soldiers - n
        reason = (f"hunt {head}: send {names} ({n} soldiers, strength {power:.0f} against {need:.0f}: "
                  f"{power / max(1.0, need):.1f}x, {ratio:g}x needed); {stay} soldier(s) stay home")
        proposals.append(Proposal("hunt", {"type": "hunt_send", "squad_ids": [q["id"] for q in party],
                                           "target_id": t["id"]}, reason, 2))
        sent = True
    if said:
        notes.extend("hunt: " + x for x in said[:NOTE_MAX])
        if len(said) > NOTE_MAX:
            notes.append(f"hunt: {len(said) - NOTE_MAX} more target(s) not hunted")


def note_hunt_cycle(s: dict, memory, cfg: dict) -> list:
    """Bookkeeping before the plan: the history's outcomes learned once each
    (memory.fight_factor), the off marks of targets no longer on the map
    forgotten. Returns notes."""
    rows = hunt_rows(s)
    if rows is None or memory is None:
        return []
    targets, _squads, _hunts, hist = rows
    seen = hunt_seen(memory)
    notes = []
    off = seen.get("off")
    if isinstance(off, dict):
        here = {str(t["id"]) for t in targets}
        for k in [k for k in off if k not in here]:
            del off[k]
    learned = [x for x in _l(seen.get("learned")) if isinstance(x, str)]
    ff = memory.fight_factor if isinstance(getattr(memory, "fight_factor", None), dict) else {}
    changed = False
    for e in hist:
        # (H1's bridge) outcome won | caged | gone | dropped | recalled; lost
        # also as soldiers_lost, the tick also as end_tick
        out = e.get("outcome") if e.get("outcome") is not None else e.get("result")
        kinds = [str(k) for k in _l(e.get("kinds") if e.get("kinds") is not None else e.get("target_kinds"))]
        tick = e.get("tick") if isinstance(e.get("tick"), int) else e.get("end_tick")
        if out not in ("won", "caged", "gone", "dropped", "recalled") or not isinstance(tick, int) \
                or isinstance(tick, bool):
            continue
        k = fight_key({"kinds": kinds})
        key = f"{tick}:{k}:{out}"
        if key in learned:
            continue
        learned.append(key)
        lost = _int(e.get("lost")) if _num(e.get("lost")) is not None else _int(e.get("soldiers_lost"))
        of = _int(e.get("of"))
        bad = (out == "recalled" and lost > 0) or (of > 0 and lost * 3 >= of)
        if out in ("gone", "dropped") and not bad:
            continue                       # it left, or the order was cleared elsewhere: no lesson
        if out == "recalled" and not bad:
            continue                       # called back in time (no loss): no lesson
        old = float(_num(ff.get(k)) or 1.0)
        new = round(min(max(4.0, old), max(0.5, old * 1.5)), 2) if bad else round(max(0.5, old * 0.9), 2)
        ff[k] = new
        changed = True
        notes.append(f"hunt learned: a {out} hunt after a {k} ({lost} of {of} lost): that kind is now taken as "
                     f"{new}x its estimate")
    seen["learned"] = learned[-int(cfg.get("hunt_learned_keep", 60)):]
    if changed:
        memory.fight_factor = ff
    return notes
