"""(item5) The wounded who are up and working, put to bed for DF's doctors.

B, 24 Nov: Zutthan waited 126 days "for immobilize, dressing, surgery",
walking about and working, and died; the chief medical dwarf, two surgeons, a
doctor and the militia captain all walked about with infected wounds DF had
diagnosed years before and asked nothing for (needs_healthcare off: DF counts
them treated). DF's doctors treat a patient resting in a hospital bed, and
diagnose only one resting there. The bridge (lua/ai-health.lua bed_rest)
gives such a dwarf the special Rest job DFHack's dwarfvet gives an injured
animal: a patient DF asked a treatment for, and (a trial, one at a time,
undone when DF asks nothing) a heavy chronic infection made undiagnosed so DF
diagnoses it again. It never sends the last dwarf able to diagnose, and gives
the DIAGNOSE labour to the best healthy citizen when no healthy dwarf has it.

The report: infection.bed (lua/ai-health.lua bed_survey). Called from
planner.plan() under the infection section's gate.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal

__all__ = ["_bed_rest_rule", "rediag_allowed", "who_words"]

BLEEDS = 300       # df-structures: an infection load of 300 or more makes the dwarf bleed


def rediag_allowed(bed: dict, cfg: dict) -> bool:
    """The re-diagnosis trial: on in the config, and not after
    bed_rest_rediag_give_up failures with none helped (the bridge keeps the
    counts in the save)."""
    st = _d(bed.get("stats"))
    failed, helped = int(st.get("rediag_failed") or 0), int(st.get("rediag_helped") or 0)
    return bool(cfg["bed_rest_rediag"]) and not (failed >= cfg["bed_rest_rediag_give_up"] and helped == 0)


def who_words(w: dict) -> str:
    """One waiting dwarf: name, what DF asks (or the old infection), why he
    isn't in bed."""
    name = w.get("name") or w.get("id")
    needs = [str(x) for x in _l(w.get("needs"))]
    what = (f"needs {', '.join(needs[:3])}" if needs else f"old infection, load {w.get('load')}")
    return f"{name} ({what}{', a healer' if w.get('healer') else ''}): {w.get('why') or 'up'}"


def _bed_rest_rule(s: dict, cfg: dict, proposals: list | None, notes: list) -> None:
    """Who waits for bed rest and why (a note), and the bridge asked to put
    up to bed_rest_max to bed (and keep a healer) while beds are free, at most
    bed_rest_cap of the AI's sleepers at once, bed_rest_keep_free beds left
    for DF's own patients. Throttled a day (bed_rest_cooldown_ticks), raised
    while one bleeds from the infection."""
    inf = _d(s.get("infection"))
    bed = inf.get("bed")
    if inf.get("error") or not isinstance(bed, dict) or not bed:
        return                                   # an older bridge, or no report
    if bed.get("error"):
        notes.append(f"the bed-rest survey failed ({str(bed['error'])[:80]}): nobody up and working is put to bed")
        return
    treat, chronic = int(bed.get("treat_waiting") or 0), int(bed.get("rediag_waiting") or 0)
    rediag = rediag_allowed(bed, cfg)
    st = _d(bed.get("stats"))
    who = [w for w in _l(bed.get("who")) if isinstance(w, dict)]
    if treat or chronic:
        parts = []
        if treat:
            parts.append(f"{treat} wounded dwarf(s) DF asked a treatment for are up, not in a bed (DF's doctors treat "
                         "a patient resting in a hospital bed)")
        if chronic:
            parts.append(f"{chronic} with a heavy infection DF counts treated (every infected wound diagnosed long "
                         "ago, nothing asked)"
                         + ("" if rediag else f": the re-diagnosis trial is stopped ({int(st.get('rediag_failed') or 0)}"
                                              " failed, none helped)"))
        text = "; ".join(parts)
        if who:
            text += ": " + "; ".join(who_words(w) for w in who[:4])
        notes.append(text)
    healthy = bed.get("healthy_diagnosers")
    cand = _d(bed.get("healer_candidate"))
    healer = healthy == 0 and bool(cand)
    if healthy == 0:
        notes.append("no healthy dwarf able to diagnose (each one with the labour is a patient, resting or unable)"
                     + (": the AI gives the labour to the healthy citizen best at it" if cand
                        else ", and no healthy citizen can take it"))
    if proposals is None or not inf.get("hospital_zones"):
        return                                   # the hospital rules build one first
    ready = int(bed.get("ready_treat") or 0)
    if rediag and not int(bed.get("trials") or 0):
        ready += min(1, int(bed.get("ready_rediag") or 0))       # one trial at a time
    free = int(inf.get("free_beds") or 0)
    sleeping = int(bed.get("sleeping") or 0) + int(inf.get("sleeping") or 0)   # rest_infected's share the cap
    keep, cap = cfg["bed_rest_keep_free"], cfg["bed_rest_cap"]
    m = min(cfg["bed_rest_max"], ready, cap - sleeping, free - keep)
    if ready and m <= 0:
        notes.append(f"{ready} wounded dwarf(s) wait to be put to bed for the doctors: "
                     + (f"{free} hospital bed(s) free, {keep} kept for DF's own patients" if free - keep <= 0
                        else f"{sleeping} of the AI's sleepers in bed already (at most {cap})"))
    if m <= 0 and not healer:
        return
    bleeding = any(int(w.get("load") or 0) >= BLEEDS for w in who)
    asked = int(bed.get("ready_treat") or 0)
    names = [str(w.get("name") or w.get("id")).split(",")[0] for w in who][:2]
    why = []
    if m > 0:
        why.append(f"{treat + chronic} wounded dwarf(s) up and working, never treated in a bed"
                   + (f" ({', '.join(names)})" if names else "")
                   + f": up to {m} put to bed in the hospital for the doctors"
                   + (" (one heavy old infection diagnosed again, as a trial)" if rediag and asked < m else ""))
    if healer:
        why.append("nobody healthy can diagnose: the labour given to the healthy citizen best at it")
    prio = 1 if bleeding else 2 if (asked or healer) else 3
    proposals.append(Proposal("bed_rest", {"type": "bed_rest", "max": max(1, m), "cap": cap, "keep_free": keep,
                                           "rediag": rediag},
                              "; ".join(why), prio))
