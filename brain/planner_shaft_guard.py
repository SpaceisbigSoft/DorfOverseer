"""(item2) The cavern wells' shafts kept shut for a great beast in the
cavern layer they open into, and the one thirst that may open one anyway.

Why (B, 24 Nov, live journal): Paddlecrevice, a forgotten beast that flies
and breaks buildings, was in Cavern2 about 40 tiles from shaft 128. The
well_shaft rule opened shaft 128 "the fort is short of water (1 injured
need water): open the cavern well's shaft again at once" (the `dry` path
lets the hold go), then shaft 63 "no danger near the cavern well now"
while Paddlecrevice was named as shaft 128's danger: the bridge's watcher
(shaft_judge) judges each shaft by its own distance, but a flier in the
same layer reaches any shaft into it between two looks. B also has three
forgotten beasts the fort hasn't seen (deep.unseen, planner_unseen): one
can't be seen to be near, so "no danger near" says nothing of them.

planner_wells_caverns._shaft_turn uses these: a guarded shaft stays shut
(the bridge told by the action's `keep_shut` ids, so its watcher doesn't
open it either), short of water or not, unless a dwarf is dying of thirst
with only well water to save them and no other water comes: then the one
guarded shaft farthest from the beast is opened, and said.
(A module of its own: planner_wells' parts keep the names they had at the
r7 d4 split, tests/test_r7_d4.py.)
"""

from __future__ import annotations

from digest import _d, _l
from planner_core_base import TICKS_PER_YEAR, TICKS_PER_DAY

__all__ = ["SHAFT_LAYER_FLIER_TILES", "SHAFT_BEAST_MEMORY_DAYS", "SHAFT_GUARD_HOLD_TICKS", "shaft_layer",
           "shaft_layer_guard", "shaft_thirst_lethal", "guard_distance", "remember_shaft_beasts", "shaft_gates"]

# (item16) B (24 Nov 23:25-23:35): the flier Urnut in Cavern1 left
# others_on_map.threats for minutes at a time (it flew over cavern tiles the
# fort hasn't revealed: the report skips a hidden unit, and deep.unseen, which
# lists hidden ones, is in the full report only, stale on the pulses between),
# so the guard opened the five shafts "no danger near the cavern well now" 4
# times in 10 minutes and shut them again each time it came back in sight.
# A great beast that kept a shaft shut is remembered (memory.shaft_beasts, by
# its unit id, with the last tick it was seen) and keeps every shaft into its
# layer shut until it is seen dead (a death event), caged, out of the caverns,
# or unseen this many days; and a shaft the guard shut stays shut a day at
# least (no flapping), but for a dwarf dying of thirst (the farthest shaft).
SHAFT_BEAST_MEMORY_DAYS = 2
SHAFT_GUARD_HOLD_TICKS = TICKS_PER_DAY


SHAFT_LAYER_FLIER_TILES = 60     # (item2) a seen flier great beast this near (across) any shaft into its
                                 # cavern layer: every shaft into that layer kept shut
GREAT_THREAT_KINDS = ("ForgottenBeast", "Titan", "Megabeast", "SemiMegabeast", "Demon")
WELL_ONLY_THIRST = ("injured", "chained", "jailed", "no_drink")   # planner_thirst reasons: only well water helps
SHAFT_LETHAL_THIRST = 50000      # planner_thirst DEHYDRATED (the society section's `parched`)


def _gate_xy(x: dict) -> tuple:
    h = _d(x.get("shaft_hatch"))
    if isinstance(h.get("x"), int) and isinstance(h.get("y"), int):
        return h["x"], h["y"]
    return x.get("x"), x.get("y")


def shaft_layer(s: dict, gate: dict) -> str:
    """(item2) The cavern layer a well's shaft opens into ("Cavern2"), by its
    hatch's level (the shaft's bottom) and the map's layers; "" unknown."""
    hz = _d(gate.get("shaft_hatch")).get("z")
    if not isinstance(hz, int):
        return ""
    layers = [l for l in _l(_d(s.get("map")).get("layers")) if isinstance(l, dict)
              and str(l.get("name") or "").startswith("Cavern")
              and isinstance(l.get("z_top"), int) and isinstance(l.get("z_bottom"), int)]
    for z in (hz - 1, hz):
        for l in layers:
            if l["z_bottom"] <= z <= l["z_top"]:
                return str(l["name"])
    return ""


def _great_threat(th: dict) -> bool:
    return bool(th.get("great_danger")) or any(k in GREAT_THREAT_KINDS for k in _l(th.get("kinds")))


def shaft_layer_guard(s: dict, gates: list, mem: dict | None = None) -> dict:
    """(item2) The cavern wells' shafts kept shut for a great beast in the
    cavern layer they open into, whatever the watcher's per-shaft distance
    says: {project_id: {name, why, layer, pos?}}.

    Why (B, 24 Nov): Paddlecrevice, a forgotten beast that flies and breaks
    buildings, was named the danger of shaft 128 while shaft 63, into the
    same Cavern2, was opened "no danger near the cavern well now" (and 128
    opened "short of water ... at once"): the watcher judges each shaft by
    its own distance, but a flier crosses a cavern layer between two looks.
    Kept shut (seen ones by the report's threats, unseen ones by
    deep.unseen):
      * a seen flier great beast within SHAFT_LAYER_FLIER_TILES (across) of
        any shaft into its layer, or anywhere in it if it also destroys
        buildings (a hatch doesn't hold it);
      * a seen flier great beast the watcher names for a shaft (watch_near):
        every shaft into that shaft's layer;
      * an unseen great beast in the layer that flies or can walk to the
        dwarves (it can't be seen to be near).
    A shaft whose layer is unknown is kept shut for a seen flier by its own
    distance, and for an unseen great beast anywhere in the caverns."""
    live = [x for x in gates if isinstance(x, dict) and not x.get("cancelled")
            and isinstance(x.get("project_id"), int)]
    if not live:
        return {}
    layer_of = {x["project_id"]: shaft_layer(s, x) for x in live}
    by_layer: dict = {}
    for x in live:
        if layer_of[x["project_id"]]:
            by_layer.setdefault(layer_of[x["project_id"]], []).append(x)
    out: dict = {}

    def mark(x: dict, info: dict) -> None:
        pid = x["project_id"]
        if pid not in out:
            out[pid] = dict(info, layer=layer_of[pid] or info.get("layer") or "")

    def near(x: dict, pos: dict) -> bool:
        gx, gy = _gate_xy(x)
        return (isinstance(gx, int) and isinstance(gy, int)
                and max(abs(pos["x"] - gx), abs(pos["y"] - gy)) <= SHAFT_LAYER_FLIER_TILES)

    for th in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(th, dict) or th.get("caged") or not th.get("flier") or not _great_threat(th):
            continue
        name = str(th.get("name") or "a great beast")
        layer = str(th.get("layer") or "")
        pos = _d(th.get("pos"))
        has_pos = all(isinstance(pos.get(k), int) for k in ("x", "y", "z"))
        if layer.startswith("Cavern") and layer in by_layer:
            rows = by_layer[layer]
            if th.get("destroyer") or (has_pos and any(near(x, pos) for x in rows)):
                what = "flies and breaks buildings" if th.get("destroyer") else "flies"
                for x in rows:
                    mark(x, {"name": name, "why": f"{name} ({what}, in {layer})",
                             "pos": pos if has_pos else None, "id": th.get("id"), "flier": True,
                             "destroyer": bool(th.get("destroyer"))})
        if has_pos and (not layer or layer.startswith("Cavern")):
            for x in live:
                hz = _d(x.get("shaft_hatch")).get("z")
                if (not layer_of[x["project_id"]] and near(x, pos)
                        and (not isinstance(hz, int) or pos["z"] < hz)):
                    mark(x, {"name": name, "why": f"{name} (flies, in the cavern below)", "pos": pos,
                             "id": th.get("id"), "flier": True})
    for x in live:
        wn = _d(x.get("watch_near"))
        if wn and wn.get("flier") and wn.get("great") and not wn.get("in_shaft"):
            name = str(wn.get("name") or "a great beast")
            lay = layer_of[x["project_id"]]
            pos = _d(wn.get("pos")) if all(isinstance(_d(wn.get("pos")).get(k), int) for k in ("x", "y")) else None
            for y in (by_layer.get(lay) or [x]):
                mark(y, {"name": name, "why": f"{name} (flies, in {lay or 'the cavern below'})", "pos": pos,
                         "id": wn.get("id"), "flier": True})
    from planner_unseen import unseen_great
    unseen = list(unseen_great(s))
    # (item16) and the pulse's own hidden great beasts (others_on_map.hidden_great):
    # deep.unseen on a pulse is the last full report's (merged under it), a day old at most
    seen_ids = {u.get("id") for u in unseen}
    held = set(_l(_d(s.get("lures")).get("held_beasts")))
    for u in _l(_d(s.get("others_on_map")).get("hidden_great")):
        if (isinstance(u, dict) and u.get("id") not in seen_ids and u.get("id") not in held
                and str(u.get("layer") or "").startswith("Cavern")):
            unseen.append(dict(u, kind=u.get("kind") or "great beast"))
    for u in unseen:
        # (merge) only one that flies or can walk to the dwarves: a walker that
        # can't reach them doesn't come up a shaft, and B's Cavern1 wells would
        # stay shut for Bonephantom for good (B's thirst deaths)
        if not (u.get("flier") or u.get("can_reach_dwarves") is True):
            continue
        name = str(u.get("name") or "a great beast")
        layer = str(u.get("layer") or "")
        what = f"{u.get('kind') or 'great beast'}, unseen" + (", flies" if u.get("flier") else "")
        for x in live:
            lay = layer_of[x["project_id"]]
            if (lay and lay == layer) or (not lay and (layer.startswith("Cavern") or not layer)):
                mark(x, {"name": name, "why": f"{name} ({what}, in {layer or 'the caverns'})", "pos": None,
                         "id": u.get("id"), "flier": bool(u.get("flier")), "unseen": True})
    if mem is None:
        mem = s.get("_shaft_memory")
    if isinstance(mem, dict) and mem:
        _remembered(s, live, layer_of, by_layer, mem, mark)
    return out


def _now(s: dict):
    d = _d(s.get("date"))
    if isinstance(d.get("year"), int) and isinstance(d.get("tick"), int):
        return d["year"] * TICKS_PER_YEAR + d["tick"]
    return None


def _visible_ids(s: dict) -> set:
    """The units the report sees now (a threat row): judged by the live rules."""
    return {th.get("id") for th in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(th, dict) and th.get("id") is not None}


def _remembered(s: dict, live: list, layer_of: dict, by_layer: dict, mem: dict, mark) -> None:
    """(item16) The remembered great beasts out of sight now keep every shaft
    into their layer shut (a flier crosses a layer between two looks), and a
    shaft the guard shut less than a day ago stays shut."""
    now = _now(s)
    if now is None:
        return
    visible = _visible_ids(s)
    for key, b in sorted(_d(mem.get("beasts")).items()):
        if not isinstance(b, dict) or not isinstance(b.get("seen"), int):
            continue
        if b.get("id") in visible or now - b["seen"] > SHAFT_BEAST_MEMORY_DAYS * TICKS_PER_DAY:
            continue
        layer = str(b.get("layer") or "")
        if not layer.startswith("Cavern"):
            continue
        name = str(b.get("name") or "a great beast")
        days = (now - b["seen"]) / TICKS_PER_DAY
        ago = "just now" if days < 0.1 else f"{days:.1f} days ago"
        why = (f"{name} (in {layer}, out of sight, last seen {ago}: remembered "
               f"{SHAFT_BEAST_MEMORY_DAYS} days unless seen dead or gone)")
        for x in (by_layer.get(layer) or [x for x in live if not layer_of[x["project_id"]]]):
            mark(x, {"name": name, "why": why, "pos": None, "id": b.get("id"), "remembered": True})
    for x in live:
        t = _d(mem.get("held")).get(str(x["project_id"]))
        if isinstance(t, int) and 0 <= now - t < SHAFT_GUARD_HOLD_TICKS:
            left = SHAFT_GUARD_HOLD_TICKS - (now - t)
            mark(x, {"name": "the great beast it was shut for",
                     "why": (f"the great beast it was shut for {now - t} ticks ago (kept shut a day at least, "
                             f"{left} ticks yet: no flapping)"), "pos": None, "held": True})


def shaft_gates(s: dict) -> list:
    """The cavern wells' shaft gates (projects.well_lids with a gate)."""
    return [x for x in _l(_d(s.get("projects")).get("well_lids")) if isinstance(x, dict) and x.get("gate")]


def remember_shaft_beasts(s: dict, memory, events: list | None = None) -> dict:
    """(item16) The cycle's step before the plan: memory.shaft_beasts brought
    up to date. A great beast the guard keeps a shaft shut for now is
    remembered (unit id, name, layer, the tick last seen); one seen again is
    seen; one told dead (a death event), seen caged, seen out of the caverns,
    or unseen SHAFT_BEAST_MEMORY_DAYS is forgotten. `held` keeps the tick the
    guard began to keep each shaft shut (a day at least). Returns the record."""
    now = _now(s)
    if now is None:
        return _d(getattr(memory, "shaft_beasts", None))
    mem = _d(getattr(memory, "shaft_beasts", None))
    beasts = {k: dict(v) for k, v in _d(mem.get("beasts")).items() if isinstance(v, dict)}
    held = {k: v for k, v in _d(mem.get("held")).items() if isinstance(v, int)}
    dead = {e.get("unit_id") for e in (events or []) if isinstance(e, dict) and e.get("kind") == "death"}
    gates = shaft_gates(s)
    # the live guard first (no memory): the beasts that keep a shaft shut now
    live = shaft_layer_guard(s, gates, mem={})
    for info in live.values():
        bid = info.get("id")
        if isinstance(bid, int) and not isinstance(bid, bool):
            b = beasts.setdefault(str(bid), {"id": bid})
            b.update(name=info.get("name"), layer=info.get("layer") or b.get("layer") or "", seen=now,
                     guarded=now)
    # seen anywhere: the threats (caged or out of the caverns: forgotten), the hidden ones
    om = _d(s.get("others_on_map"))
    for th in _l(om.get("threats")) + _l(om.get("hidden_great")):
        if not isinstance(th, dict) or str(th.get("id")) not in beasts:
            continue
        b = beasts[str(th.get("id"))]
        lay = str(th.get("layer") or "")
        if th.get("caged") or (lay and not lay.startswith("Cavern")):
            beasts.pop(str(th.get("id")), None)
            continue
        b["seen"] = now
        if lay:
            b["layer"] = lay
    for k in list(beasts):
        b = beasts[k]
        seen = b.get("seen")
        if (b.get("id") in dead or not isinstance(seen, int)
                or now - seen > SHAFT_BEAST_MEMORY_DAYS * TICKS_PER_DAY or seen - now > TICKS_PER_DAY):
            beasts.pop(k)
    rec = {"beasts": beasts, "held": held}
    guard = shaft_layer_guard(s, gates, mem=dict(rec, held={}))
    for pid in guard:
        held.setdefault(str(pid), now)
    for k in list(held):
        if not k.isdigit() or int(k) not in guard:
            if not (0 <= now - held[k] < SHAFT_GUARD_HOLD_TICKS):
                held.pop(k)
    rec = {"beasts": dict(sorted(beasts.items())[-20:]), "held": held}
    memory.shaft_beasts = rec
    return rec


def shaft_thirst_lethal(s: dict) -> str:
    """(item2) Who is dying of thirst with only well water to save them
    (dehydrated, and a patient, in chains, jailed or with no drink in the
    fort): words, "" when nobody."""
    rows = []
    for r in _l(_d(s.get("thirst")).get("list")):
        if not isinstance(r, dict) or r.get("reason") not in WELL_ONLY_THIRST:
            continue
        t = r.get("timer")
        if r.get("level") == "dehydrated" or (isinstance(t, (int, float)) and t >= SHAFT_LETHAL_THIRST):
            rows.append(r)
    if not rows:
        return ""
    names = ", ".join(str(r.get("name") or f"unit {r.get('id')}") for r in rows[:3])
    more = f" and {len(rows) - 3} more" if len(rows) > 3 else ""
    return f"{names}{more} dehydrated, with only well water to save them"


def guard_distance(x: dict, info: dict) -> int:
    pos = info.get("pos")
    gx, gy = _gate_xy(x)
    if not isinstance(pos, dict) or not isinstance(gx, int) or not isinstance(gy, int):
        return -1
    if not (isinstance(pos.get("x"), int) and isinstance(pos.get("y"), int)):
        return -1
    return max(abs(pos["x"] - gx), abs(pos["y"] - gy))
