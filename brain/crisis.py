"""Crisis mode (0.104.137, phase 12i; Teacheroar, 31 Oct: 73% unhappy, ~45 dead
in a tantrum spiral in six minutes, 14 ghosts, 38 dead unburied, the jail
empty, and the AI still opening library and statue work). When the fort is in
crisis, new expansion waits and recovery comes first: its rules rank ahead,
skip their cooldowns, and get extra action slots each cycle."""

from __future__ import annotations

from planner_core import TICKS_PER_DAY, _d, abs_tick, tantrums_recent

# rules that put a fort back on its feet
RECOVERY_RULES = {
    "burial", "tombs_ghosts", "slabs", "slabs_free", "coffins", "hospital", "doctor_patient", "staff",
    "stress_care", "soap", "cloth", "needs_craft", "needs_shops", "needs_trinkets", "trinket_orders", "needs_finery",
    "needs_drink", "needs_meal", "good_cooks", "recreation", "hospital_burrow", "tavern", "tavern_chest", "temple_chest",
    "tavern_urgent", "jail_urgent", "jail_size", "jail_more", "break_fights", "convict", "mood", "rooms", "drink", "drink_fruit",
    "food", "farms", "kitchen", "water", "well", "well_parts", "pop_cap", "dig_first", "fat_ban",
    "labor", "stone", "furniture",
}
# (0.104.168) the infected put to bed, soap two steps a cycle, more doctors,
# and the offices the dead held filled again
RECOVERY_RULES |= {"infected_rest", "soap_rush", "doctor_post", "appoint"}
# (0.104.169) the barrels and pots the crisis's brewing waits for
RECOVERY_RULES |= {"containers"}
RECOVERY_RULES |= {"calm_burrow"}     # (0.104.169) a tantrum kept away from the others
RECOVERY_RULES |= {"booze_variety"}   # (0.105.24) the worst stress in B and E: the same old booze
# levels that are themselves recovery when started (a build of these kinds is never held)
RECOVERY_KINDS = {"hospital", "tombs", "dining", "tavern", "temple", "jail", "bedrooms", "workshops",
                  "suites", "well", "farms", "storage"}
# work that can wait while the fort is in crisis ((0.104.164) not the traction
# bench's parts: care for the wounded, held while a patient waited for traction)
EXPANSION_RULES = {"polish", "stairwell", "grandeur", "location_value", "glass", "gems", "gem_cutting",
                   "encrust", "squad_make", "war_animals", "instruments",
                   "instrument_orders", "industry", "idle"}


def deaths_recent(s: dict, memory, days: int = 28) -> int:
    now = abs_tick(s)
    return sum(1 for t in (getattr(memory, "deaths_seen", None) or [])
               if isinstance(t, int) and 0 <= now - t < days * TICKS_PER_DAY)


def note_deaths(state: dict, memory, events: list) -> int:
    """Citizens' deaths from the bridge's events (a ghost laid to rest, an
    animal or an outsider not counted). Returns how many new."""
    now, n = abs_tick(state), 0
    for e in events or []:
        if (isinstance(e, dict) and e.get("kind") == "death" and e.get("own_civ") and not e.get("animal")
                and not e.get("again") and not e.get("ghost")):
            memory.deaths_seen.append(now)
            n += 1
            # (0.104.139) killed by one of their own in a real fight (not a
            # sparring accident; an older bridge says no level: counted)
            # (0.104.141) "None" too: DF's level for the strangling of patients
            # (Teacheroar 19:24, a Hammer Lord suffocated a patient: no fight
            # level, so nothing counted and the fights were never broken up)
            if e.get("killer_kind") == "citizen" and e.get("conflict") in (None, "None", "Brawl", "Nonlethal", "Lethal",
                                                                          "NoQuarter"):
                memory.fight_deaths.append(now)
    memory.deaths_seen = [t for t in memory.deaths_seen if isinstance(t, int) and 0 <= now - t < 84 * TICKS_PER_DAY][-500:]
    memory.fight_deaths = [t for t in memory.fight_deaths if isinstance(t, int) and 0 <= now - t < 28 * TICKS_PER_DAY][-500:]
    return n


def crisis_reasons(s: dict, memory, cfg: dict, held: bool) -> list:
    """Why the fort is in crisis now ([] when it isn't). While held, the
    "clear" levels must all be reached to let go (no flicker)."""
    import outcomes
    m = outcomes.measure(s)
    pop = max(1, int(m.get("pop") or 0))
    k = "_clear" if held else ""
    out = []
    un = m.get("unhappy_pct")
    if isinstance(un, (int, float)) and un >= cfg["crisis_unhappy" + k + "_pct"]:
        out.append(f"{un:g}% unhappy")
    dead = deaths_recent(s, memory)
    if dead >= max(cfg["crisis_deaths" + k], round(pop * cfg["crisis_deaths" + k + "_share"])):
        out.append(f"{dead} citizens dead in 4 weeks")
    d = _d(s.get("dead"))
    ghosts = int(d.get("ghosts") or 0)
    if ghosts >= cfg["crisis_ghosts" + k]:
        out.append(f"{ghosts} ghosts")
    tan = tantrums_recent(s, memory)
    if tan >= cfg["crisis_tantrums" + k]:
        out.append(f"{tan} tantrums in 4 weeks")
    return out


def update(s: dict, memory, cfg: dict, notes: list) -> list:
    """The crisis level for this cycle, kept in memory (`crisis`: since, why).
    It ends only once every reason is under its clear level and it has lasted
    `crisis_min_days`. Returns the reasons ([] when there's no crisis)."""
    now = abs_tick(s)
    c = memory.crisis if isinstance(memory.crisis, dict) else {}
    held = bool(c.get("since"))
    why = crisis_reasons(s, memory, cfg, held)
    if why and not held:
        memory.crisis = {"since": now, "why": why}
        notes.append("CRISIS: the fort is in crisis (" + "; ".join(why) + "): new expansion waits and recovery "
                     "comes first (burial, slabs, the hospital, justice, needs)")
    elif held and not why and now - int(c.get("since") or now) >= cfg["crisis_min_days"] * TICKS_PER_DAY:
        memory.crisis = {}
        notes.append("the crisis is over: expansion goes on")
        return []
    elif held:
        memory.crisis = dict(c, why=why or c.get("why") or [])
    return (memory.crisis or {}).get("why") or []


def is_expansion(p) -> bool:
    a = p.action
    if p.rule in RECOVERY_RULES:
        return False
    if a.get("type") == "start_project":
        if a.get("urgent") or a.get("kind") in RECOVERY_KINDS and not a.get("set_piece") and not a.get("growth"):
            return False
        return True                            # the ladder's optional levels, growth halls, set pieces, gardens
    return p.rule in EXPANSION_RULES


def is_recovery(p) -> bool:
    """A recovery step: a recovery rule, or a level that is itself recovery
    (urgent, or a hospital, tombs, dining hall, tavern, temple...)."""
    if p.rule in RECOVERY_RULES:
        return True
    return p.action.get("type") == "start_project" and not is_expansion(p)


def apply(proposals: list, why: list, notes: list) -> list:
    """Expansion held, recovery ranked first (priority - 2)."""
    if not why:
        return proposals
    kept, waiting = [], []
    for p in proposals:
        if is_expansion(p):
            waiting.append(p)
            continue
        if is_recovery(p):
            p.priority -= 2
        kept.append(p)
    if waiting:
        names = sorted({(p.action.get("kind") or p.rule) for p in waiting})
        notes.append(f"crisis ({'; '.join(why)}): {len(waiting)} expansion step(s) wait: {', '.join(names[:8])}")
    return kept
