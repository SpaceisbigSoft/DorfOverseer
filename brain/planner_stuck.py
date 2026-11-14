"""(0.105.45) The sweep for things stuck "in progress" (Phase 11 (d)).

Over many runs the forts lost dwarves or stalled because something the AI
started stayed "in progress" for good: a gate the game held shut
(0.105.32), a cistern step, a well dig, a level kept "digging" with nothing
dug, a squad's kill order on a target long gone, a work order neither done
nor cancelled, a lever pull job never done (the cavern well's 49 tries,
0.104.164). Each got a rule of its own in time; this one is the net under
them all. The bridge's `stuck` section (lua/ai-stuck.lua) lists the AI's own
things in a state that isn't final, with the tick each entered it and the
tick its progress last changed; the projects' dig and furnish counts are
joined from the projects section here.

Per kind a timeout (PLANNER_CONFIG `stuck_sweep_<kind>_days`, in game days)
without progress, then the remedy that already exists for it:

  project    a level: first its dig nudged (the stalled dig jobs freed, or
             the level dug before the rest; a well's channel job renewed),
             then given up (cancel_project; never dug at all: its spot kept
             off-limits a while). A level furnishing for ever: finished as
             it stands (finish_project stalled). Never a way in or a
             landmark (their own rules), never one decorating (it times out
             by itself).
  cistern    the next step asked (the cistern rule asks it anyway), then the
             cistern retired (cistern_step retire; the bridge shuts its
             floodgate first, and refuses while it can't).
  waterwork  the next step asked, then the work retired (water_work retire);
             a held work is the waterworks rule's own.
  lever      an AI lever's pull job nobody does: the job taken off and asked
             afresh (stuck_reset reissue), then dropped (stuck_reset drop:
             the rule that wanted the pull asks again from how things are).
  squad      an AI kill order whose targets are all dead, gone or caged: the
             order cleared (squad_orders clear).
  order      an AI work order that hasn't moved: cancelled and booked as
             stuck (cancel_work_order stuck: the recipe is held its 28-112
             days); the orders rule cancels at 28 days, this at 56.
  gate       gate pieces the AI planned waiting: their suspended jobs
             resumed (free_gate_jobs); a gate is never given up, only said.

Escalation, per thing: past its timeout the nudge (step 1); still nothing
`stuck_sweep_nudge_wait_days` later (at most half the timeout) the retire (step
2); after a retire the thing is left `stuck_sweep_backoff_days`. Any progress
starts the steps again. A retire is remembered for the kind of thing
("family": a level kind, the cistern, a recipe...): each retire in the last
game year doubles that family's timeout (to 8x), and past
`stuck_sweep_family_max` retires a year it is only said, so the same thing is not
restarted and retired in a loop. One note a thing, at most
`stuck_sweep_notes_max` a cycle.

Never twice: the sweep runs after every other rule and leaves a thing alone
when another rule's proposal already acts on it this cycle (the level's
project id, the cistern's retire or shut, the squad's orders, the order's
cancel, the lever's pull, any gate_stuck / way_in / gate_jobs proposal for
the gates). It only ever touches what the bridge lists, and the bridge lists
only the AI's own (its levers, its orders, its kill orders, its projects).
Without the `stuck` section (an older bridge, the fixtures) nothing here
proposes or notes anything.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import MULTI_PER_CYCLE, TICKS_PER_DAY, TICKS_PER_YEAR, Proposal, abs_tick

__all__ = ["stuck_rows", "stuck_key", "_stuck_rule", "note_stuck", "soak_summary", "past_count", "STUCK_RULE"]

STUCK_RULE = "stuck_sweep"
MULTI_PER_CYCLE.add(STUCK_RULE)       # several things a cycle (capped by stuck_sweep_actions_max)

KINDS = ("project", "cistern", "waterwork", "lever", "squad", "order", "gate")
DEFAULT_DAYS = {"project": 84, "cistern": 84, "waterwork": 84, "lever": 2, "squad": 1, "order": 56, "gate": 42}
# project kinds whose own rules see them through (planner_gates' way in, the Design track's landmarks)
PROJECT_OWNED = ("way_in", "landmark")
# the rules that work on the gates: while any proposes, the sweep leaves the gates alone
GATE_RULES = {"gate_stuck", "way_in", "gate_jobs", "gate_parts", "gate", "gates"}
WORDS = {"project": "level", "cistern": "cistern", "waterwork": "water work", "lever": "lever's pull",
         "squad": "kill order", "order": "work order", "gate": "gate"}


def stuck_rows(s: dict) -> list:
    """The section's rows the sweep can read: a known kind, an id, a state."""
    return [r for r in _l(_d(s.get("stuck")).get("list"))
            if isinstance(r, dict) and r.get("kind") in KINDS and r.get("id") is not None
            and isinstance(r.get("state"), str)]


def stuck_key(r: dict) -> str:
    return r["key"] if isinstance(r.get("key"), str) else f"{r.get('kind')}:{r.get('id')}"


def _int(v, default=None):
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _projects(s: dict) -> dict:
    pr = _d(s.get("projects"))
    return {p["id"]: p for p in _l(pr.get("open")) + _l(pr.get("decorating"))
            if isinstance(p, dict) and _int(p.get("id")) is not None}


def _orders(s: dict) -> dict:
    return {o["id"]: o for o in _l(s.get("orders")) if isinstance(o, dict) and _int(o.get("id")) is not None}


def _sig(r: dict, proj: dict | None) -> str:
    """Its progress, as one text: the bridge's, and a level's dig and furnish counts."""
    sig = f"{r.get('state')}|{r.get('progress')}"
    if proj is not None:
        dig, fur = _d(proj.get("dig")), _d(proj.get("furnish"))
        sig += f"|{dig.get('dug')}/{dig.get('total')}|{fur.get('done')}/{fur.get('placed')}"
    return sig


def _family(r: dict, order: dict | None) -> str:
    k = r["kind"]
    if k == "project":
        return f"project:{r.get('what')}"
    if k == "order":
        return f"order:{(order or {}).get('recipe') or r.get('what')}"
    if k in ("cistern",):
        return "cistern"
    if k == "waterwork":
        return f"waterwork:{r.get('id')}"
    return stuck_key(r)


def _retires(book: dict, fam: str, now: int) -> int:
    return sum(1 for t in _l(_d(book.get("families")).get(fam)) if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR)


def _taken(proposals: list, r: dict) -> str | None:
    """Another rule's proposal that already acts on this thing this cycle: its rule, else None.
    The cistern's and a waterwork's plain next step (their rules ask it every cycle) is not one."""
    k, id_ = r["kind"], r.get("id")
    for p in proposals:
        a = _d(p.action)
        t = a.get("type")
        if k == "project" and a.get("project_id") == id_:
            return p.rule
        if k == "cistern" and (t == "cistern_step" and (a.get("retire") or a.get("shut") or a.get("relink"))):
            return p.rule
        if (k == "waterwork" and t == "water_work" and a.get("kind") == r.get("what")
                and (a.get("retire") or a.get("shut") or a.get("reopen") or a.get("recheck"))):
            return p.rule
        if k == "lever" and ((t == "pull_gate" and a.get("lever_id") == id_) or (t == "stuck_reset" and a.get("id") == id_)):
            return p.rule
        if k == "squad" and t == "squad_orders" and a.get("squad_id") == id_:
            return p.rule
        if k == "order" and t == "cancel_work_order" and a.get("order_id") == id_:
            return p.rule
        if k == "gate" and (p.rule in GATE_RULES or a.get("entrance_id") == id_):
            return p.rule
    return None


def _gate_rules_lately(memory, r: dict, now: int, cfg: dict) -> str | None:
    """A gate rule that acted within the nudge wait (planner.select's last_fired,
    by rule or "rule:id"): the gates are theirs this while, not the sweep's
    (their free_gate_jobs every couple of days is the nudge already)."""
    if r["kind"] != "gate" or memory is None:
        return None
    wait = int(cfg.get("stuck_sweep_nudge_wait_days", 14)) * TICKS_PER_DAY
    for k, t in _d(getattr(memory, "last_fired", None)).items():
        rule = str(k).split(":")[0]
        if rule in ("gate_jobs", "gate_stuck", "way_in") and isinstance(t, int) and 0 <= now - t < wait:
            return rule
    return None


def _owner_steps(proposals: list, r: dict) -> bool:
    """The thing's own rule asks its next step this cycle (the cistern, a waterwork): that is the nudge."""
    for p in proposals:
        a = _d(p.action)
        if r["kind"] == "cistern" and a.get("type") == "cistern_step":
            return True
        if r["kind"] == "waterwork" and a.get("type") == "water_work" and a.get("kind") == r.get("what"):
            return True
    return False


def _remedies(r: dict, proj: dict | None, order: dict | None, days: int):
    """(nudge, retire, words): the actions (None where there is none) and what the thing is."""
    k, id_, st = r["kind"], r.get("id"), r.get("state")
    if k == "project":
        what = f"the {r.get('what')} level (project {id_}, {st})"
        if st == "dig":
            dig = _d(proj.get("dig"))
            dug, total = _int(dig.get("dug"), 0), _int(dig.get("total"), 0)
            what = f"the {r.get('what')} level (project {id_}: {dug} of {total} tiles dug)"
            if r.get("what") == "well":
                nudge = {"type": "renew_well_dig", "project_id": id_, "priority": 2}
            elif _int(dig.get("digging"), 0) > 0:
                nudge = {"type": "free_dig_jobs", "project_id": id_}
            else:
                nudge = {"type": "prioritize_dig", "project_id": id_, "priority": 2}
            retire = {"type": "cancel_project", "project_id": id_}
            if dug == 0:
                retire["unreached"] = True
            if r.get("what") == "well" and (r.get("cavern") or _d(proj.get("summary")).get("cavern")):
                retire["cavern_well"] = True
            return nudge, retire, what
        if st == "furnish":
            fur = _d(proj.get("furnish"))
            what = (f"the {r.get('what')} level (project {id_}: {fur.get('done')} of {fur.get('placed')} "
                    "pieces built)")
            return None, {"type": "finish_project", "project_id": id_, "stalled": True}, what
        return None, None, what
    if k == "cistern":
        return ({"type": "cistern_step"},
                {"type": "cistern_step", "retire": True, "why": f"stuck at its {st} step for {days} days"[:110]},
                f"the cistern ({st})")
    if k == "waterwork":
        step = {"type": "water_work", "kind": r.get("what")}
        if r.get("shop"):
            step["shop"] = r["shop"]
        return (step, dict(step, retire=True, why=f"stuck {st} for {days} days"[:110]),
                f"the {r.get('what')} water work ({st})")
    if k == "lever":
        who = f"lever {id_}" + (f" ({r.get('what')})" if r.get("what") else "")
        return ({"type": "stuck_reset", "kind": "lever", "id": id_, "mode": "reissue"},
                {"type": "stuck_reset", "kind": "lever", "id": id_, "mode": "drop"},
                f"the pull job on {who}" + ("" if r.get("worker") else ", no dwarf has taken it"))
    if k == "squad":
        gone = ", ".join(f"{_int(r.get(x), 0)} {x}" for x in ("dead", "gone", "caged") if _int(r.get(x), 0))
        return (None, {"type": "squad_orders", "squad_id": id_, "clear": True},
                f"{r.get('what') or 'a squad'}'s kill order (its {_int(r.get('targets'), 0)} target(s): {gone})")
    if k == "order":
        recipe = (order or {}).get("recipe") or r.get("what")
        return (None, {"type": "cancel_work_order", "order_id": id_, "stuck": str(recipe)},
                f"the AI's {recipe} order ({r.get('left')} of {r.get('total')} left)")
    if k == "gate":
        return ({"type": "free_gate_jobs", "entrance_id": id_}, None,
                f"the gate planned at the {r.get('what')} entrance at x{r.get('x')} y{r.get('y')} "
                f"({_int(r.get('pieces'), 0)} piece(s)" + (", no dwarf on them" if not r.get("worker") else "") + ")")
    return None, None, k


def _skip(r: dict, proj: dict | None, order: dict | None, cfg: dict, dead=None) -> str | None:
    """Why the sweep leaves this one to others (None: it is the sweep's)."""
    k = r["kind"]
    if k == "project":
        if r.get("what") in PROJECT_OWNED:
            return "its own rules see it through"
        if proj is None:
            return "the projects section doesn't show it this cycle"
        if r.get("state") == "decorate":
            return "a level decorating times out by itself"
    if k == "cistern" and cfg.get("cistern_hold"):
        return "the cistern is on hold"
    if k == "squad" and r.get("state") != "kill_done":
        return "its targets still live"
    if k == "order":
        if order is None or not order.get("by_ai") or order.get("repeats"):
            return "not one of the AI's one-time orders this cycle"
        if order.get("validated") is False or r.get("validated") is False:
            return "not approved yet (the approve rule's)"
        if _int(_d(order.get("jobs")).get("working"), 0) > 0:
            return "a dwarf is at work on it"
        # (as the orders rule, 0.105.22) the last slab or coffin is kept while ghosts walk or bodies wait
        dd = _d(dead)
        if order.get("recipe") in ("stone_slab", "stone_coffin") and (_int(dd.get("ghosts"), 0) > 0
                                                                     or _int(dd.get("unburied"), 0) > 0):
            return "kept for the waiting dead"
    return None


def _days(cfg: dict, kind: str) -> int:
    v = cfg.get(f"stuck_sweep_{kind}_days", DEFAULT_DAYS[kind])
    return max(1, int(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else DEFAULT_DAYS[kind]


def _stuck_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Every AI thing past its timeout without progress: its nudge, then its
    retire, once each, with the backoff; one note a thing."""
    sec = _d(s.get("stuck"))
    if not isinstance(sec.get("list"), list):
        return
    now = abs_tick(s)
    book = _d(getattr(memory, "stuck_seen", None)) if memory is not None else {}
    if memory is not None:
        memory.stuck_seen = book
    items = book.setdefault("items", {})
    fams = book.setdefault("families", {})
    for f in list(fams):
        kept = [t for t in _l(fams[f]) if isinstance(t, int) and 0 <= now - t < TICKS_PER_YEAR]
        if kept:
            fams[f] = kept
        else:
            del fams[f]
    projects, orders = _projects(s), _orders(s)
    acted = 0
    said: list = []
    past: dict = {}
    live = set()
    act_max = int(cfg.get("stuck_sweep_actions_max", 2))
    backoff = int(cfg.get("stuck_sweep_backoff_days", 112))
    fam_max = int(cfg.get("stuck_sweep_family_max", 3))
    for r in stuck_rows(s):
        key = stuck_key(r)
        live.add(key)
        proj = projects.get(r.get("id")) if r["kind"] == "project" else None
        order = orders.get(r.get("id")) if r["kind"] == "order" else None
        sig = _sig(r, proj)
        it = items.get(key)
        if not isinstance(it, dict) or it.get("state") != r["state"]:
            it = {"state": r["state"], "sig": sig, "moved": _int(r.get("moved"), now), "step": 0}
        elif it.get("sig") != sig:
            # it moved: the steps begin again (a retire's backoff too)
            it = {"state": r["state"], "sig": sig, "moved": now, "step": 0}
        items[key] = it
        since = _int(r.get("since"), now)
        moved = max(_int(it.get("moved"), now), _int(r.get("moved"), 0))
        still = max(0, now - moved) // TICKS_PER_DAY
        age = max(0, now - since) // TICKS_PER_DAY
        fam = _family(r, order)
        n_ret = _retires(book, fam, now)
        limit = _days(cfg, r["kind"]) * (2 ** min(n_ret, 3))
        if still < limit or age < limit:
            continue
        why_not = _skip(r, proj, order, cfg, s.get("dead"))
        if why_not:
            continue
        past[r["kind"]] = past.get(r["kind"], 0) + 1
        nudge, retire, what = _remedies(r, proj, order, still)
        head = f"stuck: {what} hasn't moved in {still} days"
        owner = _taken(proposals, r) or _gate_rules_lately(memory, r, now, cfg)
        if owner:
            said.append(f"{head}: the {owner} rule acts on it this cycle")
            continue
        step = _int(it.get("step"), 0)
        at = _int(it.get("at"), now)
        wait = min(int(cfg.get("stuck_sweep_nudge_wait_days", 14)), max(1, limit // 2))
        if step >= 2:
            if now - at >= backoff * TICKS_PER_DAY:
                it.update(step=0, at=None)          # its backoff over: the steps may begin again
            else:
                said.append(f"{head}: {'retired' if retire else 'said'} {max(0, now - at) // TICKS_PER_DAY} day(s) ago; "
                            f"left {max(1, backoff - max(0, now - at) // TICKS_PER_DAY)} more day(s)")
            continue
        if step == 0 and nudge is not None:
            if _owner_steps(proposals, r):
                # its own rule asks the next step this cycle: that is the nudge
                it.update(step=1, at=now)
                said.append(f"{head}: its next step is asked again; given up in {wait} day(s) if nothing moves")
                continue
            if acted >= act_max:
                said.append(f"{head}: nudged next cycle (the sweep's limit this cycle)")
                continue
            p = Proposal(STUCK_RULE, nudge, f"{head}: nudge it ({nudge['type']})", 5)
            p.stuck_key, p.stuck_step, p.stuck_family = key, 1, fam
            proposals.append(p)
            acted += 1
            said.append(f"{head}: nudged; given up in {wait} day(s) if nothing moves")
            continue
        if step == 1 and now - at < wait * TICKS_PER_DAY:
            said.append(f"{head}: nudged {max(0, now - at) // TICKS_PER_DAY} day(s) ago; given up in "
                        f"{max(1, wait - max(0, now - at) // TICKS_PER_DAY)} day(s) if nothing moves")
            continue
        if retire is None:
            # nothing to give up (a gate is kept): said, and left a while
            it.update(step=2, at=now)
            said.append(f"{head}: kept (a gate is never given up); the gate rules map the entrances again")
            continue
        if n_ret >= fam_max:
            said.append(f"{head}: {n_ret} like it retired this year already: left to its own rules")
            continue
        if acted >= act_max:
            said.append(f"{head}: given up next cycle (the sweep's limit this cycle)")
            continue
        p = Proposal(STUCK_RULE, retire, f"{head}" + (" after a nudge" if step == 1 else "")
                     + f": give it up ({retire['type']}" + (" clear" if retire.get("clear") else "")
                     + (" retire" if retire.get("retire") else "") + ")", 2 if r["kind"] == "squad" else 4)
        p.stuck_key, p.stuck_step, p.stuck_family = key, 2, fam
        if r["kind"] in ("cistern", "waterwork"):
            # its own rule's plain next step this cycle would run beside the retire: left out
            proposals[:] = [q for q in proposals if not (
                (r["kind"] == "cistern" and _d(q.action).get("type") == "cistern_step")
                or (r["kind"] == "waterwork" and _d(q.action).get("type") == "water_work"
                    and _d(q.action).get("kind") == r.get("what")))]
        proposals.append(p)
        acted += 1
        said.append(f"{head}: given up")
    for k in [k for k in items if k not in live]:
        del items[k]
    book["past"] = past
    book["tick"] = now
    cap = int(cfg.get("stuck_sweep_notes_max", 6))
    notes.extend(said[:cap])
    if len(said) > cap:
        notes.append(f"stuck: {len(said) - cap} more thing(s) past their timeout (the `stuck` section lists them)")


def note_stuck(p, r: dict, memory, now: int) -> None:
    """planner.record: the sweep's own action done (or its answer lost): its
    thing's step and when; a retire booked for its family."""
    key = getattr(p, "stuck_key", None)
    if key is None or memory is None or _d(r).get("ok") is False:
        return
    book = _d(getattr(memory, "stuck_seen", None))
    memory.stuck_seen = book
    it = book.setdefault("items", {}).get(key)
    if isinstance(it, dict):
        it.update(step=getattr(p, "stuck_step", 1), at=now)
    if getattr(p, "stuck_step", 1) >= 2 and getattr(p, "stuck_family", None):
        fams = book.setdefault("families", {})
        fams[p.stuck_family] = (_l(fams.get(p.stuck_family)) + [now])[-8:]


def past_count(memory) -> int:
    past = _d(_d(getattr(memory, "stuck_seen", None)).get("past"))
    return sum(v for v in past.values() if isinstance(v, int))


def soak_summary(memory) -> dict | None:
    """The soak row's `stuck`: {past, kinds} from the last plan (None before the sweep ever ran)."""
    book = _d(getattr(memory, "stuck_seen", None))
    if "past" not in book:
        return None
    kinds = {k: v for k, v in _d(book.get("past")).items() if isinstance(v, int) and v}
    return {"past": sum(kinds.values()), "kinds": kinds}
