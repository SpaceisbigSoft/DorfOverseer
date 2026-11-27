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

(0.105.112 item7) D2, live 24 Nov (12 h): B staff 91 ("nobody free"),
homes_liked 44, care_feed 33, unload_depot 228; E chronic_convict 41, mood 48;
A squad_fill 86, food_store 32. The streaks were begun again almost every
time: the signature held the levels finished ever, which moves every few game
days in a fort of 150+ levels, though a post, a labour or a trial has nothing
to do with a new level; an answer to wait was never counted; the squads (the
defence class) were never held even in peace. Now:
  * the levels are in the signature only for a step that looks for room
    (water, farms, a level, a place, a pile, a room: SPACE_*);
  * an answer to wait counts too (same reason, numbers aside), its wait at
    most `r112_wait_answer_max_days` (the game is already at it);
  * a defence step is held only in peace (no reachable threat, quiet for
    `alert_quiet_cycles` cycles, no great danger) and at most
    `r112_defence_wait_max_days`; the critical ones (CRITICAL_*: the alarm,
    gates, the shelter, killers, fights) never;
  * a few safety steps that were held up to 28 days keep a short cap
    (SHORT_CAP_*: `r112_short_cap_days`, half a day): a mood's help, a tantrum's
    care, the jail, the magma guard;
  * a hospital post asked while patients wait for care ("nobody free") at
    most a game day (`r112_care_post_max_days`).
Never held at all (as before, and listed): EMERGENCY, OWN_PACE, releases,
TRANSIENT_* (thirst, the stranded, ways in and out, wells' rescue, fights,
the insane, the mood's own rule ...), drink and water in a crisis, urgent
survival steps in a crisis, CRITICAL_* defence, any defence step in danger.

(0.105.115 item20) Live 25 Nov (2.5 h, 0.105.114): E staff 217 ("nobody free":
the doctor's post, once a game day while patients waited, a day being 15-25 s
there), A squad_fill 145, C build 35 and F 35 ("no safe level found within
the time limit (z40: kept for ...; z11: cavern ...)": three lists, three
reasons), E appoint 23. Now:
  * the reason is compared without what is in brackets as well as numbers
    (the counts and lists the bridge adds: "kept out: 2 a post, 1 very
    unhappy" or "1 breaking down" is the same no);
  * a few fort-wide reasons are a family across the rule's actions
    (FAMILIES: "nobody free to take the post" for any post, "no suitable
    dwarves" for any squad, "nobody fits to lead a squad" for any office): a
    family's streak holds each of them, and a success of any ends it;
  * the short caps (a care post, an answer to wait, a defence step in peace)
    are the longer of their game days and planner_backoff.REAL_CAP_MINUTES
    real minutes at the fort's fps (state perf.fps), so a fast fort isn't
    asked every few seconds; the safety steps (SHORT_CAP_*) keep game time.

Never held: the responses to danger (EMERGENCY, the rules that pace their
own tries), defence steps (the alarm, gates, squads: hold_classes), the
steps that only let go, the transient survival steps below (thirst, the
stranded, a way in or out, a well's rescue, lid or parts), and in a crisis
or an urgent step the drink and water rules.
"""

from __future__ import annotations

import re

import hold_classes as _hc
import planner_attempts as _att
from digest import _d
from planner_config import PLANNER_CONFIG
from planner_core import EMERGENCY, OWN_PACE, TICKS_PER_DAY, is_release, levels_done, refusal_key
from planner_core_threats import great_present
from planner_backoff import care_post, real_ticks, REAL_CAP_MINUTES

# survival steps whose refusal is transient: never held by a streak
TRANSIENT_RULES = {
    "thirst", "drink_fruit", "water_traffic", "well_rescue", "well_lid", "well_parts", "well_shaft",
    "well_safety", "cistern_shut", "waterworks_shut", "magma_shut", "lure_shut", "stranded", "way_in",
    "way_out", "way_out_dig", "hospital", "hospital_burrow", "hospital_guard", "doctor_patient", "doctor_post",
    "rescue_labor", "infected_rest", "traction_rest", "insane", "insane_water", "break_fights", "fight_watch", "calm_burrow", "jail_urgent",
    "mood", "mood_shelter", "cave_in_dig_out", "prisoners_water", "tavern_urgent",
}
TRANSIENT_ACTIONS = {
    "civ_alert", "thirst_unforbid", "thirst_way", "thirst_patient", "thirst_probe", "open_entrance",
    "dig_way_in", "way_out_open", "way_out_leave", "well_rescue", "well_safety", "well_shaft",
    "hospital_burrow", "calm_burrow", "break_fights", "fight_watch", "insane_guard", "insane_water", "mood_free_items", "mood_shelter",
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

# (item7) the critical defence: never held by a streak, in peace either
CRITICAL_RULES = {
    "threat_alert", "alerts", "gate", "gates", "gate_guard", "gate_doors", "gate_lever", "gate_parts",
    "gate_jobs", "gate_stuck", "gate_dogs", "entrances", "destroyer_gate", "seal_cavern", "cavern_openings",
    "shelter", "shelter_flee", "shelter_pick", "shelter_refresh", "shelter_squads", "shelter_supply",
    "squad_attack", "squad_recall", "archer_post", "caravan_guard", "near_gates", "near_gates_refresh",
    "killer", "cursed", "reanimation", "flood", "fire_guard", "intruder_guard", "thief_watch",
    "break_fights", "fight_watch", "calm_burrow", "insane", "insane_water", "thirst", "moon_cell",
}
CRITICAL_PREFIXES = ("thirst", "fight", "killer", "shelter", "gate", "alarm", "alert")
# (item7) safety steps that may wait, but never long: at most r112_short_cap_days
SHORT_CAP_RULES = {"mood_hospital", "mood_reserve", "mood_help", "mood_free", "staff_tantrum", "tantrum_soldier",
                   "tantrum_care", "jail_more", "jail_size", "jail_urgent", "magma_guard", "hospital_guard"}
SHORT_CAP_PREFIXES = ("mood", "tantrum", "thirst", "killer", "fight", "shelter", "gate", "alarm")
# (item7) steps whose refusal may end with a new level (room, floor, soil): the levels finished
# ever are in their signature; for the rest (a post, a labour, a trial, a squad) they are not
SPACE_TYPES = {"start_project", "food_pile", "make_pasture", "farm_plots", "house_dwarves", "give_room",
               "dig_stairwell", "deep_depot", "cistern_step", "make_pit"}
SPACE_PREFIXES = ("place_", "dig", "build", "make_zone", "zone_")
SPACE_WORDS = re.compile(r"\b(room|rooms|floor|spot|tile|tiles|space|soil|level|levels|dig|"
                         r"drop|wall|stockpile|pile|zone)\b", re.I)
# (item7) the shorter caps, game days (a cfg key of the same name overrides; kept out of
# PLANNER_CONFIG, whose keys are pinned by test_r7_d6)
WAIT_ANSWER_MAX_DAYS = 7      # r112_wait_answer_max_days: an answer to wait (work under way), the same again
DEFENCE_MAX_DAYS = 7          # r112_defence_wait_max_days: a defence step (squads, kit), held only in peace
SHORT_CAP_DAYS = 0.5          # r112_short_cap_days: the safety steps that may wait (SHORT_CAP_*)
CARE_POST_DAYS = 1            # r112_care_post_max_days: a hospital post while patients wait ("nobody free")


def _on(cfg) -> bool:
    return bool(_c(cfg, "r5p3_refusal_backoff"))


# (F2b) kept local: a key set to None in cfg falls back to the default (unlike util's)
def _c(cfg, key):
    """(F2b) A r5p3 key from cfg, its default PLANNER_CONFIG's (one place:
    r5p3_refusal_keep was 60 here and 30 there)."""
    v = _d(cfg).get(key)
    return PLANNER_CONFIG[key] if v is None else v


def _ci(cfg, key) -> int:
    try:
        return max(1, int(_c(cfg, key) or PLANNER_CONFIG[key]))
    except (TypeError, ValueError):
        return max(1, int(PLANNER_CONFIG[key]))


_BRACKETS = re.compile(r"\s*\([^()]*\)")


def norm_why(text) -> str:
    """(item20) A reason without its numbers and without what is in brackets
    (the bridge's counts and lists: "no safe level found within the time limit
    (z40: kept for the main hall ...)" is one no whatever the list)."""
    t = str(text or "").strip()
    for _ in range(4):                       # nested brackets, from the inside out
        u = _BRACKETS.sub("", t)
        if u == t:
            break
        t = u
    t = re.sub(r"\d+", "#", t)
    return re.sub(r"\s+", " ", t).strip()[:WHY_MAX]


def _why(r: dict) -> str:
    """The reason, numbers aside ("4 buildings still waiting" is the same no as "5 ..."),
    (item20) and what is in brackets."""
    return norm_why(_d(r).get("error"))


# (item20) fort-wide reasons: one streak for all the rule's actions (any post, squad or office),
# beside each action's own. The pattern is matched against the normalised reason.
FAMILIES = {
    "staff": re.compile(r"^nobody free to take the post"),
    "squad_fill": re.compile(r"^no suitable dwarves could be added"),
    "appoint": re.compile(r"^nobody fits to lead a squad"),
}


def family_key(rule) -> str:
    return f"{rule}:*family"


def _family(p, why: str) -> bool:
    pat = FAMILIES.get(getattr(p, "rule", None))
    return bool(pat and pat.match(str(why or "")))


def _water(p) -> bool:
    a = _d(getattr(p, "action", None))
    return p.rule in WATER_RULES or a.get("type") in WATER_ACTIONS or (
        a.get("type") == "start_project" and a.get("kind") == "well")


def _farm(p) -> bool:
    a = _d(getattr(p, "action", None))
    return a.get("type") in FARM_ACTIONS or (a.get("type") == "start_project" and a.get("kind") == "farms")


def spatial(p, why: str = "") -> bool:
    """(item7) A step whose refusal a new level may end (room, floor, soil):
    water, farms, a level, a place, a pile, a room, or a reason about room."""
    a = _d(getattr(p, "action", None))
    t = str(a.get("type") or "")
    return (_water(p) or _farm(p) or t in SPACE_TYPES or t.startswith(SPACE_PREFIXES)
            or bool(SPACE_WORDS.search(str(why or ""))))


def signature(p, state: dict, why: str = "") -> dict:
    """What the refusal depends on: when any of it changes, the streak ends.
    (item7) The levels finished ever only for a step that looks for room."""
    s = _d(state)
    sig = {"v": s.get("bridge_version")}
    if spatial(p, why):
        sig["levels"] = levels_done(s)
    b = _d(s.get("buildings"))
    if _water(p):
        sig["wells"] = _d(b.get("other")).get("Well", 0)
    if _farm(p):
        f = _d(s.get("farms"))
        sig["plots"] = f.get("plots") if isinstance(f.get("plots"), int) else len(f.get("plot_list") or [])
    return sig


def _prefixed(rule, names: set, prefixes: tuple) -> bool:
    rule = str(rule or "")
    return rule in names or rule.startswith(prefixes)


def critical(p) -> bool:
    """(item7) The critical defence and safety (CRITICAL_*): never held."""
    return _prefixed(getattr(p, "rule", None), CRITICAL_RULES, CRITICAL_PREFIXES)


def danger(memory, state, cfg=None) -> bool:
    """(item7) Danger about: no defence step is held then. A threat that can
    reach the dwarves lately (not yet quiet for alert_quiet_cycles cycles), a
    great danger, the fort's own alarm up, or no memory to tell."""
    if memory is None:
        return True
    try:
        quiet = int(_d(cfg).get("alert_quiet_cycles", 3) or 3)
        if int(getattr(memory, "quiet_cycles", 0) or 0) < quiet:
            return True
        if great_present(_d(state)) or getattr(memory, "ai_alert_raised", False):
            return True
    except Exception:  # noqa: BLE001  (unknown: as danger, never held by mistake)
        return True
    return False


def cap_ticks(p, r_or_rec: dict, cfg: dict, state=None) -> int:
    """(item7) The longest wait of this step's streak, in ticks: half a day for
    the SHORT_CAP_* safety steps, a day for a hospital post while patients wait,
    r112_defence_wait_max_days for a defence step (in peace), at most
    r112_wait_answer_max_days for an answer to wait, else r5p3_refusal_wait_max_days."""
    cfg = _d(cfg)
    first = _ci(cfg, "r5p3_refusal_first_days")
    most = float(max(first, _ci(cfg, "r5p3_refusal_wait_max_days")))
    days = most
    if _d(r_or_rec).get("waiting"):
        days = min(days, float(cfg.get("r112_wait_answer_max_days", WAIT_ANSWER_MAX_DAYS) or WAIT_ANSWER_MAX_DAYS))
    try:
        if _hc.step_class(p) == _hc.DEFENCE:
            days = min(days, float(cfg.get("r112_defence_wait_max_days", DEFENCE_MAX_DAYS) or DEFENCE_MAX_DAYS))
    except Exception:  # noqa: BLE001
        pass
    if care_post(p):
        days = min(days, float(cfg.get("r112_care_post_max_days", CARE_POST_DAYS) or CARE_POST_DAYS))
    ticks = max(1, int(days * TICKS_PER_DAY))
    if _prefixed(getattr(p, "rule", None), SHORT_CAP_RULES, SHORT_CAP_PREFIXES):
        # the safety steps keep game time (a mood or a tantrum runs in game days)
        days = min(days, float(cfg.get("r112_short_cap_days", SHORT_CAP_DAYS) or SHORT_CAP_DAYS))
        return max(1, int(days * TICKS_PER_DAY))
    if days < most:
        # (item20) a short cap: or REAL_CAP_MINUTES real minutes, where that is longer (a fast
        # fort), never past the streak's own longest wait
        real = real_ticks(state, float(cfg.get("r115_real_cap_minutes", REAL_CAP_MINUTES) or REAL_CAP_MINUTES))
        ticks = max(ticks, min(real, int(most * TICKS_PER_DAY)))
    return ticks


def exempt(p, memory=None, state=None, cfg=None) -> bool:
    """A step never held by a refusal streak (see the module's text). The
    streak is still counted for it (it may stop being exempt)."""
    a = _d(getattr(p, "action", None))
    rule = getattr(p, "rule", None)
    if rule in EMERGENCY or a.get("type") in OWN_PACE or is_release(a):
        return True
    if rule in TRANSIENT_RULES or a.get("type") in TRANSIENT_ACTIONS:
        return True
    try:
        if _hc.step_class(p) == _hc.DEFENCE and (critical(p) or danger(memory, state, cfg)):
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
    new one), an acceptance ends it. Unknown answers, the in-game halt and a
    search cut short (to be tried again soon) leave it. (item7) An answer to
    wait (work under way) counts too, its wait shorter (cap_ticks)."""
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
        if p.rule in FAMILIES:
            book.pop(family_key(p.rule), None)     # (item20) one taken: the fort-wide no is over
        return
    if r.get("ok") is not False or r.get("halted") or brief:
        return
    if p.rule in EMERGENCY or a.get("type") in OWN_PACE:
        return
    waiting = bool(r.get("waiting"))
    why = ("wait: " if waiting else "") + _why(r)
    why = why[:WHY_MAX]
    sig = signature(p, state, why)
    keys = [key] + ([family_key(p.rule)] if not waiting and _family(p, why) else [])
    for k in keys:
        _count(book, k, p, a, why, sig, waiting, state, now, cfg, family=k != key)
    _prune(book, now, cfg)


def _count(book, key, p, a, why, sig, waiting, state, now, cfg, family=False) -> None:
    """One record of the streak lengthened (or begun again): the action's own,
    or (item20) its rule's family's."""
    old = _d(book.get(key))
    n = int(old.get("n") or 0) + 1 if old.get("why") == why and old.get("sig") == sig else 1
    first = _ci(cfg, "r5p3_refusal_first_days")
    streak = _ci(cfg, "r5p3_refusal_streak")
    rec = {"n": n, "why": why, "sig": sig, "at": now, "rule": p.rule, "type": a.get("type")}
    if waiting:
        rec["waiting"] = True
    if family:
        rec["family"] = True
    if n >= streak:
        cap = cap_ticks(p, rec, cfg, state)
        ticks = min(cap, first * 2 ** min(n - streak, 20) * TICKS_PER_DAY)
        rec["until"] = now + ticks
        rec["days"] = int(ticks // TICKS_PER_DAY) if ticks % TICKS_PER_DAY == 0 else round(ticks / TICKS_PER_DAY, 2)
        if n == streak and not (family and _d(book.get(refusal_key(p))).get("say")):
            rec["say"] = True      # said once a streak: when its wait first begins
    book[key] = rec


def _prune(book: dict, now: int, cfg: dict) -> None:
    forget = _ci(cfg, "r5p3_refusal_forget_days") * TICKS_PER_DAY
    for k in [k for k, v in book.items()
              if not isinstance(v, dict) or not isinstance(v.get("at"), int) or not 0 <= now - v["at"] <= forget]:
        book.pop(k, None)
    most = _ci(cfg, "r5p3_refusal_keep")
    if len(book) > most:     # the working memory stays small: the oldest go first
        streak = _ci(cfg, "r5p3_refusal_streak")
        # (r5 merge) one-off refusals go first, the oldest of them first: a real streak is what is kept
        for k in sorted(book, key=lambda k: (int(book[k].get("n") or 0) >= streak, book[k]["at"]))[:len(book) - most]:
            book.pop(k, None)


def wait(memory, p, state: dict, now: int, cfg: dict):
    """(days left, record) while the step's streak holds it, else None. The
    streak no longer holds once what the refusal depends on has changed."""
    if memory is None or exempt(p, memory, state, cfg):
        return None
    best = None
    if _on(cfg):
        book = _d(getattr(memory, "refusal_streaks", None))
        for k in (refusal_key(p),) + ((family_key(p.rule),) if p.rule in FAMILIES else ()):
            got = _wait_one(_d(book.get(k)), p, state, now, cfg)
            if got is not None and (best is None or got[0] > best[0]):
                best = got
    if best is None:
        best = _ledger_wait(memory, p, state, now, cfg)
    return best


def _ledger_wait(memory, p, state, now: int, cfg):
    """(F2b) The attempt ledger's hold (planner_attempts), within this step's
    short cap where it has one (a defence step in peace, a care post, a safety
    step: cap_ticks), as the streak's own."""
    try:
        got = _att.ledger_wait(memory, p, state, now, cfg)
        if got is None:
            return None
        rec = got[1]
        cap = cap_ticks(p, rec, cfg, state)
        if cap < _ci(cfg, "r5p3_refusal_wait_max_days") * TICKS_PER_DAY:
            until = min(rec["u"], rec["at"] + cap)
            if now >= until:
                return None
            return max(1, -(-(until - now) // TICKS_PER_DAY)), dict(rec, ledger=True)
        return got[0], dict(rec, ledger=True)
    except Exception:  # noqa: BLE001  (the ledger unreadable: not held by it)
        return None


def _wait_one(rec: dict, p, state, now: int, cfg: dict):
    until = rec.get("until")
    if not isinstance(until, int) or not 0 <= now < until:
        return None
    if rec.get("family") and not _family(p, rec.get("why")):
        return None
    cap = _ci(cfg, "r5p3_refusal_wait_max_days") * TICKS_PER_DAY
    if until - now > cap or (isinstance(rec.get("at"), int) and rec["at"] > now):
        return None      # (r5 Z4) the game's time went back (an older save): the wait no longer holds
    if isinstance(rec.get("at"), int):
        # (item7) the step's cap as it is now (a hospital post once patients wait, a short-cap step)
        until = min(until, rec["at"] + cap_ticks(p, rec, cfg, state))
        if now >= until:
            return None
    if rec.get("sig") != signature(p, state, str(rec.get("why") or "")):
        return None
    return max(1, -(-(until - now) // TICKS_PER_DAY)), rec


def held_line(p, days: int, rec: dict) -> str:
    if _d(rec).get("ledger"):
        return _att.ledger_held_line(p, days, rec)
    return (f"{p.rule}: refused {rec.get('n')} times in a row for the same reason "
            f"({str(rec.get('why') or '')[:80]}); asks again in {days} day(s), sooner if the fort changes")


def notes(memory, cfg: dict) -> list[str]:
    """The waits begun since the last cycle, each said once (select() clears the flag)."""
    if memory is None:
        return []
    out = []
    try:
        out += _att.ledger_notes(memory)          # (F2b) "held: <action> at <target>: <reason> x3", once
    except Exception:  # noqa: BLE001
        pass
    if not _on(cfg):
        return out
    for k, v in sorted(_d(getattr(memory, "refusal_streaks", None)).items()):
        if isinstance(v, dict) and v.get("say"):
            out.append(f"{v.get('rule')}: {str(v.get('type') or 'its step').replace('_', ' ')} refused "
                       f"{v.get('n')} times in a row for the same reason ({str(v.get('why') or '')[:80]}): "
                       f"asked again in {v.get('days')} day(s), twice as long after each refusal (at most "
                       f"{_c(cfg, 'r5p3_refusal_wait_max_days')}), at once when the fort changes "
                       "(a new level or well, another reason)")
    return out


def said(memory) -> None:
    """The notes of this cycle's new waits were made: not again."""
    try:
        _att.ledger_said(memory)
    except Exception:  # noqa: BLE001
        pass
    for v in _d(getattr(memory, "refusal_streaks", None)).values():
        if isinstance(v, dict) and v.get("say"):
            v["say"] = False
