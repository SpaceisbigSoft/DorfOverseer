"""(r5 p3) Repeated refusals backed off.

The general back-off (planner_core.note_refusal / _refused_wait) doubles the
wait of a refused action, but its record is forgotten two months after the
last refusal (and begins again at a day). A rule that meets the same "no"
every season starts afresh each time: B (run of 15-16 Nov) asked place_well
92 times in 13 years ("no open drop from a free floor inside the fort to
clean water; ... freezes in winter"), 7 a year, each autumn from one day; C's
well 54; E's farm_plots 38+ ("no free soil ... no safe spot for a farm
level").

This is a second, longer memory (Memory.refusal_streaks): the same rule and
action key (planner_core.refusal_key) refused with the same reason (numbers
aside) `r5p3_refusal_streak` times in a row waits 1 game day, then 2, 4 ...
up to `r5p3_refusal_wait_max_days`. The streak is kept a year
(`r5p3_refusal_forget_days`) after its last refusal, not two months. It is
reset when:
  * the action is accepted once (ok true);
  * the reason text changes (numbers aside);
  * the state the refusal depends on changes (signature): the bridge's
    version, the levels finished ever, and for water steps the wells built,
    for farm steps the farm plots.
The wait is said once in the notes when it begins (plan() reads the flag,
select() clears it), not every cycle.

Never held: the responses to danger (EMERGENCY, the rules that pace their
own tries), defence steps (the alarm, gates, squads: hold_classes), the
steps that only let go, the transient survival steps below (thirst, the
stranded, a way in or out, a well's rescue, lid or parts), and in a crisis
or an urgent step the drink and water rules.
"""

from __future__ import annotations

import re

import hold_classes as _hc
from digest import _d
from planner_core import EMERGENCY, OWN_PACE, TICKS_PER_DAY, is_release, levels_done, refusal_key

# survival steps whose refusal is transient: never held by a streak
TRANSIENT_RULES = {
    "thirst", "drink_fruit", "water_traffic", "well_rescue", "well_lid", "well_parts", "well_shaft",
    "well_safety", "cistern_shut", "waterworks_shut", "magma_shut", "lure_shut", "stranded", "way_in",
    "way_out", "way_out_dig", "hospital", "hospital_burrow", "hospital_guard", "doctor_patient", "doctor_post",
    "rescue_labor", "infected_rest", "traction_rest", "insane", "break_fights", "fight_watch", "calm_burrow", "jail_urgent",
    "mood", "mood_shelter", "cave_in_dig_out", "prisoners_water", "tavern_urgent",
}
TRANSIENT_ACTIONS = {
    "civ_alert", "thirst_unforbid", "thirst_way", "thirst_patient", "thirst_probe", "open_entrance",
    "dig_way_in", "way_out_open", "way_out_leave", "well_rescue", "well_safety", "well_shaft",
    "hospital_burrow", "calm_burrow", "break_fights", "fight_watch", "insane_guard", "mood_free_items", "mood_shelter",
    "hospital_release",   # (item2) a mood's thread; the hospital's quotas put back
    "unpause", "save_game", "report_status", "save_memory", "dismiss_alerts",
}
# drink and water: never held in a crisis (or on an urgent step)
WATER_RULES = {
    "well", "well_dig", "water", "water_zone", "frost_water_zone", "frost_well", "ice_shore_well", "ice_zones",
    "ice_traffic", "winter_water", "cistern", "cistern_parts", "drink", "booze_variety", "seed_brew", "kitchen",
    "waterworks_check",
}
WATER_ACTIONS = {"place_well", "water_zone", "restrict_water", "renew_well_dig", "survey_water", "cistern_step",
                 "kitchen_brewables", "retire_water_zones"}
FARM_ACTIONS = {"farm_plots", "set_farm_crops", "farm_thresholds"}
WHY_MAX = 100          # characters of the reason kept (and compared)


def _on(cfg) -> bool:
    return bool(_d(cfg).get("r5p3_refusal_backoff", True))


def _why(r: dict) -> str:
    """The reason, numbers aside ("4 buildings still waiting" is the same no as "5 ...")."""
    return re.sub(r"\d+", "#", str(_d(r).get("error") or "").strip())[:WHY_MAX]


def _water(p) -> bool:
    a = _d(getattr(p, "action", None))
    return p.rule in WATER_RULES or a.get("type") in WATER_ACTIONS or (
        a.get("type") == "start_project" and a.get("kind") == "well")


def _farm(p) -> bool:
    a = _d(getattr(p, "action", None))
    return a.get("type") in FARM_ACTIONS or (a.get("type") == "start_project" and a.get("kind") == "farms")


def signature(p, state: dict) -> dict:
    """What the refusal depends on: when any of it changes, the streak ends."""
    s = _d(state)
    sig = {"v": s.get("bridge_version"), "levels": levels_done(s)}
    b = _d(s.get("buildings"))
    if _water(p):
        sig["wells"] = _d(b.get("other")).get("Well", 0)
    if _farm(p):
        f = _d(s.get("farms"))
        sig["plots"] = f.get("plots") if isinstance(f.get("plots"), int) else len(f.get("plot_list") or [])
    return sig


def exempt(p, memory=None, state=None) -> bool:
    """A step never held by a refusal streak (see the module's text). The
    streak is still counted for it (it may stop being exempt)."""
    a = _d(getattr(p, "action", None))
    rule = getattr(p, "rule", None)
    if rule in EMERGENCY or a.get("type") in OWN_PACE or is_release(a):
        return True
    if rule in TRANSIENT_RULES or a.get("type") in TRANSIENT_ACTIONS:
        return True
    try:
        if _hc.step_class(p) == _hc.DEFENCE:
            return True
    except Exception:  # noqa: BLE001  (unclassable: never held by mistake)
        return True
    crisis = bool(_d(getattr(memory, "crisis", None)).get("why")) if memory is not None else False
    if _water(p) and (crisis or a.get("urgent")):
        return True
    # (r5 Z3) an urgent survival step (a hospital in a crisis, a Still for the thirsty, the ghosts'
    # tombs) is never held: its refusal may clear any day
    try:
        if a.get("urgent") and _hc.step_class(p) == _hc.SURVIVAL and (crisis or getattr(p, "rule", None) == "bottleneck"):
            return True
    except Exception:  # noqa: BLE001
        return True
    return False


def _book(memory) -> dict:
    if not isinstance(getattr(memory, "refusal_streaks", None), dict):
        memory.refusal_streaks = {}
    return memory.refusal_streaks


def note(memory, p, r: dict, state: dict, now: int, cfg: dict, brief: bool = False) -> None:
    """A step answered (record()): a refusal lengthens its streak (or starts a
    new one), an acceptance ends it. Unknown answers, the in-game halt, work
    under way and a search cut short (to be tried again soon) leave it."""
    if not _on(cfg) or memory is None:
        return
    r = _d(r)
    a = _d(getattr(p, "action", None))
    if a.get("dry_run"):
        return
    book = _book(memory)
    key = refusal_key(p)
    if r.get("ok") is True:
        book.pop(key, None)
        return
    if r.get("ok") is not False or r.get("halted") or r.get("waiting") or brief:
        return
    if p.rule in EMERGENCY or a.get("type") in OWN_PACE:
        return
    why, sig = _why(r), signature(p, state)
    old = _d(book.get(key))
    n = int(old.get("n") or 0) + 1 if old.get("why") == why and old.get("sig") == sig else 1
    first = max(1, int(cfg.get("r5p3_refusal_first_days", 1) or 1))
    cap = max(first, int(cfg.get("r5p3_refusal_wait_max_days", 28) or 28))
    streak = max(1, int(cfg.get("r5p3_refusal_streak", 3) or 3))
    rec = {"n": n, "why": why, "sig": sig, "at": now, "rule": p.rule, "type": a.get("type")}
    if n >= streak:
        days = min(cap, first * 2 ** (n - streak))
        rec["until"] = now + days * TICKS_PER_DAY
        rec["days"] = days
        if n == streak:
            rec["say"] = True      # said once a streak: when its wait first begins
    book[key] = rec
    _prune(book, now, cfg)


def _prune(book: dict, now: int, cfg: dict) -> None:
    forget = int(cfg.get("r5p3_refusal_forget_days", 336) or 336) * TICKS_PER_DAY
    for k in [k for k, v in book.items()
              if not isinstance(v, dict) or not isinstance(v.get("at"), int) or not 0 <= now - v["at"] <= forget]:
        book.pop(k, None)
    most = max(1, int(cfg.get("r5p3_refusal_keep", 60) or 60))
    if len(book) > most:     # the working memory stays small: the oldest go first
        streak = max(1, int(cfg.get("r5p3_refusal_streak", 3) or 3))
        # (r5 merge) one-off refusals go first, the oldest of them first: a real streak is what is kept
        for k in sorted(book, key=lambda k: (int(book[k].get("n") or 0) >= streak, book[k]["at"]))[:len(book) - most]:
            book.pop(k, None)


def wait(memory, p, state: dict, now: int, cfg: dict):
    """(days left, record) while the step's streak holds it, else None. The
    streak no longer holds once what the refusal depends on has changed."""
    if not _on(cfg) or memory is None or exempt(p, memory, state):
        return None
    rec = _d(_d(getattr(memory, "refusal_streaks", None)).get(refusal_key(p)))
    until = rec.get("until")
    if not isinstance(until, int) or not 0 <= now < until:
        return None
    cap = max(1, int(cfg.get("r5p3_refusal_wait_max_days", 28) or 28)) * TICKS_PER_DAY
    if until - now > cap or (isinstance(rec.get("at"), int) and rec["at"] > now):
        return None      # (r5 Z4) the game's time went back (an older save): the wait no longer holds
    if rec.get("sig") != signature(p, state):
        return None
    return max(1, -(-(until - now) // TICKS_PER_DAY)), rec


def held_line(p, days: int, rec: dict) -> str:
    return (f"{p.rule}: refused {rec.get('n')} times in a row for the same reason "
            f"({str(rec.get('why') or '')[:80]}); asks again in {days} day(s), sooner if the fort changes")


def notes(memory, cfg: dict) -> list[str]:
    """The waits begun since the last cycle, each said once (select() clears the flag)."""
    if not _on(cfg) or memory is None:
        return []
    out = []
    for k, v in sorted(_d(getattr(memory, "refusal_streaks", None)).items()):
        if isinstance(v, dict) and v.get("say"):
            out.append(f"{v.get('rule')}: {str(v.get('type') or 'its step').replace('_', ' ')} refused "
                       f"{v.get('n')} times in a row for the same reason ({str(v.get('why') or '')[:80]}): "
                       f"asked again in {v.get('days')} day(s), twice as long after each refusal (at most "
                       f"{cfg.get('r5p3_refusal_wait_max_days', 28)}), at once when the fort changes "
                       "(a new level or well, another reason)")
    return out


def said(memory) -> None:
    """The notes of this cycle's new waits were made: not again."""
    for v in _d(getattr(memory, "refusal_streaks", None)).values():
        if isinstance(v, dict) and v.get("say"):
            v["say"] = False
