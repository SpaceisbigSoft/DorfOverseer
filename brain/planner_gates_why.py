"""planner_gates_why (R32 b): what the gates rules say about the
entrances and the lifted lockdown. B (26 Nov 08:33-08:39): "watch the 1
gate(s)" with 2 entrances (a Giantess walked in by the other, 13 dead), then
"shut for days with no new enemy: open the gates" while she killed. Read by
planner_gates and planner_gates_lockdown (imported in their functions, so
their names stay as pinned)."""

from __future__ import annotations

from digest import _d, _l


def release_void(s: dict, cfg: dict, ids: list) -> str:
    """(R32 b) Why a lockdown may not be lifted early now ("" if it may): one
    of these enemies is no ordinary one (a great danger, a building
    destroyer, a flier or a fire breather: no gate or door holds it, and the
    squads, not an open gate, answer it) or is among the dwarves
    (few_near: killing, not waiting about). B (26 Nov 08:39): "shut for days
    with no new enemy: open the gates" and the alarm down while a Giantess
    inside killed 13 in 4 minutes."""
    from planner_gates_lockdown import few_near
    rows = {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats")) if isinstance(t, dict)}
    for i in ids or []:
        t = _d(rows.get(i))
        for k, word in (("great_danger", "a great danger"), ("destroyer", "a building destroyer"),
                        ("flier", "a flier"), ("fire_breather", "a fire breather")):
            if t.get(k):
                return f"{t.get('name') or t.get('race') or 'an enemy'} ({word}) is on the map"
        big = [x for x in _l(t.get("kinds")) if x in ("Megabeast", "SemiMegabeast", "Titan", "ForgottenBeast", "Demon")]
        if big:
            return f"{t.get('name') or t.get('race') or 'an enemy'} (a {big[0]}) is on the map"
    if ids and few_near(s, cfg, list(ids)):
        return "an enemy is among the dwarves"
    return ""


def released_text(s: dict, memory, cfg: dict, traits: dict | None = None) -> str:
    """(R32 b) What the lifted lockdown's "open the gates" says: the enemies
    still on the map and why it is lifted (its record), never "no new
    enemy" alone while one is there."""
    from planner_gates_lockdown import _lockdown, _lockdown_ids
    from planner_core import _traits
    rec = _lockdown(memory)
    ids = _lockdown_ids(s, traits if traits is not None else _traits(s), cfg)
    why = str(rec.get("released_why") or "").strip()
    if ids:
        return (f"the AI's lockdown was lifted: {len(ids)} ordinary enemy/enemies left, all inside the fort "
                f"(shut, the gates keep only the others out)" + (f", and {why}" if why else "")
                + ": open the gates (a new enemy, or one among the dwarves, closes them again)")
    return "the fort has been shut for days and no enemy is left in reach: open the gates"


def _entrance_why(s: dict, memory, cfg: dict, e: dict) -> str:
    """(R32 b) Why this entrance can't shut now, and what the AI does about
    it, in a few words ("" when its gate can shut)."""
    spot = f"{e.get('x')},{e.get('y')},{e.get('z')}"
    unworked = [b for b in _l(e.get("bridges_unworked")) if isinstance(b, int)]
    if _l(e.get("equipment")) and e.get("sealed"):
        from planner_holdfast import door_only, building_destroyers
        if door_only(e) and building_destroyers(s):
            return ("only a door or hatch holds it, and a building destroyer is on the map: it breaks them; "
                    "the squads and the shelter answer it")
        return ""
    if unworked:
        wait = e.get("lever_wait_days")
        if isinstance(wait, int) and not isinstance(wait, bool) and wait > 0:
            return f"its drawbridge has waited {wait} day(s) for a lever inside: the AI places and links one"
        if e.get("closing"):
            return "its drawbridge waits for its lever to be linked (a mechanic's job)"
        return "its drawbridge has no lever inside to work it: the AI places one and links it"
    if e.get("closing"):
        waiting = _d(e.get("waiting"))
        what = ", ".join(f"{n} {k}" for k, n in waiting.items() if isinstance(n, int) and n > 0)
        return "its gate is still being built" + (f" (waits for {what})" if what else "")
    why = _d(getattr(memory, "gate_failures", None)).get(spot)
    if why:
        return f"the game refused a gate there ({str(why)[:80]}): the AI tries again"
    if e.get("door_spots"):
        return f"nothing closes it: {e['door_spots']} door(s) to be put across it"
    if e.get("deep_road"):
        return "the underground depot's wagon road, with no drawbridge yet"
    if isinstance(e.get("cut_hatches"), int) and e["cut_hatches"] > 0:
        return f"{e['cut_hatches']} hatch(es) planned on the stairs below it"
    if (e.get("width") or 0) > cfg.get("fortify_max_width", 50):
        return f"{e.get('width')} wide, past what the AI can wall: open, the alarm and squads answer there"
    from planner_gates import _near_spot
    if memory is not None and _near_spot(e, getattr(memory, "gates_fortified", None) or {}):
        return "the gate the AI planned there waits on the dwarves to build it"
    return "no gate: the AI walls it down to a gate"


def entrances_not_shutting(s: dict, memory, cfg: dict, es: list, off: int = 0) -> list:
    """(R32 b) The entrances that can't shut now: [(where, why)]. B (26 Nov):
    "watch the 1 gate(s)" while a second entrance had none, and a Giantess
    walked in by it."""
    out = []
    for e in es:
        if not isinstance(e, dict):
            continue
        why = _entrance_why(s, memory, cfg, e)
        if why:
            where = (f"the {e.get('kind')} entrance at elevation {(e.get('z') or 0) + off} "
                     f"(x{e.get('x')} y{e.get('y')})")
            out.append((where, why))
    return out


def cant_text(cant: list) -> str:
    """(R32 b) "; N can't shut: where (why); ..." for the gates line ("" for none)."""
    if not cant:
        return ""
    return (f"; {len(cant)} can't shut: " + "; ".join(f"{w} ({y})" for w, y in cant[:3])
            + (f"; and {len(cant) - 3} more" if len(cant) > 3 else ""))
