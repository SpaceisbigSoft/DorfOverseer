"""The outcome log: every meaningful decision is a small experiment.

When the planner, the strategist, the weights engine or a self-tuning script
does something that should show in the fort's numbers, an entry is opened:

    what it did, who did it, which number should move and which way,
    the number before, and the day to judge it.

On that day a script compares the numbers and gives a verdict: helped, no
effect, hurt, or unclear (a siege, a migrant wave or a big loss got in the
way, or the number couldn't be read). No tokens are spent on judging.

Since 0.31 the numbers compared are the timeline's averages (brain/timeline.py):
the week before the decision against its last days (up to a week), which is
far less noisy than two single days. With too few days recorded (a new fort,
the game not run), today's number is used as before.

Kept in the fort's memory (memory.outcomes):
  open     entries still waiting for their day (at most MAX_OPEN)
  recent   the newest judged entries (at most MAX_RECENT)
  tally    kind -> {"helped", "none", "hurt", "unclear"} counts

    opened = record_actions(results, state, memory, by="planner")
    judged = judge(state, memory)
    lines  = lessons(memory)    # kinds whose verdicts agree, in words
"""

from __future__ import annotations

from digest import _d, _l, normalize
from util import state_tick

DAY = 1200
MAX_OPEN = 40
MAX_RECENT = 30
REL_TOL = 0.05              # a change must also be at least this share of the number before
LEVEL_WAIT_DAYS = 7         # a level still being built: judged this much later...
LEVEL_WAIT_MAX_DAYS = 84    # ...for at most this long (a level never finished is judged anyway)
# Numbers that move with the population by themselves: (metric, how a dwarf
# more changes it). Free beds drop by one with every migrant, whatever the
# AI built.
POP_BOUND = {"free_beds": -1.0}
MIN_FOR_LESSON = 3          # judged entries (not unclear) before a kind says anything
LESSON_SHARE = 0.6          # ... and one verdict must have at least this share
VERDICT_TEXT = {"helped": "helped", "none": "no effect", "hurt": "hurt", "unclear": "unclear"}

# The numbers decisions are judged on: name -> (words, smallest change that counts)
METRICS = {
    "drink_pd": ("drink per dwarf", 1.0),
    "meals_pd": ("meals per dwarf", 1.0),
    "plants_pd": ("food plants per dwarf", 1.0),
    "unhappy_pct": ("unhappy dwarves %", 3.0),
    "happy_pct": ("happy dwarves %", 3.0),
    "idle_pct": ("idle adults %", 5.0),
    "needs_care": ("dwarves needing care", 1.0),
    "hungry": ("starving or parched dwarves", 1.0),
    "unpastured": ("grazers without a pasture", 1.0),
    "free_beds": ("free beds", 1.0),
}


def measure(state: dict) -> dict:
    """Today's numbers (only those that could be read)."""
    s = normalize(state)
    err = s["_errors"]
    out: dict = {}
    dw = _d(s.get("dwarves"))
    pop = dw.get("total") or 0
    out["pop"] = pop
    if pop and "stocks" not in err:
        st = _d(s.get("stocks"))
        out["drink_pd"] = round((st.get("drink") or 0) / pop, 2)
        out["meals_pd"] = round((st.get("prepared_meals") or 0) / pop, 2)
        out["plants_pd"] = round((st.get("plants") or 0) / pop, 2)
    if pop:
        stress = _d(dw.get("stress"))
        if stress:
            out["unhappy_pct"] = round(100 * sum(stress.get(k, 0) for k in ("miserable", "very_unhappy",
                                                                              "unhappy")) / pop, 1)
            out["happy_pct"] = round(100 * sum(stress.get(k, 0) for k in ("happy", "ecstatic")) / pop, 1)
        adults = dw.get("adults") or 0
        if adults:
            out["idle_pct"] = round(100 * (dw.get("idle_adults") or 0) / adults, 1)
        out["needs_care"] = dw.get("needs_medical_care") or 0
    if "society" not in err:
        so = _d(s.get("society"))
        out["hungry"] = (so.get("starving") or 0) + (so.get("parched") or 0)
        out["unpastured"] = so.get("grazers_unpastured") or 0
    if "buildings" not in err and pop:
        out["free_beds"] = (_d(_d(s.get("buildings")).get("other")).get("Bed") or 0) - pop
    return out


# kind -> (metric, which way it should move, days to wait, what it is in words)
KINDS = {
    "drink_order": ("drink_pd", "up", 14, "brewing orders"),
    "meal_order": ("meals_pd", "up", 14, "cooking orders"),
    "idle_blocks": ("idle_pct", "down", 7, "block orders for idle hands"),
    "farm_plots": ("plants_pd", "up", 56, "new farm plots"),
    "farm_level": ("plants_pd", "up", 84, "a dug farm level"),
    "new_pasture": ("unpastured", "down", 7, "a new pasture"),
    "fill_pasture": ("unpastured", "down", 3, "putting grazers in a pasture"),
    "bedrooms": ("free_beds", "up", 28, "a bedroom level"),
    "dining": ("unhappy_pct", "down", 28, "a dining hall"),
    "tavern": ("unhappy_pct", "down", 56, "a tavern"),
    "temple": ("unhappy_pct", "down", 56, "a temple"),
    "library": ("unhappy_pct", "down", 56, "a library"),
    "memorial": ("unhappy_pct", "down", 56, "a memorial hall"),
    "hospital": ("needs_care", "down", 28, "a hospital"),
    "style": ("happy_pct", "up", 84, "a change of style"),
    "drink_target": ("drink_pd", None, 28, "a new drink target"),
    "meal_target": ("meals_pd", None, 28, "a new meal target"),
    "farm_target": ("plants_pd", None, 56, "a new farm size"),
    "pasture_margin": ("unpastured", "down", 84, "a new pasture size"),
}


def kind_of(action: dict) -> str | None:
    """Which kind of experiment an action is (None: nothing to judge it on)."""
    t = action.get("type")
    if t == "work_order":
        r = str(action.get("recipe") or "")
        if r in ("brew_drink", "brew_drink_from_fruit", "make_mead"):
            return "drink_order"
        if r.startswith("prepare_") and r.endswith("_meal"):
            return "meal_order"
        if r == "stone_blocks":
            return "idle_blocks"
        return None
    if t == "farm_plots":
        return "farm_level" if action.get("dig") else "farm_plots"
    if t == "make_pasture":
        return "new_pasture"
    if t == "pasture":
        return "fill_pasture"
    if t == "start_project" and action.get("kind") in KINDS:
        return action["kind"]
    return None


def _state(memory) -> dict:
    o = memory.outcomes if isinstance(memory.outcomes, dict) else {}
    memory.outcomes = o
    for k, default in (("open", []), ("recent", []), ("tally", {})):
        if not isinstance(o.get(k), type(default)):
            o[k] = default                # (the save turns an empty {} into [])
    return o


def _context(state: dict, memory) -> dict:
    h = memory.culture if isinstance(memory.culture, dict) else {}
    return {"pop": _d(normalize(state).get("dwarves")).get("total") or 0,
            "sieges": int(h.get("sieges", 0) or 0),
            "deaths": int(h.get("citizen_deaths", 0) or 0)}


def open_entry(state: dict, memory, kind: str, what: str, by: str,
               expect: str | None = None, now: int | None = None) -> dict | None:
    """Open one entry; None if this kind is already being watched (one at a
    time per kind, so ten brewing orders are judged once) or can't be measured."""
    if kind not in KINDS:
        return None
    metric, direction, days, _ = KINDS[kind]
    direction = expect or direction
    if direction not in ("up", "down"):
        return None
    if now is None:
        now = state_tick(state)
    # the week before, from the timeline; today's number when there's too little of it
    before, n = _timeline_avg(memory, metric, now // DAY - BASELINE_DAYS + 1, now // DAY, MIN_TIMELINE_DAYS)
    if before is None:
        before, n = measure(state).get(metric), 1
    if before is None:
        return None
    o = _state(memory)
    if any(e.get("kind") == kind for e in o["open"]):
        return None
    e = {"kind": kind, "what": what[:120], "by": by, "tick": now, "judge_at": now + days * DAY,
         "metric": metric, "expect": direction, "before": before, "before_days": n,
         "context": _context(state, memory), "date": _date_text(state)}
    o["open"] = (o["open"] + [e])[-MAX_OPEN:]
    return e


BASELINE_DAYS = 7          # "before" is the average of the week up to the decision
MIN_TIMELINE_DAYS = 3      # ...when the timeline has at least this many of those days


def _timeline_avg(memory, metric: str, first: int, last: int, min_days: int):
    import timeline                       # (timeline imports this module)
    if not isinstance(getattr(memory, "timeline", None), dict) or not memory.timeline.get("days"):
        return None, 0
    return timeline.avg(memory, metric, first, last, min_days)


def after_value(e: dict, memory, measured: dict, now: int):
    """The number to judge an entry on: the average of its last days (up to a
    week, never from before the decision), or today's number."""
    metric = e.get("metric")
    wait = max(1, (e.get("judge_at", now) - e.get("tick", now)) // DAY)
    span = max(1, min(BASELINE_DAYS, wait // 2))
    first = max(e.get("tick", 0) // DAY + 1, now // DAY - span + 1)
    v, n = _timeline_avg(memory, metric, first, now // DAY, min(MIN_TIMELINE_DAYS, span))
    if v is not None:
        return {metric: v}, n
    return measured, 1


def _date_text(state: dict) -> str:
    d = _d(state.get("date"))
    return f"{d.get('day')} {d.get('month')} y{d.get('year')}"


def record_actions(results, state: dict, memory, by: str = "planner") -> list[dict]:
    """After acting: an entry for each action that worked and has a kind."""
    opened = []
    for p, r in results:
        if not isinstance(r, dict) or r.get("ok") is not True:
            continue
        kind = kind_of(p.action)
        if not kind:
            continue
        who = "strategist" if p.rule == "strategist" or str(p.reason).startswith("strategist") else by
        e = open_entry(state, memory, kind, p.reason or KINDS[kind][3], who)
        if e:
            opened.append(e)
    return opened


def verdict(e: dict, after: dict, context: dict) -> tuple[str, str]:
    """(verdict, why) for one entry, from the numbers now. A change counts
    when it is at least the metric's step and 5% of the number before; a
    number that moves with the population (free beds) is judged with the
    newcomers taken out."""
    metric = e.get("metric")
    words, tol = METRICS.get(metric, (metric, 1.0))
    c0 = _d(e.get("context"))
    if context.get("sieges", 0) > c0.get("sieges", 0):
        return "unclear", "a siege came in between"
    pop0, pop1 = c0.get("pop") or 0, context.get("pop") or 0
    if pop0 and abs(pop1 - pop0) > max(5, 0.25 * pop0):
        return "unclear", f"the population changed a lot ({pop0} to {pop1})"
    if context.get("deaths", 0) - c0.get("deaths", 0) >= max(3, 0.1 * (pop0 or 1)):
        return "unclear", "many dwarves died in between"
    if metric not in after or e.get("before") is None:
        return "unclear", f"{words} couldn't be read"
    before, now = float(e["before"]), float(after[metric])
    delta = now - before
    moved = f"{words} {before:g} to {now:g}"
    if metric in POP_BOUND and pop0 and pop1 != pop0:
        delta -= POP_BOUND[metric] * (pop1 - pop0)
        moved += f" ({pop1 - pop0:+d} dwarves: {delta:+g} without them)"
    tol = max(tol, REL_TOL * abs(before))
    sign = 1 if e.get("expect") == "up" else -1
    if sign * delta >= tol:
        return "helped", moved
    if -sign * delta >= tol:
        return "hurt", moved
    return "none", moved


LEVEL_KINDS = {"bedrooms", "dining", "tavern", "temple", "library", "memorial", "hospital", "farm_level"}


def _level_open(state: dict, kind: str) -> bool:
    """Is a level of this kind still being dug or furnished?"""
    want = "farms" if kind == "farm_level" else kind
    pr = _d(state.get("projects"))
    return any(isinstance(p, dict) and p.get("kind") == want for p in _l(pr.get("open")))


def judge(state: dict, memory, now: int | None = None) -> list[dict]:
    """Judge every entry whose day has come. Returns the judged entries."""
    o = _state(memory)
    if now is None:
        now = state_tick(state)
    after, ctx = measure(state), _context(state, memory)
    keep, done = [], []
    for e in o["open"]:
        if not isinstance(e, dict):
            continue
        if e.get("tick", 0) > now:
            continue                      # an older save was loaded: this never happened
        if now < e.get("judge_at", 0):
            keep.append(e)
            continue
        # a level not built yet can't have done anything: wait for it
        if e.get("kind") in LEVEL_KINDS and _level_open(state, e["kind"]) and \
                now - e.get("first_judge_at", e.get("judge_at", now)) < LEVEL_WAIT_MAX_DAYS * DAY:
            keep.append(dict(e, judge_at=now + LEVEL_WAIT_DAYS * DAY, first_judge_at=e.get("first_judge_at",
                                                                                              e.get("judge_at"))))
            continue
        seen, n = after_value(e, memory, after, now)
        v, why = verdict(e, seen, ctx)
        if n > 1 or (e.get("before_days") or 1) > 1:
            why += f" (averages over {e.get('before_days') or 1} and {n} days)"
        e = dict(e, verdict=v, why=why, judged=_date_text(state), after_days=n)
        done.append(e)
        t = o["tally"].setdefault(e["kind"], {})
        if not isinstance(t, dict):
            t = o["tally"][e["kind"]] = {}
        t[v] = t.get(v, 0) + 1
    o["open"] = keep
    o["recent"] = (o["recent"] + done)[-MAX_RECENT:]
    return done


def lessons(memory) -> list[str]:
    """Kinds whose verdicts agree often enough to say something, in words:
    'brewing orders helped (4 of 5)'."""
    o = _state(memory)
    out = []
    for kind, t in sorted(o["tally"].items()):
        if not isinstance(t, dict) or kind not in KINDS:
            continue
        judged = sum(t.get(v, 0) for v in ("helped", "none", "hurt"))
        if judged < MIN_FOR_LESSON:
            continue
        best = max(("helped", "none", "hurt"), key=lambda v: t.get(v, 0))
        if t.get(best, 0) / judged >= LESSON_SHARE:
            out.append(f"{KINDS[kind][3]}: {VERDICT_TEXT[best]} ({t[best]} of {judged})")
    return out


def summary_lines(memory, limit: int = 6) -> list[str]:
    """The newest verdicts, for the panel."""
    o = _state(memory)
    out = []
    for e in reversed(o["recent"][-limit:]):
        out.append(f"{e.get('judged', '?')}: {KINDS.get(e.get('kind'), (0, 0, 0, e.get('kind')))[3]} "
                   f"({e.get('by')}): {VERDICT_TEXT.get(e.get('verdict'), '?')}, {e.get('why')}")
    return out


def waiting_lines(memory, limit: int = 4) -> list[str]:
    o = _state(memory)
    out = []
    for e in o["open"][-limit:]:
        days = max(0, (e.get("judge_at", 0) - e.get("tick", 0)) // DAY)
        words = METRICS.get(e.get("metric"), (e.get("metric"), 0))[0]
        out.append(f"{KINDS.get(e.get('kind'), (0, 0, 0, '?'))[3]} ({e.get('by')}, {e.get('date')}): "
                   f"expects {words} to go {e.get('expect')} within {days} days")
    return out
