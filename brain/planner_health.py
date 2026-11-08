"""planner_health: the sick, the wounded and the distraught (split out of
planner_society in 0.105.25, 13c): who waits for care and how long, doctors
sent to patients, the hospital burrow, the calm burrow for tantrums (and the
tantrums remembered), traction benches, staff posts in the hospital, library
and tavern. planner_society re-exports every name here. (The infected, the
doctors' posts and offices refilled are in planner_care.)"""

from __future__ import annotations

import re
from digest import _d, _l
from planner_core import *  # noqa: F401,F403

__all__ = ["patient_waits", "_health_rules", "_doctor_patient_rule", "_hospital_burrow_rule", "_calm_burrow_rule", "TANTRUM_KEEP", "note_tantrums", "POST_LABORS", "STAFF_POSTS", "STAFF_MAX", "_traction_rule", "_staff_rule"]


def patient_waits(s: dict, memory, now: int) -> dict:
    """Since when each patient with a treatment asked has waited: the booked
    day, or now for a new one (0.104.78: only while a treatment is asked)."""
    patients = [p for p in _l(_d(s.get("health")).get("patients")) if isinstance(p, dict) and p.get("id") is not None]
    seen = {str(p["id"]) for p in patients if _l(p.get("needs"))}
    # (0.104.133) every patient waiting, not the 30 listed: one off the list
    # lost the day their wait began and started again from "now"
    ids = _d(s.get("health")).get("waiting_ids")
    if isinstance(ids, list):
        seen |= {str(i) for i in ids if isinstance(i, int)}
    since = {k: v for k, v in _d(getattr(memory, "patient_since", None)).items() if k in seen and isinstance(v, int)}
    for k in seen:
        since.setdefault(k, now)
    return since


def _health_rules(s: dict, memory, cfg: dict, notes: list) -> None:
    """Phase 12 (health over years): each patient's wait is tracked
    (memory.patient_since); one who has waited health_wait_days, or an
    infected wound, is said, with why it may be (no hospital, no chief
    medical dwarf, no soap). The care itself is DF's doctors' work: the AI
    stocks the hospital and appoints the chief medical dwarf elsewhere."""
    h = _d(s.get("health"))
    if not h or h.get("error"):
        return
    now = abs_tick(s)
    patients = [p for p in _l(h.get("patients")) if isinstance(p, dict) and p.get("id") is not None]
    # (0.104.78) the wait runs only while a treatment waits: a patient listed
    # for years with an old infection and nothing asked (Enxah's chief medical
    # dwarf, "6215 days") counted from the first day he was listed
    since = patient_waits(s, memory, now)     # (0.104.81) booked in note_cycle: plan() reads memory only
    hospital = _d(_d(s.get("locations")).get("count")).get("HOSPITAL", 0)
    doctor = not ("CHIEF_MEDICAL_DWARF" in _l(_d(s.get("society")).get("vacant")))
    soap = _d(s.get("supplies")).get("soap") or 0
    why = []
    if not hospital:
        why.append("there is no hospital")
    if not doctor:
        why.append("nobody is chief medical dwarf")
    long = []
    for p in patients:
        if str(p["id"]) not in since:
            continue
        days = (now - since[str(p["id"])]) // TICKS_PER_DAY
        # (0.88.3) only those with a treatment still waiting (live: three dwarves
        # with infected wounds, up and working with nothing left to do, were
        # "waiting 538 days for care" as Needs you)
        if days >= cfg["health_wait_days"] and _l(p.get("needs")):
            long.append((days, p))
    long.sort(key=lambda x: -x[0])
    if long:
        who = "; ".join(f"{p.get('name') or p['id']} {d} days"
                        + (f" (needs {', '.join(map(str, _l(p.get('needs'))[:3]))})" if p.get("needs") else "")
                        for d, p in long[:3])
        n_long = len(long)
        if isinstance(_d(s.get("health")).get("waiting_ids"), list):    # (0.104.133) every one, not the listed
            n_long = sum(1 for k, v in since.items() if (now - v) // TICKS_PER_DAY >= cfg["health_wait_days"])
        ask_player(notes, f"{n_long} dwarves have waited a long time for care: {who}"
                   + (": " + " and ".join(why) if why
                      else ": check the doctors' labours (diagnose, surgery, suturing, bone setting)"))
    # (0.104.122) the full count (the list stops at 30) and the hospital's own
    # bars (it said "28 ... no soap" with 112 infected and 5 bars kept there)
    n_inf = _d(s.get("health")).get("infected")
    n_inf = n_inf if isinstance(n_inf, int) else sum(1 for p in patients if p.get("infected"))
    hosp = _location(s, "HOSPITAL")
    if hosp is not None:
        soap += int(_d(hosp.get("have")).get("soap") or 0) // LOCATION_UNITS["soap"]
    if n_inf and not soap:
        ask_player(notes, f"{n_inf} dwarves have infected wounds and the fort has no soap "
                   "(wounds are cleaned with soap)")


def _doctor_patient_rule(s: dict, proposals: list) -> None:
    """(0.104.111, the 38-year soak) Teacheroar's surgeon and bone doctor lay
    in the hospital themselves, holding their posts, while five dwarves waited
    450-820 days for care. A hospital post held by a dwarf being treated (in
    the hospital, or waiting for a treatment) is given back; the staffing
    rule then gives it to the best healthy dwarf (wounded ones are passed over
    since 0.104.111). One a cycle."""
    h = _d(s.get("health"))
    sick = {p.get("id"): p for p in _l(h.get("patients"))
            if isinstance(p, dict) and (p.get("in_hospital") or _l(p.get("needs")))}
    if not sick:
        return
    for hosp in _l(h.get("hospital")):
        if not isinstance(hosp, dict) or not isinstance(hosp.get("id"), int):
            continue
        for st in _l(hosp.get("staff")):
            uid = _d(st).get("unit_id")
            if uid in sick:
                p = sick[uid]
                post = str(_d(st).get("post") or "post").lower().replace("_", " ")
                proposals.append(Proposal("doctor_patient", {"type": "vacate_post", "location_id": hosp["id"],
                                                             "unit_id": uid},
                                          f"the hospital's {post}, {p.get('name') or uid}, is a patient"
                                          + (f" (needs {', '.join(map(str, _l(p.get('needs'))[:3]))})"
                                             if _l(p.get("needs")) else "")
                                          + ": the post goes to a healthy dwarf", 2))
                return


def _hospital_burrow_rule(s: dict, cfg: dict, proposals: list, memory=None) -> None:
    """(0.104.167) Teacheroar, 1 Nov: five of seven citizens killed by
    citizens in 26 minutes were patients waiting for care, walking the halls,
    struck down by dwarves in tantrums. The player's word: keep the wounded
    inside the hospitals. The bridge keeps the patients DF asks a treatment
    for in a burrow over the hospitals' zones and the nearest drink and food
    they can walk to (never one without drink: then nobody), and lets the
    healed out; the planner asks while a hospital exists and patients walk
    outside it, or while the burrow has members (to let them out). Always
    (patients are safer inside), first of all while the fort is in crisis or
    its own are killing each other.

    (review) Never members left behind: with the rule switched off, the
    burrow's status unreadable (or the whole society section), or no
    hospital zone left, the bridge is asked to let everyone out (`release`);
    the bridge also re-checks them itself at every report. Called outside
    the health section's gate (planner.py): a failed health section never
    freezes the members."""
    if proposals is None:
        return
    soc = _d(s.get("society"))
    hb = _d(soc.get("hospital_burrow"))
    # a failed section arrives emptied, its error in s["_errors"] (digest.normalize)
    soc_err = soc.get("error") or _d(s.get("_errors")).get("society")
    err = hb.get("error") or soc_err
    members = int(hb.get("members") or 0) if not err else 0
    release = {"type": "hospital_burrow", "release": True}
    if not player_rules(s).get("hospital_burrow", True):
        if members or err:
            proposals.append(Proposal("hospital_burrow", release, "the hospital burrow is switched off in the Rules: "
                                      f"{members or 'its'} patient(s) let out", 2))
        return
    if err:
        proposals.append(Proposal("hospital_burrow", release,
                                  "the hospital burrow's status can't be read (" + str(err)[:80]
                                  + "): its patients let out, so none is kept from drink unseen", 2))
        return
    h = _d(s.get("health"))
    zones = sum(len(_l(_d(x).get("zones"))) for x in _l(h.get("hospital")))
    if not zones and not int(hb.get("hospital_zones") or 0):
        if members:
            proposals.append(Proposal("hospital_burrow", release,
                                      f"no hospital zone left: the {members} patient(s) kept in let out", 2))
        return
    outside = hb.get("outside")
    if not isinstance(outside, int):            # an older bridge: the listed patients outside the hospital
        outside = sum(1 for p in _l(h.get("patients"))
                      if isinstance(p, dict) and _l(p.get("needs")) and not p.get("in_hospital"))
    if not outside and not members:
        return
    now_ = abs_tick(s)
    fighting = any(isinstance(t, int) and 0 <= now_ - t < cfg["break_fights_days"] * TICKS_PER_DAY
                   for t in _l(getattr(memory, "fight_deaths", None)))
    crisis = bool(_d(getattr(memory, "crisis", None)).get("why"))
    proposals.append(Proposal("hospital_burrow", {"type": "hospital_burrow", "max": cfg["hospital_burrow_max"],
                                                  "per": cfg["hospital_burrow_per"],
                                                  "days": cfg["hospital_burrow_days"]},
                              (f"{outside} patient(s) walking outside the hospital" if outside else "no patient outside")
                              + (f", {members} kept in" if members else "")
                              + (" while the fort's own kill each other" if fighting else "")
                              + ": the wounded kept in the hospital (with drink and food they can reach), "
                                "the healed let out",
                              2 if (fighting or crisis) else 4))


def _calm_burrow_rule(s: dict, cfg: dict, proposals: list, notes: list | None = None, memory=None) -> None:
    """(0.104.169) Teacheroar, 1 Nov 18:38-18:53: five citizens killed by
    citizens, three of them patients waiting for care, the killers in a
    tantrum. The player's word: keep a dwarf in a tantrum away from the
    patients and the others until they calm down. The bridge keeps each
    citizen in a tantrum in a burrow of their own over a free bedroom far
    from the hospitals and the nearest drink they can walk to, and lets them
    out once calm, after calm_burrow_days, thirsty or hungry (it re-checks
    them at every report). The planner asks while a tantrum walks free
    (`free`), or while the burrows hold members (to let them out).

    Whether DF keeps a tantrum's own acts inside a burrow is not known (the
    wiki is silent): the report counts each member seen inside or outside
    their burrow, and the rule says so once the count says it doesn't hold.

    (review, as the hospital burrow) Never members left behind: the rule
    switched off or the status unreadable, the bridge is asked to let
    everyone out (`release`). Never the jail, a lock or a chain."""
    if proposals is None:
        return
    soc = _d(s.get("society"))
    if "calm_burrow" not in soc and not soc.get("error") and not _d(s.get("_errors")).get("society"):
        return                                   # an older bridge: nothing to ask
    cb = _d(soc.get("calm_burrow"))
    err = cb.get("error") or soc.get("error") or _d(s.get("_errors")).get("society")
    members = int(cb.get("members") or 0) if not err else 0
    release = {"type": "calm_burrow", "release": True}
    if not player_rules(s).get("calm_burrow", True):
        if members or err:
            proposals.append(Proposal("calm_burrow", release, "the calm-down burrows are switched off in the Rules: "
                                      f"{members or 'their'} dwarf(s) let out", 2))
        return
    if err:
        proposals.append(Proposal("calm_burrow", release,
                                  "the calm-down burrows' status can't be read (" + str(err)[:80]
                                  + "): their dwarves let out, so none is kept from drink unseen", 2))
        return
    seen_in, seen_out = int(cb.get("seen_in") or 0), int(cb.get("seen_out") or 0)
    seen = seen_in + seen_out
    share = seen_out / seen if seen else 0.0
    # (0.105.24) the measure has spoken: 2-5 Nov, five forts, members seen
    # outside their burrow 25/25, 92/92, 29/29, 100/103 and 20/20 times (344 of
    # 349) while the rule fired ~940 times; tantrum kills went on (citizens
    # killed by citizens in a tantrum: A 9, B 3, C 10, E 22, F 5). DF doesn't
    # hold a tantrum to a burrow: the lever is retired for this fort (its
    # members let out), and the effort goes to the causes of the stress.
    if seen >= cfg["calm_burrow_retire_after"] and share >= cfg["calm_burrow_retire_share"]:
        if notes is not None:
            notes.append(f"calm burrows retired: dwarves in a tantrum were seen outside their burrow {seen_out} of "
                         f"{seen} times: DF doesn't hold a tantrum to a burrow")
        if members:
            proposals.append(Proposal("calm_burrow", release,
                                      f"the calm-down burrows don't hold a tantrum (seen outside {seen_out} of {seen} "
                                      f"times): their {members} dwarf(s) let out, the burrows retired", 2))
        return
    if notes is not None and seen >= cfg["calm_burrow_judge_after"]:
        if share >= cfg["calm_burrow_outside_share"]:
            notes.append(f"calm burrows: dwarves in a tantrum were seen outside their burrow {seen_out} of "
                         f"{seen} times: DF doesn't seem to hold a tantrum to a burrow")
    free = int(cb.get("free") or 0)
    if not free and not members:
        return
    why = cb.get("why")
    if not members and why and free:
        # the last call found no room (or no drink): say so, and ask again after the cooldown
        if notes is not None:
            notes.append(f"{free} citizen(s) in a tantrum walk free: {why}")
    proposals.append(Proposal("calm_burrow", {"type": "calm_burrow", "max": cfg["calm_burrow_max"],
                                              "days": cfg["calm_burrow_days"]},
                              (f"{free} citizen(s) in a tantrum walk free" if free else "no tantrum walks free")
                              + (f", {members} kept apart" if members else "")
                              + ": each kept in a free bedroom away from the patients (with drink in reach) "
                                "until calm, the calm let out",
                              0 if free else 2))


TANTRUM_KEEP = 60           # tantrums remembered (each [tick, who])


def note_tantrums(state: dict, memory, events: list) -> int:
    """(0.104.31) Tantrums seen in the game's announcements, one a dwarf a
    day (the game repeats one tantrum in many lines). Returns how many new."""
    now = abs_tick(state)
    day = now // TICKS_PER_DAY
    have = {(int(t[0]) // TICKS_PER_DAY, str(t[1])) for t in memory.tantrums
            if isinstance(t, list) and len(t) == 2 and isinstance(t[0], int)}
    n = 0
    for e in events or []:
        if not isinstance(e, dict) or e.get("kind") != "report" or e.get("topic") != "tantrum":
            continue
        text = " ".join(str(e.get("text") or "").split())
        if "cancels" in text:
            continue                    # "... cancels X: Throwing tantrum." repeats the same one
        who = text.split(" is throwing")[0].split(" throws")[0][:30]
        if (day, who) in have:
            continue
        have.add((day, who))
        memory.tantrums.append([now, who])
        n += 1
    memory.tantrums = [t for t in memory.tantrums if isinstance(t, list) and len(t) == 2][-TANTRUM_KEEP:]
    return n


# (0.87.3) the labours each post needs (lua/ai-society.lua POST_LABORS)
POST_LABORS = {"DOCTOR": ("DIAGNOSE", "SURGERY", "BONE_SETTING", "SUTURING", "DRESSING_WOUNDS"),
               "DIAGNOSTICIAN": ("DIAGNOSE",), "SURGEON": ("SURGERY", "SUTURING"), "BONE_DOCTOR": ("BONE_SETTING",)}


# (0.84) posts at locations the AI fills, in this order, and how many of each
STAFF_POSTS = {"HOSPITAL": ("DIAGNOSTICIAN", "DOCTOR", "SURGEON", "BONE_DOCTOR"), "LIBRARY": ("SCRIBE",),
               "INN_TAVERN": ("TAVERN_KEEPER",)}


STAFF_MAX = {"SCRIBE": 2, "TAVERN_KEEPER": 2, "DIAGNOSTICIAN": 2, "DOCTOR": 2, "SURGEON": 2, "BONE_DOCTOR": 2}


def _traction_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """(0.88) A hospital wants a traction bench for broken bones that need
    traction (DF wiki, Hospital; region2's had beds, chests and a table, no
    bench). A free bench goes into the hospital zone with the most beds; with
    none, one is made at a Mechanic's workshop from a table, a mechanism and a
    rope or chain, the missing part ordered first."""
    sup = _d(s.get("supplies"))
    if "traction_benches" not in sup:
        return
    for h in _l(_d(s.get("health")).get("hospital")):
        zones = [z for z in _l(_d(h).get("zones")) if isinstance(z, dict) and z.get("id") is not None]
        if not zones:
            continue
        have = sum(max(int(z.get("traction") or 0), int(z.get("traction_planned") or 0)) for z in zones)
        if have >= cfg["hospital_traction"]:
            continue
        zone = max(zones, key=lambda z: int(z.get("beds") or 0))
        if int(sup.get("traction_benches") or 0) > 0:
            proposals.append(Proposal("traction", {"type": "place_in_zone", "zone_id": zone["id"],
                                                   "what": "traction_bench"},
                                      "the hospital has no traction bench (broken bones that need traction "
                                      "wait without one): put one in", 5))
            return
        if queued(s, {"traction_bench"}):
            return
        b = s["buildings"]
        if not _has_shop(b, "Mechanics"):
            notes.append("a traction bench for the hospital needs a Mechanic's workshop")
            return
        st = s["stocks"]
        part = None
        if not int(sup.get("tables") or 0) and not queued(s, {"wooden_table", "stone_table"}):
            part = ("stone_table", "a table")
        elif not free_stock(s, "mechanisms") and not queued(s, {"mechanisms"}):
            part = ("mechanisms", "a mechanism")
        elif not int(sup.get("ropes") or free_stock(s, "chains") or 0) and not queued(s, {"cloth_rope"}):
            part = ("cloth_rope", "a rope") if int(st.get("cloth") or 0) else None
            if part is None:
                notes.append("a traction bench for the hospital waits for a rope or chain (no cloth for a rope)")
                return
        if part:
            proposals.append(Proposal("traction_parts", {"type": "work_order", "recipe": part[0], "amount": 1},
                                      f"a traction bench for the hospital needs {part[1]}: make one", 6, True))
        else:
            proposals.append(Proposal("traction_parts", {"type": "work_order", "recipe": "traction_bench", "amount": 1},
                                      "the hospital has no traction bench: make one at the Mechanic's workshop "
                                      "(a table, a mechanism, a rope)", 6, True))
        return


def _staff_rule(s: dict, cfg: dict, proposals: list) -> None:
    """Vacant posts at the fort's locations (the bridge's `locations.list`):
    a hospital's diagnostician, doctor, surgeon and bone doctor first (urgent
    while someone needs care: region2's patients waited 130 days), then a
    library's scribes and a tavern's keeper; one post a cycle (ai-society
    staff_location picks the dwarf best at the trade)."""
    patients = int(_d(s.get("dwarves")).get("needs_medical_care") or 0)
    # (0.87.3) the hospital's staff without their post's labours (live: the
    # surgeon, bone doctor and doctor the AI seated had none, and a dwarf
    # needing a bone set waited 355 days): given first
    for h in _l(_d(s.get("health")).get("hospital")):
        if not isinstance(h, dict) or h.get("id") is None:
            continue
        short = [st.get("post") for st in _l(h.get("staff")) if isinstance(st, dict)
                 and set(POST_LABORS.get(st.get("post"), ())) - set(_l(st.get("labors")))]
        if short:
            proposals.append(Proposal("staff", {"type": "staff_labors", "location_id": h["id"]},
                                      f"the hospital's {', '.join(str(x).lower().replace('_', ' ') for x in short)} "
                                      "can't do their work (the post's labours are off)"
                                      + (f" and {patients} need care" if patients else "")
                                      + ": turn them on", 2 if patients else 4))
            return
    # (0.85) posts DF hasn't made yet (it makes them when the location's posts
    # screen is opened): the AI makes them as the game does, then fills them.
    # A library's scribes only once it has paper or books (they copy and write).
    order = sorted((e for e in _l(_d(s.get("locations")).get("list")) if isinstance(e, dict)),
                   key=lambda e: list(STAFF_POSTS).index(e.get("type")) if e.get("type") in STAFF_POSTS else 9)
    for e in order:
        if e.get("type") not in STAFF_POSTS or e.get("id") is None:
            continue
        if e["type"] == "LIBRARY" and not (e.get("books") or _d(e.get("have")).get("paper")):
            continue
        missing = [k for k in STAFF_POSTS[e["type"]] if k not in _d(e.get("jobs"))]
        if missing:
            hosp = e["type"] == "HOSPITAL"
            proposals.append(Proposal("staff", {"type": "add_posts", "location_id": e["id"], "posts": missing},
                                      f"the {e['type'].lower().replace('_', ' ')} has no post for "
                                      f"{', '.join(k.lower().replace('_', ' ') for k in missing)}"
                                      + (f" and {patients} need care" if hosp and patients else "")
                                      + ": make the posts (as its location screen does)", 2 if hosp and patients else 5))
            return
    for e in order:
        jobs = _d(e.get("jobs"))
        for post in STAFF_POSTS.get(e.get("type"), ()):
            j = _d(jobs.get(post))
            posts, filled = int(j.get("posts") or 0), int(j.get("filled") or 0)
            if filled < min(posts, STAFF_MAX.get(post, posts)):
                hosp = e.get("type") == "HOSPITAL"
                what = post.lower().replace("_", " ")
                proposals.append(Proposal("staff", {"type": "staff_location", "location_id": e.get("id"), "post": post},
                                          f"the {e.get('type', '').lower().replace('_', ' ')} has no {what}"
                                          + (f" ({filled} of {posts} posts filled)" if filled else "")
                                          + (f" and {patients} need care" if hosp and patients else "")
                                          + f": give the post to the dwarf best at it", 2 if hosp and patients else 5))
                return
