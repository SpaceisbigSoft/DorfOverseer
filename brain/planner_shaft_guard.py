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

__all__ = ["SHAFT_LAYER_FLIER_TILES", "shaft_layer", "shaft_layer_guard", "shaft_thirst_lethal", "guard_distance"]


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


def shaft_layer_guard(s: dict, gates: list) -> dict:
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
                             "pos": pos if has_pos else None})
        if has_pos and (not layer or layer.startswith("Cavern")):
            for x in live:
                hz = _d(x.get("shaft_hatch")).get("z")
                if (not layer_of[x["project_id"]] and near(x, pos)
                        and (not isinstance(hz, int) or pos["z"] < hz)):
                    mark(x, {"name": name, "why": f"{name} (flies, in the cavern below)", "pos": pos})
    for x in live:
        wn = _d(x.get("watch_near"))
        if wn and wn.get("flier") and wn.get("great") and not wn.get("in_shaft"):
            name = str(wn.get("name") or "a great beast")
            lay = layer_of[x["project_id"]]
            pos = _d(wn.get("pos")) if all(isinstance(_d(wn.get("pos")).get(k), int) for k in ("x", "y")) else None
            for y in (by_layer.get(lay) or [x]):
                mark(y, {"name": name, "why": f"{name} (flies, in {lay or 'the cavern below'})", "pos": pos})
    from planner_unseen import unseen_great
    for u in unseen_great(s):
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
                mark(x, {"name": name, "why": f"{name} ({what}, in {layer or 'the caverns'})", "pos": None})
    return out


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
