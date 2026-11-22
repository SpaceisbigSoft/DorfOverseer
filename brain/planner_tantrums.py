"""(0.105.47, R2 item 3, 12i) Tantrums one dwarf at a time: the posts, the
loyalty fix before the first death, a guard at the hospitals, the chronic
cases.

Why (I7c, the 11-14 Nov run): E lost 14 citizens to citizens. Five chronic
tantrum dwarves, miserable for years, held the posts the AI gave them
(doctor, tavern keeper, surgeon, bone doctor; two with skill 0) and beat
patients to death in their beds (8 of E's 11 "suffocated" died inside a
hospital zone). `break_fights` (DFHack fix/loyaltycascade) ran only after a
death: in y257 it fixed 45 units after the first and four more died. The
calm burrow never held a tantrum (outside 54 of 60 times). Crisis mode's
10-tantrums trigger never fired in a fort of 23-45.

This module reads the bridge's `tantrums` section (lua/ai-tantrums.lua): a
ledger of each citizen's tantrum starts, each thrower's posts, hospital
labours and unmet needs, the hospital zones, the squads (calm or not) and the
AI's hospital guards. What it does (nothing waits for the player):

  * staff_tantrum   a post (any location's: hospital, tavern, library...)
                    taken from a holder with a tantrum in the last 28 days
                    (vacate_post); the staffing rule gives it to a calm one
                    (ai-society can_staff refuses the very unhappy and the
                    recent tantrum-throwers).
  * break_fights    fix/loyaltycascade on every tantrum, berserk or
                    possession report and while a tantrum is loose (harmless
                    when nothing is wrong: "No loyalty cascade found" 30 times
                    in E), not only after a death; never with enemies about.
  * hospital_guard  while a tantrum is loose, one calm squad (no member very
                    unhappy or worse or in a tantrum, none wounded, thirsty or
                    hungry, on no other order) stationed in each hospital
                    zone (ai-military's station order, 0.105.45); taken off a
                    day after the last tantrum, after a week, or when its
                    soldiers thirst. The hospital burrow's priority is raised
                    for the fort's fights only while a guard stands
                    (planner_health).
  * chronic_*       a dwarf with 3+ tantrums in a year, one at a time (the
                    worst first): off every post and the hospital labours
                    (tantrum_step_down); their own unmet needs met in turn
                    with the AI's existing actions (lavish meals, idle
                    crafting, trinkets, chairs side by side in the tavern, a
                    bedroom); the training needs left to the training squads
                    (planner_society); the last resort, behind its checks:
                    their own solved cases convicted into a free jail chain
                    (convict with unit_id).
Without the section (an older bridge, the fixtures) only the report-driven
loyalty fix acts (from the announcements in memory).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import (AGENDA_THEMES, Proposal, TICKS_PER_DAY, _has_shop, _traits, abs_tick, game_day,
                          justice_held, queued)

# the season's agenda (planner_core agenda): these rules' themes
AGENDA_THEMES["staff_tantrum"] = "no post in the hands of a dwarf in a tantrum"
AGENDA_THEMES["hospital_guard"] = "a guard at the hospital while a tantrum is loose"
AGENDA_THEMES["chronic_posts"] = AGENDA_THEMES["chronic_care"] = "care for the chronic tantrum cases"
AGENDA_THEMES["chronic_convict"] = "care for the chronic tantrum cases"

__all__ = ["tantrum_section", "tantrum_rows", "guard_ids", "loose_tantrums", "note_tantrum_book",
           "mind_break_why", "_break_fights_report_rule", "_staff_tantrum_rule", "_hospital_guard_rule",
           "chronic_cases", "chronic_need_actions", "_chronic_rule", "_tantrum_rules", "NEED_WORDS"]

# the needs no action of the AI's meets for one dwarf, and who meets them
NEED_WORDS = {"MartialTraining": "training (the training squads meet it)", "Fight": "a fight (the training squads)",
              "PrayOrMeditate": "prayer (the temples the petitions raise)", "Wander": "wandering",
              "MakeRomance": "romance", "BeWithFamily": "family", "LearnSomething": "learning (the library)"}


def tantrum_section(s: dict) -> dict:
    sec = _d(s.get("tantrums"))
    return {} if sec.get("error") else sec


def tantrum_rows(s: dict) -> list:
    return [r for r in _l(tantrum_section(s).get("dwarves")) if isinstance(r, dict) and isinstance(r.get("id"), int)]


def guard_ids(s: dict) -> set:
    """The squads the AI has on guard at a hospital (the bridge checked each
    against the squad's own orders)."""
    return {g["squad_id"] for g in _l(tantrum_section(s).get("guards"))
            if isinstance(g, dict) and isinstance(g.get("squad_id"), int)}


def loose_tantrums(s: dict) -> int:
    v = tantrum_section(s).get("loose")
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _break_report(e: dict) -> bool:
    if not isinstance(e, dict) or e.get("kind") != "report":
        return False
    topic, typ = e.get("topic"), str(e.get("type") or "").upper()
    text = str(e.get("text") or "").lower()
    if " cancels " in text:
        return False
    if topic == "tantrum":
        return True
    if topic == "insanity" and ("BERSERK" in typ or "berserk" in text):
        return True
    return topic == "mood" and ("POSSESS" in typ or "possessed" in text)


def note_tantrum_book(state: dict, memory, events: list) -> int:
    """Bookkeeping (overseer, beside note_tantrums): the tick of each tantrum,
    berserk or possession report (the loyalty fix's trigger), and when a
    tantrum was last seen loose (the guards' hold). Returns new reports."""
    now = abs_tick(state)
    book = dict(_d(getattr(memory, "tantrum_book", None)))
    breaks = [t for t in _l(book.get("breaks")) if isinstance(t, int) and 0 <= now - t < 28 * TICKS_PER_DAY]
    n = sum(1 for e in events or [] if _break_report(e))
    if n:
        breaks.append(now)
    book["breaks"] = breaks[-30:]
    if loose_tantrums(state) > 0:
        book["loose_last"] = now
    elif isinstance(book.get("loose_last"), int) and book["loose_last"] > now:
        book.pop("loose_last")                        # an older save loaded
    memory.tantrum_book = book
    return n


def mind_break_why(s: dict, memory, cfg: dict) -> str | None:
    """Why the loyalty fix runs now, before anyone dies: a report this recent,
    a tantrum loose, a citizen berserk or possessed. None: no reason."""
    now = abs_tick(s)
    win = cfg["break_fights_report_ticks"]
    book = _d(getattr(memory, "tantrum_book", None))
    if any(isinstance(t, int) and 0 <= now - t < win for t in _l(book.get("breaks"))):
        return "a tantrum, berserk or possession was just reported"
    if any(isinstance(t, list) and len(t) == 2 and isinstance(t[0], int) and 0 <= now - t[0] < win
           for t in _l(getattr(memory, "tantrums", None))):
        return "a tantrum was just reported"
    sec = tantrum_section(s)
    if loose_tantrums(s):
        return f"{loose_tantrums(s)} citizen(s) in a tantrum"
    if int(sec.get("berserk") or 0) or _l(_d(s.get("hazards")).get("berserk")):
        return "a citizen gone berserk"
    if int(sec.get("possessed") or 0):
        return "a citizen possessed"
    return None


def _enemies_about(s: dict) -> bool:
    o = _d(s.get("others_on_map"))
    return bool(o.get("threats_that_can_reach_dwarves")) or any(
        isinstance(t, dict) and t.get("invader") for t in _l(o.get("threats")))


def _break_fights_report_rule(s: dict, memory, cfg: dict, proposals: list) -> None:
    """(I7c fix 3) fix/loyaltycascade before the first death: on every
    tantrum, berserk or possession report and while a tantrum is loose (the
    death-driven rule in planner_society stays; one proposal a cycle). The
    "enemies about" guard stays: the script takes soldiers out of their
    fights too."""
    if any(p.rule == "break_fights" for p in proposals):
        return
    why = mind_break_why(s, memory, cfg)
    if not why or _enemies_about(s):
        return
    proposals.append(Proposal("break_fights", {"type": "break_fights"},
                              f"{why}: break up any fight among the fort's own before someone dies (DFHack "
                              "fix/loyaltycascade; it changes nothing when no fight is on)", 0))


def _post_words(p: dict) -> str:
    return str(_d(p).get("post") or "post").lower().replace("_", " ")


def _staff_tantrum_rule(s: dict, cfg: dict, proposals: list) -> None:
    """(I7c fix 1) A post taken from a holder who threw a tantrum (in one now,
    or one begun in the last 28 days); the staffing rule gives it to the best
    calm dwarf (can_staff refuses the rest). A chronic case is the chronic
    rule's (every post and the labours at once). One post a cycle."""
    for r in tantrum_rows(s):
        if int(r.get("year") or 0) >= cfg["chronic_tantrums"]:
            continue
        if not (r.get("now") or int(r.get("n28") or 0) > 0):
            continue
        for p in _l(r.get("posts")):
            loc = _d(p).get("location_id")
            if not isinstance(loc, int) or loc < 0:
                continue
            when = "is in a tantrum" if r.get("now") else f"threw {r.get('n28')} tantrum(s) in 28 days"
            proposals.append(Proposal("staff_tantrum", {"type": "vacate_post", "location_id": loc, "unit_id": r["id"]},
                                      f"{r.get('name') or r['id']}, the {_post_words(p)}, {when}: the post goes to a "
                                      "calm dwarf (E's tantrum doctors and tavern keepers beat patients in their beds)",
                                      1))
            return


def _hospital_guard_rule(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """(I7c fix 4) While a tantrum is loose, one calm squad stationed in each
    hospital zone: soldiers on station meet a tantrum before it reaches a bed.
    Taken off a day after the last tantrum seen loose, after
    hospital_guard_max_days, or when its soldiers thirst; not posted, and
    (r9) taken off at once, while enemies can reach the dwarves (the
    military rules want the squads)."""
    sec = tantrum_section(s)
    if not sec:
        return
    now = abs_tick(s)
    guards = [g for g in _l(sec.get("guards")) if isinstance(g, dict) and isinstance(g.get("squad_id"), int)]
    squads = {q.get("id"): q for q in _l(sec.get("squads")) if isinstance(q, dict) and isinstance(q.get("id"), int)}
    loose = loose_tantrums(s)
    last = _d(getattr(memory, "tantrum_book", None)).get("loose_last")
    quiet = not loose and not (isinstance(last, int) and 0 <= now - last < cfg["hospital_guard_hold_ticks"])
    for g in guards:
        q = _d(squads.get(g["squad_id"]))
        since = g.get("since")
        # (r9) enemies about: the guard goes back to the military rules at
        # once (it was refused while enemies were about but never lifted, so
        # the fort's largest calm squad could stand in the hospital through a
        # siege)
        enemies = _enemies_about(s)
        why = ("the hospital guard is switched off" if not cfg["hospital_guard_on"]
               else "enemies can reach the dwarves" if enemies
               else "no tantrum loose for a day" if quiet
               else f"{q.get('parched')} of its soldiers are thirsty or hungry" if int(q.get("parched") or 0)
               else f"on guard {cfg['hospital_guard_max_days']} days" if isinstance(since, int)
               and now - since >= cfg["hospital_guard_max_days"] * TICKS_PER_DAY
               else None)
        if why:
            proposals.append(Proposal("hospital_guard", {"type": "hospital_guard", "squad_id": g["squad_id"],
                                                         "release": True},
                                      f"{why}: squad {g['squad_id']} leaves its guard at the hospital",
                                      0 if enemies else 2))
            return
    if not cfg["hospital_guard_on"] or not loose or _enemies_about(s):
        return
    guarded = {g.get("zone_id") for g in guards}
    used = {g["squad_id"] for g in guards}
    want = [h for h in _l(sec.get("hospitals")) if isinstance(h, dict) and isinstance(h.get("zone_id"), int)
            and h.get("x") is not None and h["zone_id"] not in guarded]
    if not want:
        return
    free = sorted((q for q in squads.values()
                   if q.get("calm") and int(q.get("members") or 0) > 0 and not q.get("wounded")
                   and not int(q.get("parched") or 0) and not int(q.get("player_orders") or 0)
                   and not int(q.get("ai_orders") or 0) and q["id"] not in used),
                  key=lambda q: (-int(q.get("members") or 0), q["id"]))
    if not free:
        notes.append(f"{loose} citizen(s) in a tantrum and no calm squad free to guard the hospital (a squad with "
                     "no unhappy, wounded or thirsty soldier, on no other order)")
        return
    h, q = want[0], free[0]
    proposals.append(Proposal("hospital_guard", {"type": "hospital_guard", "squad_id": q["id"], "zone_id": h["zone_id"]},
                              f"{loose} citizen(s) in a tantrum: a calm squad ({q.get('members')} soldiers) stands "
                              f"guard in the hospital (zone {h['zone_id']}, x{h.get('x')} y{h.get('y')} z{h.get('z')}) "
                              "so a tantrum meets soldiers before it reaches a bed", 1))


def chronic_cases(s: dict, cfg: dict) -> list:
    """The chronic tantrum cases (chronic_tantrums+ in a year), the worst first."""
    rows = [r for r in tantrum_rows(s) if int(r.get("year") or 0) >= cfg["chronic_tantrums"]]
    rows.sort(key=lambda r: (-int(r.get("year") or 0), -int(r.get("last") or 0), r["id"]))
    return rows


def chronic_need_actions(s: dict, cfg: dict, r: dict) -> list:
    """[(need, action, words, is_order)]: what the AI's existing actions can
    do for this dwarf's own unmet needs (their order), and a bedroom of their
    own if they have none."""
    b = _d(s.get("buildings"))
    nd = _d(s.get("needs"))
    out = []
    for need in _l(r.get("unmet")):
        if need == "EatGoodMeal" and _has_shop(b, "Kitchen") and not queued(s, {"prepare_lavish_meal"}):
            out.append((need, {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 5},
                        "cook lavish meals", True))
        elif need == "CraftObject" and _has_shop(b, "Craftsdwarfs"):
            out.append((need, {"type": "idle_crafting"}, "let idle dwarves craft at the Craftsdwarf's workshops", False))
        elif need in ("AcquireObject", "BeExtravagant") and int(nd.get("trinkets") or 0) > 0:
            out.append((need, {"type": "give_trinkets", "max": 5}, "give out trinkets", False))
        elif need in ("BeWithFriends", "Socialize", "MakeMerriment"):
            zones = [z for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)
                     and e.get("type") == "INN_TAVERN" for z in _l(e.get("zones")) if isinstance(z, int)]
            if zones:
                out.append((need, {"type": "pair_chairs", "zones": zones[:6], "max": 5},
                            "a chair beside each lone chair in the tavern (dwarves talk with those beside them)", False))
    free_bed = int(_d(_d(s.get("noble_rooms")).get("free")).get("bedroom") or 0)
    if r.get("bedroom") is False and free_bed > 0:
        out.append(("a room of their own", {"type": "give_room", "unit_id": r["id"], "kind": "bedroom"},
                    "give them a free bedroom", False))
    return out


def _free_chains(s: dict) -> int:
    j = _d(s.get("justice"))
    punish = _d(j.get("punish"))
    waiting = max(0, int(punish.get("n") or 0) - int(punish.get("prison") or 0))
    return int(j.get("restraints") or 0) - int(j.get("restraints_used") or 0) - waiting - 1


def _convict_blockers(s: dict, cfg: dict, r: dict) -> list:
    """Why the last resort (their own cases convicted) can't be taken now: []
    when it can. Teacheroar's sheriff beat convicts to death (and the guard
    killed patients) when a sentence found no jail place: only into a free
    chain (one kept spare), never while a beating waits, while anyone is
    wounded, or the dwarf is hurt; someone must hold the justice office."""
    out = []
    if not cfg["chronic_convict_on"]:
        out.append("switched off")
    if r.get("hurt"):
        out.append("they are hurt")
    if int(_d(s.get("dwarves")).get("needs_medical_care") or 0):
        out.append("someone is wounded")
    if int(_d(_d(s.get("justice")).get("punish")).get("beatings") or 0):
        out.append("a beating waits")
    if _free_chains(s) <= 0:
        out.append("no free jail chain")
    if not justice_held(s):
        out.append("no sheriff or captain of the guard")
    # (r9) a jail with no usable well: a prisoner gets no booze, only well
    # water, and planner_society frees every prisoner then (convict, release,
    # convict again each week, or a chained dwarf with nothing to drink)
    from planner_wells import usable_wells
    if not usable_wells(s):
        out.append("no usable well for the jail's water")
    if int(_traits(s).get("justice", 0) or 0) <= -50:
        out.append("the Justice slider is lenient")
    return out


def _chronic_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(I7c fix 5) The chronic cases one dwarf at a time, the worst first:
    off every post and the hospital labours; their own unmet needs, one a
    day in turn; the last resort behind its checks."""
    cases = chronic_cases(s, cfg)
    if not cases:
        return
    r = cases[0]
    name, year = r.get("name") or r["id"], int(r.get("year") or 0)
    stress = str(r.get("stress") or "").replace("_", " ")
    head = f"{name} threw {year} tantrums this year" + (f" ({stress})" if stress else "")
    if _l(r.get("posts")) or _l(r.get("medical")):
        posts = ", ".join(_post_words(p) for p in _l(r.get("posts"))) or "no post"
        proposals.append(Proposal("chronic_posts", {"type": "tantrum_step_down", "unit_id": r["id"], "medical": True},
                                  f"{head}: off every post ({posts}) and the hospital work, so no patient is in "
                                  "their hands", 1))
    acts = chronic_need_actions(s, cfg, r)
    if acts:
        need, action, words, is_order = acts[game_day(s) % len(acts)]
        proposals.append(Proposal("chronic_care", action, f"{head} and misses {need}: {words}", 3, is_order))
    untreated = [NEED_WORDS[n] for n in _l(r.get("unmet")) if n in NEED_WORDS]
    done = [a[0] for a in acts]
    # the last resort: their own solved cases, into a free chain, behind the checks
    ticks = sorted(t for t in _l(r.get("ticks")) if isinstance(t, int))
    now = abs_tick(s)
    k = cfg["chronic_tantrums"]
    last_resort = ""
    if (year >= cfg["chronic_convict_tantrums"] and len(ticks) >= k
            and now - ticks[k - 1] >= cfg["chronic_convict_after_days"] * TICKS_PER_DAY):
        why_not = _convict_blockers(s, cfg, r)
        if why_not:
            last_resort = f"; no conviction ({', '.join(why_not)})"
        else:
            proposals.append(Proposal("chronic_convict", {"type": "convict", "max": 1, "unit_id": r["id"],
                                                         "disorderly": True},
                                      f"{head}, still after {cfg['chronic_convict_after_days']}+ days of care: the last "
                                      "resort, one of their own disorderly-behaviour cases convicted (a free jail "
                                      "chain, a usable well, nobody "
                                      "wounded, no beating waiting)", 4))
            last_resort = "; the last resort: one of their own cases convicted"
    notes.append(f"chronic tantrum case{'s' if len(cases) > 1 else ''} ({len(cases)}): {head}; missing "
                 f"{', '.join(_l(r.get('unmet'))) or 'nothing the game lists'}: the AI "
                 + ("meets " + ", ".join(done) + " in turn" if done else "has no action for those")
                 + (f" ({'; '.join(untreated)})" if untreated else "") + last_resort
                 + (f"; next: {', '.join(str(c.get('name') or c['id']) for c in cases[1:3])}" if len(cases) > 1 else ""))


def _tantrum_rules(s: dict, memory, cfg: dict, proposals: list, notes: list) -> None:
    """Every rule here, in order (planner.py calls this once a cycle)."""
    _break_fights_report_rule(s, memory, cfg, proposals)
    if not tantrum_section(s):
        return
    _staff_tantrum_rule(s, cfg, proposals)
    _hospital_guard_rule(s, memory, cfg, proposals, notes)
    _chronic_rule(s, cfg, proposals, notes)
