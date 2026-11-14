"""(0.105.45) Kill zones where the squads can't win: traps in the narrow way
in behind the fort's gates and cavern openings, a drawbridge over a drop.

The bridge's `killzones` section (lua/ai-killzone.lua report, daily, cached
a day) lists each entrance the AI holds: its state (`possible`: a 1-wide
stretch 3-6 tiles long every enemy must walk was found inside it; `none`:
no such stretch, with why; `building` / `standing`: the AI's zone there;
`gatehouse`: the War-hold's gatehouse is that gate's zone), the traps
planned, built and full, the drawbridge (possible, over a channel or flat,
its stage), the fortifications beside it (ai-siege's survey); the enemies on
the map with `trapavoid` (DF's traps never touch a creature whose caste has
TRAPAVOID: most great beasts do) and the entrance each is nearest; free
mechanisms, trap weapons, cages; dwarves with the Mechanics labour.

How often enemies came each way is the atlas' per-entrance record
(brain/atlas.py: threats seen at it, deaths and kills by it).

The rule (_killzone_rule; Rules switch `killzones`, on by default):
  * which entrances: ones enemies used (`killzone_used_min` threats in the
    atlas' record, or deaths there), cavern openings onto a cavern with a
    great danger in it, the surface gate a siege is coming toward; every
    entrance at Fortification or Caution `killzone_all_slider`+, and in a
    closed fort (Outsiders `killzone_closed_outsiders` or lower: the Hermit
    hold), whose zones come first. With Fortification and Caution both under
    `killzone_slider` a great beast's cavern is sealed (planner_threats), not
    trapped: only the ways enemies used and a siege's gate count;
  * ordered by danger (a siege coming, a great beast in that cavern, the
    deaths and threats on record, a closed fort's), one zone at a time: a
    zone being built goes one step a day (its drawbridge's channel, the
    ramp removed, the bridge), then the next;
  * the kind: cage traps first (they hold what they catch); mixed (cages
    outside, weapon traps behind) with Fortification high and trap weapons
    or metal for blades; only the drawbridge when every enemy coming that
    way avoids traps (TRAPAVOID), said so;
  * needs: `killzone_min_citizens`, a dwarf with the Mechanics labour (given
    to one when nobody has it), mechanisms (ordered when short: the traps,
    the lever and its link), giant axe blades for weapon traps (ordered at
    the forge in the best metal, else the zone is all cages);
  * never in a crisis, never while enemies can reach the dwarves (the
    squads and the gates have them; masons and mechanics would walk into
    it), never against the Rules' switch;
  * a drawbridge standing with no lever linked and a free AI lever: linked.
Without a `killzones` section (an older bridge) nothing here proposes or
notes anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (PLANNER_CONFIG, RECIPE_SHOPS, Proposal, _best_metal, _has_shop, _traits, player_rules,
                          queued, reachable_threats)

__all__ = ["killzones_of", "entrance_records", "zone_reasons", "zone_kind", "_killzone_rule"]

RECIPE_SHOPS.setdefault("metal_trap_blades", "MetalsmithsForge")


def _c(cfg: dict, k: str):
    return cfg.get(k, PLANNER_CONFIG[k])


def killzones_of(s: dict) -> dict:
    """The bridge's killzones section; {} when absent or failed."""
    k = _d(s.get("killzones"))
    return {} if k.get("error") or "killzones" in _d(s.get("_errors")) else k


def _rows(kz: dict) -> list:
    return [e for e in _l(kz.get("entrances")) if isinstance(e, dict) and isinstance(e.get("id"), int)
            and not e.get("error") and all(isinstance(e.get(k), int) for k in ("x", "y", "z"))]


def entrance_records(memory, e: dict) -> dict:
    """The atlas' record of this entrance (threats seen at it, deaths, kills),
    by its spot or one within 3 tiles on its level; {} when none."""
    ents = _d(_d(getattr(memory, "atlas", None)).get("entrances"))
    for k, rec in ents.items():
        try:
            x, y, z = (int(v) for v in str(k).split(","))
        except ValueError:
            continue
        if z == e["z"] and abs(x - e["x"]) <= 3 and abs(y - e["y"]) <= 3 and isinstance(rec, dict):
            return rec
    return {}


def _layer_of(s: dict, e: dict) -> str | None:
    """The cavern layer a cavern opening opens onto (by its level)."""
    for layer in _l(_d(s.get("map")).get("layers")):
        if not isinstance(layer, dict):
            continue
        top, bottom = layer.get("z_top"), layer.get("z_bottom")
        if isinstance(top, int) and isinstance(bottom, int) and bottom - 1 <= e["z"] <= top + 1:
            return layer.get("name")
    return None


def _siege_gate(s: dict, rows: list):
    """The surface entrance invaders outside are nearest to (a siege coming), or None."""
    from planner_gates import gate_invaders
    inv = [t for t in gate_invaders(s) if isinstance(_d(t.get("pos")).get("x"), int)]
    surf = [e for e in rows if e.get("kind") != "cavern"]
    if not inv or not surf:
        return None
    def dist(e):
        return min(abs(_d(t["pos"])["x"] - e["x"]) + abs(_d(t["pos"]).get("y", 0) - e["y"]) for t in inv)
    return min(surf, key=dist)


def _closed(traits: dict, cfg: dict) -> bool:
    return (traits.get("outsiders", 0) or 0) <= _c(cfg, "killzone_closed_outsiders")


def zone_reasons(s: dict, memory, cfg: dict, rows: list) -> list:
    """[(danger, entrance row, [reasons])] for the entrances that want a kill
    zone, the most dangerous first."""
    traits = _traits(s)
    lean = max(int(traits.get("fortification", 0) or 0), int(traits.get("caution", 0) or 0))
    closed = _closed(traits, cfg)
    every = lean >= _c(cfg, "killzone_all_slider") or closed
    threats = [t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)]
    great_layers = {t.get("layer") for t in threats if t.get("great_danger") and t.get("layer")}
    sg = _siege_gate(s, rows)
    out = []
    for e in rows:
        rec = entrance_records(memory, e)
        why, danger = [], 0
        if sg is not None and sg["id"] == e["id"]:
            why.append("a siege is coming toward it")
            danger += 100
        if e.get("kind") == "cavern" and lean >= _c(cfg, "killzone_slider"):
            # (below the slider a beast's cavern is sealed, not trapped: planner_threats)
            layer = _layer_of(s, e)
            if layer and layer in great_layers:
                why.append(f"a great beast is in {layer.lower()}")
                danger += 80
        seen, deaths = int(rec.get("threats") or 0), int(rec.get("deaths") or 0)
        if seen >= _c(cfg, "killzone_used_min") or deaths:
            why.append(f"enemies came this way {seen} time(s)" + (f", {deaths} died by it" if deaths else ""))
            danger += 10 * min(seen, 5) + 20 * min(deaths, 5)
        if not why and not every:
            continue
        if closed:
            why.append("a closed fort keeps every way in")
            danger += 30
        elif not why:
            why.append(f"Fortification or Caution at {lean}")
        out.append((danger, e, why))
    out.sort(key=lambda r: (-r[0], 0 if r[1].get("kind") == "cavern" else 1, r[1]["id"]))
    return out


def zone_kind(s: dict, kz: dict, e: dict, cfg: dict, n: int) -> tuple:
    """(kind, traps, note): the traps for this entrance. 0 traps when every
    enemy known to come this way avoids traps (TRAPAVOID)."""
    near = [t for t in _l(kz.get("threats")) if isinstance(t, dict) and t.get("entrance_id") == e["id"]]
    if near and all(t.get("trapavoid") is True for t in near):
        names = ", ".join(str(t.get("name") or "?") for t in near[:3])
        return "cage", 0, (f"{names} coming this way avoid(s) traps (TRAPAVOID in its raws): DF's traps never "
                           "touch it, so only the drawbridge")
    note = ""
    avoid = [t for t in near if t.get("trapavoid") is True]
    if avoid:
        note = (f"{', '.join(str(t.get('name') or '?') for t in avoid[:3])} avoid(s) traps (TRAPAVOID): the traps "
                "are for the rest")
    fort = int(_traits(s).get("fortification", 0) or 0)
    if fort >= _c(cfg, "killzone_all_slider"):
        return "mixed", n, note
    return "cage", n, note


def _crisis(memory) -> bool:
    return bool(_d(getattr(memory, "crisis", None)).get("why"))


def _link_rule(s: dict, kz: dict, proposals: list) -> bool:
    """A zone's drawbridge built with no lever linked, and a free AI lever: linked."""
    from planner_gates import _free_gate_levers
    for e in _rows(kz):
        br = _d(e.get("drawbridge"))
        if br.get("built") and isinstance(br.get("id"), int) and br.get("linked") is False:
            lever = next((lv for lv in _free_gate_levers(s) if isinstance(lv.get("id"), int)), None)
            if lever is None:
                return False
            proposals.append(Proposal("killzone", {"type": "link_lever", "lever_id": lever["id"],
                                                   "target_id": br["id"]},
                                      f"the kill zone's drawbridge at x{br.get('x')} y{br.get('y')} has no lever: "
                                      "link the AI gate lever to it", 4))
            return True
    return False


def _killzone_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if not player_rules(s).get("killzones", True):
        return
    kz = killzones_of(s)
    rows = _rows(kz)
    if not kz or not rows:
        return
    if _link_rule(s, kz, proposals):
        return
    # full cages: DF hauls them itself (the hazards rule makes the pile and the cages)
    full = sum(int(_d(e.get("traps")).get("full") or 0) for e in rows)
    if full:
        notes.append(f"{full} cage trap(s) in the kill zones hold a catch: DF carries each full cage to an animal "
                     "stockpile and loads an empty one by itself")
    citizens = int(_d(s.get("dwarves")).get("total") or 0)
    if citizens < _c(cfg, "killzone_min_citizens"):
        return
    if _crisis(memory):
        return
    if reachable_threats(s, _traits(s), cfg):
        return                          # the squads and the gates have it; nobody builds in a fight
    # one zone at a time: one being built goes a step on when its step is ready
    building = [e for e in rows if e.get("state") == "building"]
    for e in building:
        br = _d(e.get("drawbridge"))
        if br.get("stage") in ("channel", "ramp") and br.get("step_ready"):
            proposals.append(Proposal("killzone", {"type": "build_killzone", "entrance_id": e["id"],
                                                   "drawbridge": True},
                                      f"the kill zone at x{e['x']} y{e['y']}: "
                                      + ("the channel is dug: its ramp removed, a pit nothing climbs out of"
                                         if br["stage"] == "channel" else "the pit is ready: the drawbridge over it"),
                                      5))
        return
    wanted = [r for r in zone_reasons(s, memory, cfg, rows) if r[1].get("state") == "possible"]
    if not wanted:
        for _, e, why in zone_reasons(s, memory, cfg, rows)[:1]:
            if e.get("state") == "none" and e.get("why"):
                notes.append(f"no kill zone at the {e.get('kind')} entrance x{e['x']} y{e['y']} ({why[0]}): "
                             f"{e['why']}")
        return
    danger, e, why = wanted[0]
    traits = _traits(s)
    lean = max(int(traits.get("fortification", 0) or 0), int(traits.get("caution", 0) or 0))
    n = _c(cfg, "killzone_traps_high") if lean >= _c(cfg, "killzone_all_slider") else _c(cfg, "killzone_traps")
    n = max(0, min(n, int(e.get("trap_tiles") or n)))
    kind, n, kind_note = zone_kind(s, kz, e, cfg, n)
    br = _d(e.get("drawbridge"))
    bridge = bool(br.get("possible"))
    if n == 0 and not bridge:
        notes.append(f"the {e.get('kind')} entrance x{e['x']} y{e['y']}: {kind_note}, and no spot for a drawbridge "
                     f"({br.get('why') or 'none'}): the gates and the shelter keep it out")
        return
    # the Mechanics labour, the mechanisms and the weapons
    mech = kz.get("mechanics")
    if isinstance(mech, int) and mech == 0:
        proposals.append(Proposal("killzone", {"type": "assign_labor", "job": "MECHANIC", "count": 1},
                                  "kill zones need a mechanic (traps, the drawbridge's lever): the labour given to a "
                                  "dwarf", 5))
        return
    need = n + (3 if bridge else 0)      # a mechanism a trap; the bridge's lever and its link's two
    free = kz.get("free_mechanisms")
    if not isinstance(free, int):
        free = _d(s.get("entrances")).get("free_mechanisms")
    if isinstance(free, int) and free < need and not queued(s, {"mechanisms"}):
        proposals.append(Proposal("killzone_parts", {"type": "work_order", "recipe": "mechanisms",
                                                     "amount": need - free},
                                  f"{need - free} mechanism(s) for the kill zone at x{e['x']} y{e['y']} "
                                  f"({free} free)", 5, True))
    if kind == "mixed":
        weapons = n - (n + 1) // 2
        have = int(kz.get("trap_weapons") or 0) + queued(s, {"metal_trap_blades"})
        if have < weapons:
            metal = _best_metal(s, weapons - have)
            if metal and _has_shop(_d(s.get("buildings")), "MetalsmithsForge"):
                proposals.append(Proposal("killzone_parts", {"type": "work_order", "recipe": "metal_trap_blades",
                                                             "amount": weapons - have, "material": metal},
                                          f"{weapons - have} giant axe blade(s) of {metal.split(':')[-1].lower()} "
                                          f"for the kill zone's weapon traps", 5, True))
            else:
                kind = "cage"            # no metal or forge for blades: all cages
    words = {"cage": "cage traps", "mixed": "cage traps, weapon traps behind them", "weapon": "weapon traps",
             "stonefall": "stone-fall traps"}[kind]
    where = (f"the {e.get('kind')} entrance at x{e['x']} y{e['y']} ({'; '.join(why)}): a "
             f"{e.get('corridor') or '?'}-tile narrow way in")
    what = (f"{n} {words}" if n else "no traps") + (
        (", a drawbridge over a channel" if br.get("channel") else ", a drawbridge (no drop: "
         + str(br.get("why") or "none possible") + ")") if bridge else "")
    if kind_note:
        what += f"; {kind_note}"
    proposals.append(Proposal("killzone", {"type": "build_killzone", "entrance_id": e["id"], "traps": n,
                                           "kind": kind, "drawbridge": bridge},
                              f"{where}: {what}", 5))
