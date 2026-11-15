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
    "needs_meal", "good_cooks", "recreation", "hospital_burrow", "tavern", "tavern_chest", "temple_chest",
    "tavern_urgent", "jail_urgent", "jail_size", "jail_more", "break_fights", "convict", "mood", "rooms", "drink", "drink_fruit",
    "food", "farms", "kitchen", "water", "well", "well_parts", "pop_cap", "dig_first", "fat_ban",
    "labor", "stone", "furniture",
}
# (0.104.168) the infected put to bed, soap two steps a cycle, more doctors,
# and the offices the dead held filled again
RECOVERY_RULES |= {"infected_rest", "soap_rush", "doctor_post", "appoint"}
# (0.104.169) the barrels and pots the crisis's brewing waits for
RECOVERY_RULES |= {"containers"}
# (0.104.169) calm_burrow was here. (0.105.47, R2 item 3) Dropped from the
# recovery rules: it never held a tantrum anywhere (members seen outside 54 of
# 60 times in E, 9 of 9 in B, 2 of 2 in F; 344 of 349 over five forts by
# 0.105.24). The rule itself stays, measured, for a fort where it might hold
# (it retires itself at 90% outside after 40 looks); it gets no crisis push.
# The crisis's tantrum levers now: posts taken from tantrum-throwers, the
# loyalty fix on every tantrum, a guard at the hospital, the chronic cases
# one by one (brain/planner_tantrums.py), all recovery rules:
RECOVERY_RULES |= {"staff_tantrum", "chronic_posts", "chronic_care", "hospital_guard"}
RECOVERY_RULES |= {"booze_variety"}   # (0.105.24) the worst stress in B and E: the same old booze
# levels that are themselves recovery when started (a build of these kinds is never held)
# (0.105.48, K5) one table for crisis and recovery: brain/hold_classes.py
import hold_classes as _hc  # noqa: E402

RECOVERY_KINDS = _hc.SURVIVAL_KINDS
# work that waits while the fort is in crisis: every rule classed expansion
# (0.105.48, K5: it was 14 names by hand, squad_make among them; the guard's
# squads are defence now, and the hunts, missions, kill zones, landmarks,
# the hall and the keep wait as in recovery)
EXPANSION_RULES = _hc.EXPANSION_RULES
# the lists before 0.105.48, kept only for `crisis_hold_table` False (the
# tests that compare plan() with main's)
_OLD_KINDS = {"hospital", "tombs", "dining", "tavern", "temple", "jail", "bedrooms", "workshops",
              "suites", "well", "farms", "storage"}
_OLD_EXPANSION = {"polish", "stairwell", "grandeur", "location_value", "glass", "gems", "gem_cutting",
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
            # (0.105.47) the bridge marks a tantrum's, a berserker's or a possessed killer's kill
            if (e.get("killer_kind") == "citizen" and e.get("conflict") in (None, "None", "Brawl", "Nonlethal", "Lethal",
                                                                          "NoQuarter", "Tantrum", "Berserk",
                                                                          "Possessed")
                    and e.get("mood") != "Berserk"):
                # (0.105.47 merge) a berserker struck down by the fort is
                # defence, not a spiral (I7c: 16 such deaths, every one
                # after a failed mood, the fights broken up at once): not counted
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
    # (0.105.47, R2 item 3, I7c) small forts: E (23-45 dwarves) never reached
    # 10 tantrums in 28 days (its 44 came from 4-5 dwarves, one or two at a
    # time), and its y257 cascade began with crisis mode off. Now any citizen
    # killed by a citizen, or 2+ dwarves each with 2+ tantrums in 28 days,
    # starts it; held, it lasts while a tantrum was seen in the last 14 days
    now = abs_tick(s)
    kills = sum(1 for t in (getattr(memory, "fight_deaths", None) or [])
                if isinstance(t, int) and 0 <= now - t < cfg["crisis_kill_days"] * TICKS_PER_DAY)
    if kills:
        out.append(f"{kills} citizen(s) killed by citizens in {cfg['crisis_kill_days']} days")
    reps = repeat_tantrum_dwarves(s, memory, cfg["crisis_repeat_tantrums"])
    if len(reps) >= cfg["crisis_repeat_dwarves"]:
        out.append(f"{len(reps)} dwarves threw {cfg['crisis_repeat_tantrums']}+ tantrums each in 4 weeks "
                   f"({', '.join(reps[:3])})")
    elif held and out == [] and tantrum_seen(s, memory, cfg["crisis_tantrum_quiet_days"]):
        out.append(f"a tantrum in the last {cfg['crisis_tantrum_quiet_days']} days")
    return out


def repeat_tantrum_dwarves(s: dict, memory, n: int, days: int = 28) -> list:
    """(0.105.47) Dwarves with n+ tantrums in `days`: from the bridge's ledger
    (the tantrums section, each dwarf by id) or, without it, the game's
    announcements by name (memory.tantrums, a dwarf a day); the larger list."""
    ledger = [str(r.get("name") or r.get("id")) for r in (_d(s.get("tantrums")).get("dwarves") or [])
              if isinstance(r, dict) and days == 28 and int(r.get("n28") or 0) >= n]
    now = abs_tick(s)
    by: dict = {}
    for t in (getattr(memory, "tantrums", None) or []):
        if isinstance(t, list) and len(t) == 2 and isinstance(t[0], int) and 0 <= now - t[0] < days * TICKS_PER_DAY:
            by[str(t[1])] = by.get(str(t[1]), 0) + 1
    named = sorted(w for w, k in by.items() if k >= n)
    return ledger if len(ledger) >= len(named) else named


def tantrum_seen(s: dict, memory, days: int) -> bool:
    """(0.105.47) A tantrum loose now or begun in the last `days` (the ledger or the announcements)."""
    sec = _d(s.get("tantrums"))
    if int(sec.get("loose") or 0) > 0:
        return True
    now = abs_tick(s)
    for r in sec.get("dwarves") or []:
        last = r.get("last") if isinstance(r, dict) else None
        if isinstance(last, int) and 0 <= now - last < days * TICKS_PER_DAY:
            return True
    return tantrums_recent(s, memory, days) > 0


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


def _old_table(cfg) -> bool:
    return isinstance(cfg, dict) and cfg.get("crisis_hold_table") is False


def is_expansion(p, cfg=None) -> bool:
    """(0.105.48, K5) A step classed expansion (hold_classes.step_class): the
    rule outranks a start_project's kind (a Jeweler's level from `gems` waits),
    a crisis recovery rule's own level goes."""
    if _old_table(cfg):
        a = p.action
        if p.rule in RECOVERY_RULES:
            return False
        if a.get("type") == "start_project":
            return not (a.get("urgent") or a.get("kind") in _OLD_KINDS and not a.get("set_piece")
                        and not a.get("growth"))
        return p.rule in _OLD_EXPANSION
    return _hc.step_class(p) == _hc.EXPANSION


def is_recovery(p, cfg=None) -> bool:
    """A recovery step: a recovery rule, or a level that is itself recovery
    (urgent, or a hospital, tombs, dining hall, tavern, temple...). Never an
    expansion step (0.105.48, K5: a `gems` workshops level was boosted)."""
    if _old_table(cfg):
        return p.rule in RECOVERY_RULES or (p.action.get("type") == "start_project" and not is_expansion(p, cfg))
    if is_expansion(p):
        return False
    if p.rule in RECOVERY_RULES:
        return True
    return p.action.get("type") == "start_project"


def apply(proposals: list, why: list, notes: list, cfg=None) -> list:
    """Expansion held, recovery ranked first (priority - 2)."""
    if not why:
        return proposals
    kept, waiting = [], []
    for p in proposals:
        if is_expansion(p, cfg):
            waiting.append(p)
            continue
        if is_recovery(p, cfg):
            p.priority -= 2
        kept.append(p)
    if waiting:
        names = sorted({(p.action.get("kind") or p.rule) for p in waiting})
        notes.append(f"crisis ({'; '.join(why)}): {len(waiting)} expansion step(s) wait: {', '.join(names[:8])}")
    return kept
