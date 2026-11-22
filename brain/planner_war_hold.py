"""(r1g5) The alarm and the squads in a real threat.

Why (run of 15-16 Nov, 0.105.55):
  * B (Monastery, y262): a lone hero visitor (Len, axeman) inside. The keeper
    noted "no squad has anyone armed to send" at 09:32:02; 11 seconds later
    `threat_alert` lowered the alarm "only 1 enemy left, inside the fort, and
    a squad on them" (planner.py _threat_alert, via lone_alert_over: half a
    day since he was first read as inside, no look at any kill order). In the
    same minute `squad_trim` sent 2 of 4 soldiers home and `train` put the
    squad off duty ("only 10 dwarves"): his reach flickered for one cycle,
    and those rules only looked at this cycle's reach. 19 citizens died.
  * F (y256): the squad put on training at 01:46:36 ("enemies can reach")
    and off duty again 16 s later while visitors killed the last 4.
  * E (y256-y259): a fire-spitting Hill Titan inside; no squad was ever sent
    (fire: no melee; no crossbows), and nothing lowered the alarm for 812
    game days: idle 45-52%, nothing dug, 7 thirst and 7 hunger deaths.
  * C (y255): five squads sent at a titan at 02:05:57 and called back at
    02:06:09 for one cycle's odds (0.5x), sent again, called back again.
  * A (y260): 22 of 57 soldiers armed with 68 steel bars in stock, after 220
    soldier swaps; B's defence floor drafted 6 soldiers and armed none.

What this module gives the planner (each piece used where the rule lives):
  * lone_hunted: the lone intruders' alarm comes down only while an AI squad
    has a kill order naming every one of them (the test _lone_squad uses for
    "a squad is already on them"), or once they are gone;
  * unfought: an alarm the AI raised for enemies in reach that no squad has
    gone at for `r1g5_unfought_alarm_days` ends: the fort fights (every squad
    with anyone armed, crossbows only at a beast no melee squad may face)
    when the matchup is at least `r1g5_unfought_fight_ratio`, once an alarm;
    else (or once that fight turned bad) the alarm is lifted, the gates keep
    shutting on the danger, and it is not raised again for the same enemies
    (a new one raises it). `r1g5_alarm_hard_days` is the most any such alarm
    stands;
  * army_danger / war_hold_filter: no squad trim, no soldier swap, no routine
    change that sends a squad off duty or swaps one training for another
    while an enemy can reach the dwarves, is inside, the AI's alarm is up, or
    an enemy could reach them within `r1g5_army_hold_ticks`;
  * arm_first: the squads' unarmed soldiers are armed (weapons made from the
    fort's bars) before more are drafted; no soldier swap while fewer than
    `r1g5_swap_armed_share` of the soldiers on duty are armed;
  * recall_hold / _recall_filter: a squad the AI sent less than
    `kill_hold_ticks` ago is not called back (squad_recall, the hiding
    rule's shelter_squads) for the odds alone: only when it is losing (a
    third of its soldiers lost, half wounded), its fight was called off for
    its losses, or the odds against everything in reach are hopeless
    (`r1g5_recall_hopeless_ratio`).
"""

from __future__ import annotations

import dataclasses

from digest import _d, _l
from planner_core import TICKS_PER_DAY, GEAR_METALS, GEAR_WEAPONS, Proposal, abs_tick, reachable_threats, _traits

__all__ = ["UNFOUGHT_WHY", "lone_hunted", "unfought", "unfought_raise_held", "book_unfought", "army_danger",
           "war_hold_filter", "arm_first", "arm_check", "armed_count", "great_among_civilians", "fight_bar_unfought", "swap_armed_short", "recall_hold", "note_war_hold"]

UNFOUGHT_WHY = "no squad has gone at"


from util import is_int as _int  # noqa: E402  (r6 c2) was a copy here


# (r6 c2) kept local: unlike util's helpers (no table, `default`)
def _c(cfg: dict, k: str, default):
    v = cfg.get(k, default) if isinstance(cfg, dict) else default
    return default if v is None else v


def _rec(memory) -> dict:
    atlas = getattr(memory, "atlas", None) if memory is not None else None
    return _d(_d(atlas).get("unfought"))


def _set_rec(memory, rec: dict) -> None:
    if memory is None:
        return
    if not isinstance(getattr(memory, "atlas", None), dict):
        memory.atlas = {}
    if rec:
        memory.atlas["unfought"] = rec
    else:
        memory.atlas.pop("unfought", None)


def _squads(s: dict) -> list:
    return [q for q in _l(_d(s.get("military")).get("squads")) if isinstance(q, dict) and q.get("id") is not None]


def _kill(q: dict) -> set:
    return {x for x in _l(q.get("kill_ids")) if _int(x)}


def _on_them(q: dict) -> bool:
    """A squad of the AI's out on a kill order (the _lone_squad test)."""
    return bool(q.get("ai_orders") and not q.get("guarding") and not q.get("sheltering")
                and isinstance(q.get("kill_ids"), list))


def lone_hunted(s: dict, lone: list) -> bool:
    """Has an AI squad a kill order naming each of these lone intruders?"""
    want = {i for i in lone if _int(i)}
    if not want:
        return False
    named = set()
    for q in _squads(s):
        if _on_them(q):
            named |= _kill(q) & want
    return named == want


def _rows(s: dict) -> dict:
    return {t.get("id"): t for t in _l(_d(s.get("others_on_map")).get("threats"))
            if isinstance(t, dict) and t.get("id") is not None}


def _alarm_on_tick(memory):
    g = getattr(memory, "alarm_gov", None) if memory is not None else None
    on = _d(_d(g).get("on"))
    return on.get("tick") if _int(on.get("tick")) else None


def _militia(s: dict) -> list:
    """Every squad with anyone armed, not on the player's own orders (the call for the armed)."""
    out = []
    for q in _squads(s):
        if int(q.get("orders") or 0) > int(q.get("ai_orders") or 0):
            continue                                   # the player's
        armed = _d(q.get("power")).get("armed")
        if int(q.get("members") or 0) > 0 and (not _int(armed) or armed > 0):
            out.append(q)
    return out


def _can_go(q: dict, t: dict) -> bool:
    """May this squad go at this enemy: never melee at a beast whose breath,
    dust or webs make closing in suicidal (planner_matchup.melee_bar)."""
    from planner_matchup import melee_bar, shoots
    return shoots(q) or not melee_bar(t) and t.get("fire_breather") is not True


def _ratio(s: dict, memory, rows: list, squads: list) -> float:
    from planner_matchup import judge
    from planner_military import fight_key
    ff = _d(getattr(memory, "fight_factor", None)) if memory is not None else {}
    if not rows or not squads:
        return 0.0
    # a beast no melee squad may face: only the squads that shoot count against it
    for t in rows:
        if not any(_can_go(q, t) for q in squads):
            return 0.0
    return float(judge(rows, squads, lambda t: float(ff.get(fight_key(t)) or 1.0))["ratio"])


def _inside_near(s: dict, cfg: dict, t: dict) -> bool:
    """(x4) This enemy is inside the fort (the walked area: DF's intruders
    inside, or the row's own `inside`) and within `r1x4_inside_near_tiles`
    of a dwarf: among the civilians."""
    inside = {x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if _int(x)}
    if not (t.get("id") in inside or t.get("inside") is True):
        return False
    d = t.get("distance_to_nearest_dwarf")
    near = float(_c(cfg, "r1x4_inside_near_tiles", 30))
    # no distance read: inside is taken as near (the safe side for the civilians)
    return not isinstance(d, (int, float)) or isinstance(d, bool) or d <= near


def great_among_civilians(s: dict, cfg: dict, rows: list) -> str:
    """(x4) The name of a great danger (titan, forgotten beast, megabeast...)
    among these rows that is inside the fort near a dwarf ("" if none): the
    long alarm is never lifted for it (S3: the 60-day lift sent the civilians
    back to work beside a titan)."""
    from planner_core import GREAT_LIKE_KINDS
    for t in rows:
        if not isinstance(t, dict):
            continue
        kinds = set(t.get("kinds") if isinstance(t.get("kinds"), list) else [])
        great = t.get("great_danger") is True or bool(kinds & (GREAT_LIKE_KINDS - {"Undead", "NightCreature"}))
        if great and _inside_near(s, cfg, t):
            return str(t.get("name") or "a great danger").split(",")[0][:40]
    return ""


def fight_bar_unfought(s: dict, cfg: dict, rows: list) -> tuple[float, str]:
    """(x4) The all-out attack's bar: the matchup's own sortie bar
    (planner_matchup.fight_bar: about even odds, a clear win for a fire
    breather or powers the AI can't read), at least
    `r1g5_unfought_fight_ratio`; times `r1x4_unfought_inside_factor` when
    every one of them is inside the fort near a dwarf: there they kill
    civilians whatever the squads do, and a fight begun below even odds ends
    at its first losses (`r1x4_poor_odds_losses`), so the lower bar costs a
    few soldiers at most, not the army."""
    from planner_matchup import fight_bar
    bar = max(float(fight_bar(rows, cfg)["bar"]), float(_c(cfg, "r1g5_unfought_fight_ratio", 1.0)))
    if rows and all(_inside_near(s, cfg, t) for t in rows):
        f = float(_c(cfg, "r1x4_unfought_inside_factor", 0.5))
        return bar * f, f"{bar * f:g}x at least: inside among the civilians"
    return bar, f"{bar:g}x at least"


def _poor_odds(cfg: dict, ratio) -> bool:
    """(x4) A fight begun below about even odds (`fight_even_ratio`)."""
    return isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and \
        ratio < float(_c(cfg, "fight_even_ratio", 1.0))


def _keep(out: dict, s: dict, memory, cfg: dict, great: str, names: str, days: int, was: str) -> dict:
    """(x4) The long alarm kept instead of lifted: a great danger inside near
    the civilians. The shelter keeps them (g4's planner_shelter picks it away
    from the danger; planner_society._shelter_supply_rule refills it with the
    drink and food inside the fort); what it holds is said."""
    held = shelter_holds(s, memory, cfg)
    out.update(mode="keep", why=(f"{was}, but {great} is inside the fort near the dwarves: the alarm stays up after "
                                 f"{days} days (lifted, the civilians would go back to work beside it); the shelter "
                                 f"keeps them, away from it: {held}"))
    return out


def shelter_holds(s: dict, memory, cfg: dict) -> str:
    """(x4) What the civilians' shelter holds, in words: g4's levels and
    their drink and food (planner_shelter.shelter_supplies, _shortfalls),
    else the last fill's record (memory.shelter_supply, refilled each day
    while short by planner_society._shelter_supply_rule)."""
    try:
        from planner_shelter import plan_ready, shelter_levels_now, shelter_supplies, _needs, _shortfalls
        plan = plan_ready(s)
        levels = shelter_levels_now(s)
        sup = shelter_supplies(plan, levels) if plan and levels else None
        if isinstance(sup, dict):
            civs = int(_d(s.get("dwarves")).get("total") or 0)
            short = _shortfalls(int(sup.get("tiles") or 0), int(sup.get("drink") or 0), int(sup.get("wells") or 0),
                                int(sup.get("food") or 0), _needs(civs, cfg))
            where = "levels " + ", ".join(str(z) for z in levels)
            if short:
                return (f"{where} short of {'; '.join(str(x) for x in short)[:80]}: it is made again each day to "
                        "take in drink and food (the shelter rules), and moved where they are")
            return f"{where}, with drink and food for them"
    except Exception:  # noqa: BLE001
        pass
    rec = _d(getattr(memory, "shelter_supply", None)) if memory is not None else {}
    short = [str(rec[k]) for k in ("no_water", "drink_short", "no_food") if rec.get(k)]
    if rec.get("dry") and not short:
        short = ["no drink in it"]
    if short:
        return f"{'; '.join(short)[:80]} at its last fill: it is made again each day to take in drink and food"
    if rec:
        return "drink and food in it at its last fill (made again while the alarm stands)"
    return "it is filled with the drink and food inside the fort while the alarm stands"


def unfought(s: dict, memory, cfg: dict, ids: list) -> dict:
    """{mode, why, ids, ratio}: what the AI's long alarm for these enemies (in
    reach) does now. mode "" (nothing: too young, someone fights them, not
    the AI's alarm), "fight" (every armed squad goes), "lift" (the alarm
    comes down; the gates keep shutting on them)."""
    out = {"mode": "", "why": "", "ids": [], "ratio": 0.0}
    if memory is None or s.get("civ_alert") is not True or not getattr(memory, "ai_alert_raised", False):
        return out
    now, on = abs_tick(s), _alarm_on_tick(memory)
    if not _int(now) or on is None or now < on:
        return out
    rows_by = _rows(s)
    listed = [i for i in ids if i in rows_by]
    if not listed:
        return out
    rows = [rows_by[i] for i in listed]
    great = great_among_civilians(s, cfg, rows)          # (x4) never lifted for one of these
    age = now - on
    limit = int(float(_c(cfg, "r1g5_unfought_alarm_days", 30)) * TICKS_PER_DAY)
    hard = int(float(_c(cfg, "r1g5_alarm_hard_days", 60)) * TICKS_PER_DAY)
    days = age // TICKS_PER_DAY
    names = ", ".join(sorted({str(t.get("name") or "an enemy").split(",")[0][:40] for t in rows}))[:100]
    out["ids"] = listed
    rec = _rec(memory)
    squads = _squads(s)
    out_on = [q for q in squads if _on_them(q) and _kill(q) & set(listed)]
    if rec.get("on") == on and _int(rec.get("fought")):
        # the all-out fight this alarm: on while it goes well
        from planner_matchup import losses_turned
        from planner_holdfast import kill_start
        went = int(rec.get("soldiers") or 0)
        now_n = int(_d(s.get("military")).get("soldiers") or 0)
        lost = went and (went - now_n) * 3 >= went
        # (x4) begun below even odds: its first real losses end it (was: a third of the army)
        poor = _poor_odds(cfg, rec.get("ratio")) and went and \
            went - now_n >= int(_c(cfg, "r1x4_poor_odds_losses", 1))
        turned = losses_turned(out_on, kill_start(memory), cfg) if out_on else ""
        if lost or turned or poor:
            bad = (turned or f"{went - now_n} of {went} soldiers lost"
                   + (f", at {float(rec.get('ratio')):.2f}x" if poor and not lost else ""))
            if great:
                return _keep(out, s, memory, cfg, great, names, days, f"the all-out fight on {names} turned bad ({bad})")
            out.update(mode="lift", why=(f"{UNFOUGHT_WHY} {names} and won: the all-out fight turned bad ({bad}"
                                         f"); after {days} days the alarm comes down: the gates keep shutting on "
                                         "them, work resumes away from them (a new enemy sounds it again)"))
            return out
        if age >= hard and not out_on:
            if great:
                return _keep(out, s, memory, cfg, great, names, days, "the all-out attack has ended")
            out.update(mode="lift", why=(f"{UNFOUGHT_WHY} {names} for {days} days since the all-out attack "
                                         "ended: the alarm comes down (the gates keep shutting on them, work "
                                         "resumes away from them)"))
            return out
        out.update(mode="fight", why=f"the all-out attack on {names} goes on")
        return out
    if age >= hard:
        if great:
            return _keep(out, s, memory, cfg, great, names, days,
                         f"the alarm has stood {days} days for {names} ({_c(cfg, 'r1g5_alarm_hard_days', 60)} at most)")
        out.update(mode="lift", why=(f"the alarm has stood {days} days for {names} "
                                     f"({_c(cfg, 'r1g5_alarm_hard_days', 60)} at most): it comes down (the "
                                     "gates keep shutting on them, work resumes away from them)"))
        return out
    if out_on or age < limit:
        return out
    from planner_core import player_rules
    never = player_rules(s).get("attack_policy") == "never"
    mil = [] if never else _militia(s)
    ratio = _ratio(s, memory, rows, mil)
    out["ratio"] = ratio
    bar, bar_why = fight_bar_unfought(s, cfg, rows)
    if never:
        if great:
            return _keep(out, s, memory, cfg, great, names, days,
                         f"{UNFOUGHT_WHY} {names} in {days} days of alarm (Rules tab: never send squads)")
        out.update(mode="lift", why=(f"{UNFOUGHT_WHY} {names} in {days} days of alarm (Rules tab: never send "
                                     "squads): the alarm comes down so work resumes; the gates keep shutting on "
                                     "them, and it sounds again for a new enemy"))
    elif mil and ratio >= bar:
        out.update(mode="fight", why=(f"{UNFOUGHT_WHY} {names} in {days} days of alarm: every squad with anyone "
                                      f"armed goes (the call for the armed; {ratio:.2f}x, {bar_why})"))
    elif great:
        return _keep(out, s, memory, cfg, great, names, days,
                     f"{UNFOUGHT_WHY} {names} in {days} days of alarm and the squads can't beat it "
                     f"({ratio:.2f}x with every armed squad, {bar_why})")
    else:
        out.update(mode="lift", why=(f"{UNFOUGHT_WHY} {names} in {days} days of alarm and the squads can't beat "
                                     f"them ({ratio:.2f}x with every armed squad, {bar_why}): the alarm comes "
                                     "down so work resumes; the gates keep shutting on them, and it sounds "
                                     "again for a new enemy"))
    return out


def book_unfought(s: dict, memory, uf: dict) -> None:
    """The decision remembered (plan(), as _note_fight does): the all-out
    fight's start and the soldiers who went; a lift's enemies (the alarm not
    raised again for them)."""
    if memory is None or not uf.get("mode"):
        return
    rec = dict(_rec(memory))
    on, now = _alarm_on_tick(memory), abs_tick(s)
    if uf["mode"] == "fight" and not (rec.get("on") == on and _int(rec.get("fought"))):
        rec.update(on=on, fought=now, soldiers=int(_d(s.get("military")).get("soldiers") or 0),
                   ratio=round(float(uf.get("ratio") or 0.0), 3))       # (x4) poor odds: first losses end it
    elif uf["mode"] == "lift":
        rec["lifted"] = now
        rec["lifted_ids"] = sorted({i for i in list(_l(rec.get("lifted_ids"))) + list(uf.get("ids") or [])
                                    if _int(i)})[-50:]
    _set_rec(memory, rec)


def unfought_raise_held(s: dict, memory, cfg: dict, fresh: list) -> str:
    """Why the alarm isn't raised again for these enemies ("" if it may be):
    it was lifted for them after a fight nobody would or could fight."""
    rec = _rec(memory)
    lifted = {i for i in _l(rec.get("lifted_ids")) if _int(i)}
    want = [i for i in fresh if i is not None]
    if not lifted or not want or any(i not in lifted for i in want):
        return ""
    return (f"{len(want)} threat(s) can reach the dwarves: the alarm was lifted for them after "
            f"{_c(cfg, 'r1g5_unfought_alarm_days', 30)}+ days nobody fought them; it stays down (the gates "
            "keep shutting on them; a new enemy sounds it again)")


def note_war_hold(s: dict, memory, cfg: dict) -> None:
    """Bookkeeping (note_cycle): since when the drafting waits for arms
    (arm_first's limit); the lifted enemies forgotten once none of them is on
    the map; the all-out record once its alarm is over."""
    if memory is not None and isinstance(getattr(memory, "atlas", None), dict) and "military" in s:
        from planner_core import player_rules
        rules_ = dict(player_rules(s))
        af = _d(memory.atlas.get("arm_first"))
        if _rule_arm_first(s, cfg, rules_):
            if not _int(af.get("since")):
                memory.atlas["arm_first"] = {"since": abs_tick(s)}
        else:
            memory.atlas.pop("arm_first", None)
    rec = _rec(memory)
    if not rec:
        return
    rows = _rows(s)
    lifted = [i for i in _l(rec.get("lifted_ids")) if _int(i) and i in rows]
    rec = dict(rec)
    if lifted:
        rec["lifted_ids"] = lifted
    else:
        rec.pop("lifted_ids", None)
        rec.pop("lifted", None)
    on = _alarm_on_tick(memory)
    if rec.get("on") is not None and rec.get("on") != on:
        for k in ("on", "fought", "soldiers", "ratio"):
            rec.pop(k, None)
    _set_rec(memory, rec)


# --- the army held still while danger is about -------------------------------------------

def army_danger(s: dict, memory, cfg: dict) -> str:
    """Why the squads are left as they are ("" if not): an enemy can reach
    the dwarves or is inside, the AI's alarm is up, a berserk dwarf, or an
    enemy could reach them within `r1g5_army_hold_ticks` (reach flickers:
    B's axeman out of reach for one cycle in a minute of killing)."""
    try:
        if reachable_threats(s, _traits(s), cfg):
            return "enemies can reach the dwarves"
    except Exception:  # noqa: BLE001
        pass
    if [x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if _int(x)]:
        return "an enemy is inside the fort"
    th = _d(s.get("threats"))
    if any(isinstance(x, dict) and x.get("inside") for x in _l(_d(th.get("thieves")).get("list"))):
        return "a thief is inside the fort"
    if _l(_d(s.get("hazards")).get("berserk")):
        return "a dwarf is berserk"
    if s.get("civ_alert") is True and memory is not None and getattr(memory, "ai_alert_raised", False):
        return "the alarm is up"
    now = abs_tick(s)
    last = getattr(memory, "last_threat_tick", None) if memory is not None else None
    hold = int(_c(cfg, "r1g5_army_hold_ticks", 2 * TICKS_PER_DAY))
    if _int(now) and _int(last) and last and 0 <= now - last < hold:
        return f"an enemy could reach the dwarves {(now - last) // 50} game hour(s) ago"
    return ""


def _off(r) -> bool:
    return "off duty" in str(r or "").lower()


def war_hold_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """No squad trim, soldier swap, nor routine change that sends a squad off
    duty or turns one training into another, while army_danger holds. A squad
    off duty put on training (in uniform, armed) still goes."""
    proposals = _recall_filter(s, memory, cfg, proposals, notes)
    why = army_danger(s, memory, cfg)
    if not why:
        return proposals
    squads = {q["id"]: q for q in _squads(s)}
    out, dropped = [], []
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        t = a.get("type")
        drop = t in ("squad_trim", "squad_swap")
        if t == "squad_routine":
            cur = _d(squads.get(a.get("squad_id"))).get("routine")
            drop = _off(a.get("routine")) or not _off(cur)
        (dropped if drop else out).append(p)
    if dropped:
        notes.append(f"{why}: the squads are left as they are (" + "; ".join(
            sorted({p.reason[:60] for p in dropped}))[:200] + ")")
    return out


# --- arm before drafting or swapping -----------------------------------------------------

def armed_count(s: dict) -> int:
    """Soldiers with a weapon (melee in hand or given, plus crossbows)."""
    g = _d(_d(s.get("military")).get("gear"))
    armed = int(g.get("armed") or 0)
    if _int(g.get("melee_given")):
        armed = max(armed, int(g["melee_given"]) + int(g.get("ranged_armed") or 0))
    return armed


def _weapon_bars(s: dict) -> tuple[str, int]:
    bars = _d(_d(_d(s.get("military")).get("gear")).get("bars"))
    best = max(((m, int(bars.get(m) or 0)) for m in GEAR_METALS), key=lambda x: x[1], default=("", 0))
    return best


def _arm_base(s: dict, cfg: dict, rules_: dict) -> str:
    """The arming hold's own test (r1g5), without its limits: more than
    `r1g5_arm_first_unarmed` (and a quarter) of the soldiers on duty are
    unarmed, and the fort has a forge and the weapon-grade bars to arm them."""
    if not rules_.get("make_gear", True):
        return ""
    g = _d(_d(s.get("military")).get("gear"))
    if "error" in g or not g.get("forges"):
        return ""
    # judged on the soldiers on duty (off duty they put their weapons away;
    # the gear rule makes weapons for those on duty)
    duty = int(g.get("on_duty") or 0)
    armed = armed_count(s)
    unarmed = duty - armed
    if unarmed <= max(int(_c(cfg, "r1g5_arm_first_unarmed", 2)), duty * 0.25):
        return ""
    metal, n = _weapon_bars(s)
    per = int(_d(cfg.get("gear_bars")).get("weapons") or 1)
    if n < unarmed * per:
        return ""
    return (f"{armed} of the {duty} soldiers on duty armed and {n} {metal.lower()} bars in store: they are armed "
            "first (their weapons made or handed out) before more soldiers are drafted")


def _war_now(s: dict, memory, cfg: dict) -> str:
    """(x4) Why the fort needs numbers now ("" if not): an enemy can reach the
    dwarves or is inside, a great danger is on the map, or a siege
    (planner_holdfast's record). Unarmed soldiers still wrestle."""
    try:
        if reachable_threats(s, _traits(s), cfg):
            return "enemies can reach the dwarves"
    except Exception:  # noqa: BLE001
        pass
    if [x for x in _l(_d(s.get("entrances")).get("intruders_inside")) if _int(x)]:
        return "an enemy is inside the fort"
    try:
        from planner_core import great_present
        if great_present(s):
            return "a great danger is on the map"
    except Exception:  # noqa: BLE001
        pass
    try:
        from planner_matchup import siege_days
        if siege_days(s, memory) > 0:
            return "the fort is under siege"
    except Exception:  # noqa: BLE001
        pass
    return ""


WEAPON_RECIPES = frozenset(GEAR_WEAPONS.values())


def _cannot_make(s: dict, memory, cfg: dict, since) -> str:
    """(x4, V3) Why the weapons the hold waits for won't be made soon ("" if
    they can): no built forge (a forge stands only on its anvil), no charcoal
    or coke and no magma forge, no citizen who may forge weapons (the
    labour), or the AI's weapon orders stand still (a suspended job, nobody
    with the labour, `r1x4_arm_stall_days` unmoved), or the hold has waited
    `r1x4_arm_no_order_days` with no weapon order and none spare to hand out."""
    b = _d(s.get("buildings"))
    shops = {**_d(b.get("workshops")), **_d(b.get("furnaces"))} if b.get("workshops") is not None else None
    magma = int((shops or {}).get("MagmaForge") or 0)
    if shops is not None and int(shops.get("MetalsmithsForge") or 0) + magma <= 0:
        return "no forge is built (each stands on an anvil)"
    fuel = _d(s.get("supplies")).get("fuel")
    if magma <= 0 and _int(fuel) and fuel <= 0:
        return "no charcoal or coke for the forge, and no magma forge"
    holders = _d(_d(s.get("order_desk")).get("labor_holders")).get("FORGE_WEAPON")
    if _int(holders) and holders <= 0:
        return "no citizen may forge weapons (nobody has the weaponsmith's labour)"
    now = abs_tick(s)
    rows = [o for o in _l(s.get("orders")) if isinstance(o, dict) and o.get("by_ai")
            and str(o.get("recipe")) in WEAPON_RECIPES and int(o.get("amount_left") or 0) > 0]
    watch = _d(getattr(memory, "order_watch", None)) if memory is not None else {}
    stall = float(_c(cfg, "r1x4_arm_stall_days", 4)) * TICKS_PER_DAY
    stalled = []
    for o in rows:
        j = _d(o.get("jobs"))
        if int(j.get("working") or 0) > 0:
            continue
        w = _d(watch.get(str(o.get("id"))))
        from planner_core import watch_since
        still = (_int(now) and _int(w.get("since")) and now - watch_since(w) >= stall)
        if int(j.get("suspended") or 0) > 0 or (_int(j.get("holders")) and j["holders"] <= 0) or still:
            stalled.append(o)
    if rows and len(stalled) == len(rows):
        return f"the AI's {len(rows)} weapon order(s) stand still (no weapon made for days)"
    g = _d(_d(s.get("military")).get("gear"))
    spare = int(_d(g.get("spare")).get("weapons") or 0) + int(g.get("weapon_gaps_fillable") or 0)
    if (not rows and not spare and _int(since) and _int(now)
            and now - since >= float(_c(cfg, "r1x4_arm_no_order_days", 4)) * TICKS_PER_DAY):
        return "no weapon order of the AI's has gone in and none is spare to hand out"
    return ""


def arm_check(s: dict, cfg: dict, rules_: dict, memory=None) -> tuple[str, str]:
    """(held, lifted): why no more soldiers are drafted now, or why the
    arming hold that would stand is lifted (each "" if not). The hold
    (r1g5): weapons first, `r1g5_arm_first_max_days` at most (memory: since
    when, note_war_hold). (x4, V3) Only while those weapons can be made soon
    (_cannot_make), and never while the fort needs numbers (_war_now)."""
    base = _arm_base(s, cfg, rules_)
    if not base:
        return "", ""
    since = _d(_d(getattr(memory, "atlas", None)).get("arm_first")).get("since") if memory is not None else None
    now = abs_tick(s)
    if (_int(since) and _int(now)
            and now - since >= float(_c(cfg, "r1g5_arm_first_max_days", 56)) * TICKS_PER_DAY):
        return "", f"the soldiers have waited {(now - since) // TICKS_PER_DAY} days for weapons"
    war = _war_now(s, memory, cfg)
    if war:
        return "", f"{war}: the fort needs numbers (unarmed soldiers still wrestle)"
    cant = _cannot_make(s, memory, cfg, since)
    if cant:
        return "", f"the weapons can't be made soon: {cant}"
    return base, ""


def arm_first(s: dict, cfg: dict, rules_: dict, memory=None) -> str:
    """Why no more soldiers are drafted now ("" if they may be): arm_check's hold."""
    try:
        return arm_check(s, cfg, rules_, memory)[0]
    except Exception:  # noqa: BLE001   (never stops the drafting)
        return ""


def _rule_arm_first(s: dict, cfg: dict, rules_: dict) -> bool:
    """arm_first's own test without its limits (the clock since when runs on
    through a siege or a stall, so the 56 days are never begun again)."""
    return bool(_arm_base(s, cfg, rules_))


def swap_armed_short(s: dict, cfg: dict) -> bool:
    """Fewer than `r1g5_swap_armed_share` of the soldiers on duty armed."""
    g = _d(_d(s.get("military")).get("gear"))
    if not _int(g.get("on_duty")) or not _int(g.get("armed")):
        return False                    # an older bridge, or no gear count: as before
    duty = int(g["on_duty"])
    if duty <= 0:
        return False
    return armed_count(s) < duty * float(_c(cfg, "r1g5_swap_armed_share", 0.75))


# --- a sent squad held -------------------------------------------------------------------

def recall_hold(s: dict, memory, cfg: dict, q: dict, rows: list, ratio: float | None = None) -> str:
    """Why this squad's recall waits ("" if it doesn't): the AI sent it
    (memory.kill_sent_at) less than `kill_hold_ticks` ago, one of its targets
    is loose (rows), it is not losing (planner_matchup.losses_turned, from
    the members its order began with), and the odds against everything in
    reach are not hopeless (`r1g5_recall_hopeless_ratio`)."""
    if memory is None or not rows or not isinstance(q, dict):
        return ""
    from planner_holdfast import kill_start
    from planner_matchup import losses_turned
    since, now = _d(getattr(memory, "kill_sent_at", None)).get(str(q.get("id"))), abs_tick(s)
    if not _int(since) or not _int(now):
        return ""
    hold = int(_c(cfg, "kill_hold_ticks", TICKS_PER_DAY))
    if not 0 <= now - since < hold:
        return ""
    if losses_turned([q], kill_start(memory), cfg):
        return ""
    if ratio is None:
        all_rows = _rows(s)
        try:
            reach = [all_rows[i] for i in reachable_threats(s, _traits(s), cfg) if i in all_rows]
        except Exception:  # noqa: BLE001
            reach = []
        both = list({t.get("id", id(t)): t for t in list(rows) + reach}.values())
        ratio = _ratio(s, memory, both, [x for x in _squads(s) if _on_them(x) and _kill(x) & _kill(q)] or [q])
    if ratio < float(_c(cfg, "r1g5_recall_hopeless_ratio", 0.25)):
        return ""
    # (x4) at poor odds (below about even) the first real losses end the hold
    # (was: a third of the soldiers lost, the whole army spent on a titan)
    n0 = kill_start(memory).get(str(q.get("id")))
    if (_poor_odds(cfg, ratio) and _int(n0)
            and n0 - int(q.get("members") or 0) >= int(_c(cfg, "r1x4_poor_odds_losses", 1))):
        return ""
    return (f"sent {(now - since) // 50} game hour(s) ago and not losing ({ratio:.1f}x): held "
            f"{hold // 50} hours before the odds alone call it back")


RECALL_RULES = ("squad_recall", "shelter_squads")


def _recall_filter(s: dict, memory, cfg: dict, proposals: list, notes: list) -> list:
    """A recall (squad_recall, or the hiding rule's shelter_squads) of a squad
    whose kill order is young, its target loose, not losing and not hopeless
    (recall_hold) waits: C's five squads called back 12 s after being sent.
    A fight called off for its losses always comes back."""
    if memory is None:
        return proposals
    from planner_military import called_off_ids
    squads = {q["id"]: q for q in _squads(s)}
    rows = _rows(s)
    off = called_off_ids(s, memory)
    held: dict = {}

    def hold_of(sid):
        if sid not in held:
            q = squads.get(sid)
            kill = _kill(q) if q else set()
            held[sid] = ("" if not q or not q.get("ai_orders") or kill & off
                         else recall_hold(s, memory, cfg, q, [rows[i] for i in kill if i in rows]))
        return held[sid]
    out = []
    for p in proposals:
        a = p.action if isinstance(p.action, dict) else {}
        if p.rule in RECALL_RULES and a.get("type") == "squad_orders" and a.get("clear"):
            why = hold_of(a.get("squad_id"))
            if why:
                notes.append(f"{_d(squads.get(a.get('squad_id'))).get('name') or 'a squad'} keeps its kill order: "
                             f"{why} ({p.reason[:60]})")
                continue
        elif p.rule in RECALL_RULES and a.get("type") == "shelter_squads" and isinstance(a.get("squads"), list):
            keep = [i for i in a["squads"] if not hold_of(i)]
            if len(keep) < len(a["squads"]):
                gone = [i for i in a["squads"] if i not in keep]
                notes.append(f"{len(gone)} squad(s) keep their kill orders: {hold_of(gone[0])} ({p.reason[:60]})")
                if not keep:
                    continue
                p = dataclasses.replace(p, action=dict(a, squads=keep))
        out.append(p)
    return out


def unfought_targets(s: dict, uf: dict) -> tuple[list, list]:
    """(proposals' squads, ids): for the all-out fight, the armed squads not yet on them."""
    rows = _rows(s)
    ids = [i for i in uf.get("ids") or [] if i in rows]
    sends = []
    for q in _militia(s):
        if _on_them(q) and _kill(q) & set(ids):
            continue
        mine = [i for i in ids if _can_go(q, rows[i])]
        if mine:
            sends.append((q, mine))
    return sends, ids


def unfought_proposals(s: dict, uf: dict) -> list:
    sends, _ids = unfought_targets(s, uf)
    return [Proposal("squad_attack", {"type": "squad_orders", "squad_id": q["id"], "kill": mine[:50]},
                     f"{uf.get('why') or 'the all-out attack'}: send {q.get('name') or 'the squad'}", 0)
            for q, mine in sends]
