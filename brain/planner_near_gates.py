"""(0.105.47, I7d 2a) Surface work kept near the gates while a great danger
the squads can't beat is about.

Why (C, y258-259): a savanna titan and a hill titan walked in at the map's
edge. The alarm was up 50 ticks after each arrival, and still the
fisherdwarves 60 to 200 tiles out died within 500-1000 ticks: the alarm can't
bring a dwarf home from that far. B lost a fishery worker 800 ticks after its
titan came, A an outpost liaison on the surface.

What it reads: the report's `others_on_map.threats` (great_danger, kinds,
layer, the threat facts), `military.squads` (power), the bridge's
`near_gates` section (lua/ai-near-gates.lua: on, members, radius, gates, the
citizens outside farther than the radius from every surface way in), and
`field_watch` (merchants on the map).

What it does (rule `near_gates`, action `near_gates`):
  * a danger: a great danger (or a titan, megabeast or semi-megabeast) on the
    map that isn't down in the caverns, the magma sea or the underworld (it
    can walk to the surface), that the squads can't beat: planner_matchup's
    judge of the able squads against all of them under `fight_ratio`, a
    fight with it called off, or no squad at all;
  * while one is on the map, and `near_gates_hold_days` after the last one
    left: every civilian goes into the "AI near gates" burrow (the fort's
    inside and `near_gates_radius` tiles round each surface way in): fishing,
    gathering, felling, herding and hunting go on near the gates and nowhere
    farther, so the alarm finds them a short walk from home;
  * then off, the members let out;
  * the members are refreshed once a day while a far-out civilian who isn't
    a member is seen (a migrant, one let out of the hospital);
  * a note names the citizens still out far, and any merchants on the map
    (arrivals walk in from the edge, the AI can't stop them; the caravan
    guard rule sends a squad where the matchup allows).
Not while the weather keep-in holds the civilians inside (stricter: the
burrow is let go, and taken again after). With `near_gates` False in the
config nothing is proposed. Without the `near_gates` section (an older
bridge) nothing is proposed or noted.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, abs_tick, can_fight, player_rules

__all__ = ["DEEP_LAYERS", "GREAT_KINDS", "surface_dangers", "unbeatable", "_near_gates_rule", "stalker_kind", "stalker_why"]

DEEP_LAYERS = ("Cavern", "MagmaSea", "Underworld")
GREAT_KINDS = {"Titan", "Megabeast", "SemiMegabeast"}
FAR_NAMES = 4


def stalker_kind(t: dict) -> str:
    """(r36) What a stalker row is, in a word or two, from its own fields."""
    kinds = t.get("kinds") if isinstance(t.get("kinds"), list) else []
    if t.get("transformed") is True or t.get("were_curse") is True:
        return "a were"
    if "NightCreature" in kinds:
        return "a night creature"
    if t.get("ambush") is True:
        return "a hidden ambusher"
    if t.get("hidden") is True:
        return "hidden"
    if t.get("arrival") is True:
        return "a hostile arrival"
    return "a stalker"


def stalker_why(s: dict, prowl: list) -> str:
    """(r36) The near-gates reason for stalkers: inside the fort or outside it
    (B 26 Nov 18:22: an ambusher in the tavern was said to stalk "outside")."""
    from planner_holdfast import _inside_ids
    ins = _inside_ids(s)
    inside = [t for t in prowl if t.get("id") in ins or t.get("inside") is True]
    outside = [t for t in prowl if t not in inside]

    def what(rows):
        ks = []
        for t in rows:
            k = stalker_kind(t)
            if k not in ks:
                ks.append(k)
        return ", ".join(ks)
    parts = []
    if inside:
        parts.append(f"{'it is' if len(inside) == 1 else f'{len(inside)} are'} inside the fort ({what(inside)})")
    if outside:
        parts.append(f"{'it stalks' if len(outside) == 1 else f'{len(outside)} stalk'} the dwarves outside ({what(outside)})")
    return "; ".join(parts)


def _section(s: dict) -> dict | None:
    if "near_gates" in _d(s.get("_errors")):
        return None
    n = s.get("near_gates")
    if not isinstance(n, dict) or not n or n.get("error"):
        return None
    return n


def surface_dangers(s: dict) -> list:
    """The great dangers on the map that can come to the surface."""
    out = []
    for t in _l(_d(s.get("others_on_map")).get("threats")):
        if not isinstance(t, dict):
            continue
        kinds = {str(k) for k in _l(t.get("kinds"))}
        if not (t.get("great_danger") is True or kinds & GREAT_KINDS):
            continue
        layer = str(t.get("layer") or "")
        if any(layer.startswith(d) for d in DEEP_LAYERS):
            continue
        out.append(t)
    return out


def unbeatable(s: dict, memory, cfg: dict, dangers: list) -> tuple[bool, str]:
    """(yes, why): can the squads NOT beat these dangers? planner_matchup's
    judge of the able squads at fight_ratio; a called-off fight; no squad."""
    if not dangers:
        return False, ""
    from planner_matchup import judge
    from planner_military import called_off_ids, fight_key
    if called_off_ids(s, memory) & {t.get("id") for t in dangers}:
        return True, "a fight with it was called off"
    if player_rules(s).get("attack_policy") == "never":
        return True, "the Rules tab says never attack"
    able = [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and can_fight(q, cfg)]
    if not able:
        return True, "no squad able to fight"
    ff = _d(getattr(memory, "fight_factor", None)) if memory is not None else {}
    j = judge(dangers, able, lambda t: float(ff.get(fight_key(t)) or 1.0))
    bar = float(cfg.get("fight_ratio", 2.0))
    if j["ratio"] >= bar:
        return False, f"the squads {j['army']:.0f} against {j['need']:.0f}"
    return True, f"the squads {j['army']:.0f} against {j['need']:.0f}, {bar:g}x needed"


def _book(memory) -> dict:
    if memory is None:
        return {}
    b = getattr(memory, "near_gates_seen", None)
    if not isinstance(b, dict):
        b = {}
        try:
            memory.near_gates_seen = b
        except AttributeError:
            pass
    return b


def _names(rows: list) -> str:
    names = [str(r.get("name") or r.get("id")) + (f" ({r['d']} tiles out)" if isinstance(r.get("d"), int) else "")
             for r in rows[:FAR_NAMES]]
    more = len(rows) - FAR_NAMES
    return ", ".join(names) + (f" and {more} more" if more > 0 else "")


def _near_gates_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    if not cfg.get("near_gates", True):
        return
    sec = _section(s)
    if sec is None:
        return
    now = abs_tick(s)
    book = _book(memory)
    dangers = surface_dangers(s)
    bad, why = unbeatable(s, memory, cfg, dangers)
    names = ", ".join(str(t.get("name") or t.get("id")) for t in dangers[:3])
    if not bad:
        # (r34b) a stalker out of the deep layers (a hidden hostile, a were, a night
        # creature, a hostile arrival: planner_hostile_arrivals) hunts the dwarves out
        # far whatever the matchup: B's tavern keeper died 100 tiles from the gates
        from planner_hostile_arrivals import stalker_rows
        prowl = stalker_rows(s)
        if prowl:
            bad = True
            why = stalker_why(s, prowl)
            names = ", ".join(str(t.get("name") or t.get("id")) for t in prowl[:3])
    if bad:
        book["last"], book["who"] = now, names[:120]
    last = book.get("last")
    held = (not bad and isinstance(last, int) and 0 <= now - last < cfg.get("near_gates_hold_days", 3) * TICKS_PER_DAY)
    want = bad or held
    on = sec.get("on") is True
    radius = int(cfg.get("near_gates_radius", 25))
    from planner_weather import keep_in_active
    if want and keep_in_active(memory):
        if on:
            proposals.append(Proposal("near_gates", {"type": "near_gates", "on": False},
                                      "the weather keep-in holds the civilians inside (stricter): the near-gates "
                                      "burrow lets them go to it", 2))
        return
    far = [r for r in _l(sec.get("far")) if isinstance(r, dict)]
    if want and not on:
        what = (f"{names} ({why})" if bad else
                f"{book.get('who') or 'a great danger'} left the map under "
                f"{cfg.get('near_gates_hold_days', 3)} days ago")
        proposals.append(Proposal("near_gates", {"type": "near_gates", "on": True, "radius": radius},
                                  f"{what}: the civilians' work outside stays within {radius} tiles of the gates "
                                  "(the AI near gates burrow), so the alarm finds them near home "
                                  "(C's fishers 60-200 tiles out died before they got in)", 1))
    elif want and on:
        stray = [r for r in far if not r.get("member")]
        if stray:
            proposals.append(Proposal("near_gates_refresh", {"type": "near_gates", "on": True, "radius": radius},
                                      f"{len(stray)} civilian(s) outside far from the gates and not in the near-gates "
                                      "burrow (newcomers?): taken in", 2))
    elif not want and on:
        proposals.append(Proposal("near_gates", {"type": "near_gates", "on": False},
                                  "no great danger the squads can't beat has been on the map for "
                                  f"{cfg.get('near_gates_hold_days', 3)} days: surface work goes anywhere again", 4))
    if want:
        if far:
            notes.append(f"near gates: {int(sec.get('far_total') or len(far))} citizen(s) still outside far from the "
                         f"gates while {names or book.get('who') or 'a great danger'} is about: {_names(far)}")
        merchants = int(_d(s.get("field_watch")).get("merchants") or 0)
        if bad and merchants:
            notes.append(f"near gates: {merchants} merchant(s) or their animals on the map while {names} is about: "
                         "arrivals walk in from the edge and the AI can't stop them (a squad guards the caravan "
                         "only where the matchup allows)")
