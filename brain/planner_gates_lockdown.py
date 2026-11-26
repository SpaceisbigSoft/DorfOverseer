"""planner_gates_lockdown: when the gates shut and open (split out of
planner_gates in r7, 0.105.62): a lone intruder or a few ordinary enemies,
the squads out on a sortie, the lockdown and its release, the quick
all-clear; pastures held while the gates are shut; the gate guard and its
dogs. planner_gates re-exports every name here."""

from __future__ import annotations

from dataclasses import field
from culture import profile_from
from quirks import has_rule
from digest import _d, _l
from planner_core import *  # noqa: F401,F403
from planner_construct import _wings_rule, cavern_wall_style  # (0.105.30) wing walls, the Hermit's cavern walls

__all__ = ["lone_intruders", "few_ordinary", "few_alert_over", "few_near", "hunted_outside", "sortie_out", "ai_gates_shut", "lockdown_released", "lone_alert_over", "note_lockdown", "quick_clear", "PASTURE_ACTIONS", "gate_invaders", "main_gate"]


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
                or t.get("destroyer") or t.get("fire_breather")):       # (0.105.40b) never a lone intruder
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
        if (not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer")
                or t.get("fire_breather")):         # (0.105.40b) a fire breather is never "ordinary"
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
        if (not isinstance(t, dict) or t.get("great_danger") or t.get("flier") or t.get("destroyer")
                or t.get("fire_breather")):         # (0.105.40b) a fire breather is never "ordinary"
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


def sortie_out(s: dict, cfg: dict, memory=None, held_only: bool = True) -> list:
    """(0.105.54, "fight back") The squads' sortie: the ids of the enemies
    outside the fort (held off by the shut gates, or out on the surface) that
    an AI squad able to fight has a kill order on, while the civilians are in
    the shelter (the alarm up). The gates are opened for it (a gatehouse's
    raised drawbridge lowered: the watcher lowers it with the hatch) and not
    armed again until the squads are back. Who goes out, and at what, is the
    engagement rules' (planner_military); this only lets them out. [] without
    the gate scan, with the alarm down (the few-ordinary case is
    hunted_outside's), or with a great danger outside that no squad goes at
    (an open gate would let it in). held_only: only enemies the gates hold
    off count (the opening; a squad sent at enemies that can reach the
    dwarves is the ordinary defence, whose gates the watcher keeps); False:
    any outside (the sortie the AI opened for, still out: _sortie_on)."""
    if s.get("civ_alert") is not True or not _d(s.get("entrances")).get("scanned"):
        return []
    o = _d(s.get("others_on_map"))
    rows = {t.get("id"): t for t in _l(o.get("threats")) if isinstance(t, dict) and t.get("id") is not None}
    from planner_holdfast import _inside_ids
    inside = _inside_ids(s)
    held = {t.get("id") for t in held_off_threats(s)}
    outside = {i for i, t in rows.items() if i not in inside and (
        i in held or (not held_only and t.get("layer") in (None, "surface", "upper_levels")))}
    if not outside:
        return []
    hunted = set()
    for q in _l(_d(s.get("military")).get("squads")):
        if (isinstance(q, dict) and q.get("ai_orders") and can_fight(q, cfg) and not q.get("sheltering")
                and not q.get("guarding") and isinstance(q.get("kill_ids"), list)):
            hunted |= outside & {x for x in q["kill_ids"] if isinstance(x, int)}
    if not hunted:
        return []
    if any(rows[i].get("great_danger") and i not in hunted for i in outside & held):
        return []
    return sorted(hunted)


def _sortie_on(s: dict, cfg: dict, memory, opening: list) -> list:
    """(0.105.54) The sortie the AI opened the gates for (its record in the
    atlas, set when the open is proposed) while its squads are still out at
    enemies outside: the gates aren't armed again meanwhile. The record goes
    once no squad is out at them."""
    if memory is None or not isinstance(getattr(memory, "atlas", None), dict):
        return []
    if opening:
        old = _d(memory.atlas.get("sortie"))
        rec = {"since": old.get("since") if isinstance(old.get("since"), int) else abs_tick(s)}
        try:
            # (R29 W6) who went out at whom: the sortie's result is journalled from it
            from planner_combat_log import sortie_party
            party = sortie_party(s, opening)
            rec["targets"] = {**_d(old.get("targets")), **party["targets"]}
            rec["squads"] = {**_d(old.get("squads")), **party["squads"]}
        except Exception:  # noqa: BLE001  (the gates open as before)
            pass
        memory.atlas["sortie"] = rec
        return opening
    if not _d(memory.atlas.get("sortie")):
        return []
    out = sortie_out(s, cfg, memory, held_only=False)
    if not out:
        memory.atlas.pop("sortie", None)
    return out


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
            or any(i not in rows or rows[i].get("great_danger") or rows[i].get("fire_breather") for i in ids)):
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
    on the surface): the squads wait for them inside the main gate.
    (0.105.54) The bridge names the surface's layer "upper_levels"
    (ai-bridge-report layer_at), never "surface": a besieger with its layer
    read was never one, so no archer was posted and no gate guard held."""
    return [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)
            and t.get("invader") and not t.get("can_reach_dwarves")
            and t.get("layer") in (None, "surface", "upper_levels")]


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
