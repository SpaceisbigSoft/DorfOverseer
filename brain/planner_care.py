"""(0.104.168) Disease and care, and the offices the dead held.

Teacheroar, 1 Nov: 142 citizens, 77 walking about with infected wounds, two
with a treatment asked, twelve hospital staff with little to do, and dwarves
dying of infection months after the fights. In DF a doctor treats only a
diagnosed patient, and a dwarf up and working is never diagnosed: the bridge
(lua/ai-health.lua) puts the idle infected to bed in the hospital (as DFHack's
dwarfvet does for animals) and the doctors take it from there. A hospital
gets a second doctor's post when the treatments asked outrun the dwarves who
can diagnose. Infections are no contagion in DF (each comes from a dwarf's
own wounds), so nobody is kept apart.

And the spirals' dead held offices: the militia commander and a squad's
captain are filled again (lua/ai-nobles.lua), the elected, inherited and
monarch-appointed ones left to DF.
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, ask_player, care_waiting, player_rules

__all__ = ["_infection_rule", "_doctor_post_rule", "_offices_refill_rule", "MILITARY_OFFICES"]

MILITARY_OFFICES = ("MILITIA_COMMANDER", "MILITIA_CAPTAIN")


def _infection_rule(s: dict, cfg: dict, proposals: list, notes: list) -> None:
    """Who walks about infected, why nobody treats them, and the idle ones
    put to bed in a free hospital bed (the worst first), unless DF kept none
    of the last ones sent resting."""
    inf = _d(s.get("infection"))
    n = inf.get("infected")
    if inf.get("error") or not isinstance(n, int) or n <= 0:
        return
    untreated, bleeding = int(inf.get("untreated") or 0), int(inf.get("bleeding") or 0)
    worst = [w for w in _l(inf.get("worst")) if isinstance(w, dict)]
    text = (f"{n} citizens have infected wounds, {untreated} with no treatment asked (a doctor treats a dwarf "
            "only once diagnosed, and one up and working never is)")
    if bleeding:
        text += f"; {bleeding} bleed from the infection (load 300 or more): they die of it unless treated"
    if worst:
        text += "; worst: " + ", ".join(f"{w.get('name') or w.get('id')} ({w.get('load')})" for w in worst[:3])
    notes.append(text)
    if inf.get("cleaners") == 0:
        ask_player(notes, f"{n} dwarves have infected wounds and no civilian has the cleaning labour: patients' "
                          "wounds are cleaned (with soap and water) by dwarves with that labour")
    if proposals is None or not untreated:
        return
    sent, stayed, asked = (int(inf.get(k) or 0) for k in ("sent", "stayed", "asked"))
    if sent >= cfg["infected_rest_give_up"] and stayed == 0 and asked == 0:
        notes.append(f"the {sent} infected dwarves the AI put to bed in the hospital did not stay there and "
                     "were not diagnosed: it waits a week before trying again")
        return
    if not inf.get("hospital_zones"):
        return                                 # the hospital rules build one
    if inf.get("diagnosers") == 0:
        ask_player(notes, f"{untreated} infected dwarves wait and nobody outside the military can diagnose "
                          "(the hospital's diagnostician or doctor posts)")
        return
    free = int(inf.get("free_beds") or 0)
    idle = int(inf.get("idle_untreated") or 0)
    if not free:
        notes.append(f"{untreated} infected dwarves wait for the doctors and every hospital bed is taken")
        return
    if not idle:
        return
    m = min(cfg["infected_rest_max"], free, idle)
    proposals.append(Proposal("infected_rest", {"type": "rest_infected", "max": m},
                              f"{untreated} dwarves walk about with infected wounds DF asks no treatment for"
                              + (f" ({bleeding} bleeding from it)" if bleeding else "")
                              + f" and {free} hospital bed(s) are free: the {m} worst of the idle put to bed "
                                "there, for the doctors to diagnose and clean", 2 if bleeding else 4))


def _doctor_post_rule(s: dict, cfg: dict, proposals: list) -> None:
    """More treatments asked than the doctors can give: a hospital whose
    posts are all filled gets a second doctor's post (a doctor does every
    treatment); the staffing rule seats the dwarf best at it."""
    if proposals is None:
        return
    waiting = care_waiting(s)
    diag = _d(s.get("infection")).get("diagnosers")
    if not isinstance(diag, int):        # an older bridge: the hospitals' staff who diagnose
        diag = sum(1 for h in _l(_d(s.get("health")).get("hospital")) if isinstance(h, dict)
                   for st in _l(h.get("staff")) if "DIAGNOSE" in _l(_d(st).get("labors")))
    if waiting <= cfg["doctor_post_per_diagnoser"] * max(1, diag):
        return
    for e in _l(_d(s.get("locations")).get("list")):
        if not isinstance(e, dict) or e.get("type") != "HOSPITAL" or e.get("id") is None:
            continue
        jobs = _d(e.get("jobs"))
        if any(int(_d(j).get("filled") or 0) < int(_d(j).get("posts") or 0) for j in jobs.values()):
            continue                         # a post still empty: the staffing rule fills it first
        if int(_d(jobs.get("DOCTOR")).get("posts") or 0) >= 2:
            continue
        proposals.append(Proposal("doctor_post", {"type": "add_doctor_post", "location_id": e["id"]},
                                  f"{waiting} dwarves wait for a treatment and {diag} can diagnose: "
                                  "a second doctor's post at the hospital", 3))
        return


def _offices_refill_rule(s: dict, cfg: dict, notes: list, proposals: list) -> None:
    """The militia commander's office, and a captain's whose squad has lost
    him, filled again (the commander first: he appoints the captains); the
    other offices the fort could fill and the AI doesn't are said. Elected
    (the mayor), inherited and monarch-appointed offices are DF's."""
    offices = _d(_d(s.get("offices")).get("offices"))
    if not offices:
        return
    appoint = player_rules(s)["appoint_nobles"] and proposals is not None
    cmd = _d(offices.get("MILITIA_COMMANDER"))
    cmd_vacant = bool(cmd) and int(cmd.get("vacant") or 0) > 0 and not _l(cmd.get("held"))
    if appoint and cmd_vacant and cmd.get("appointable") is not False:
        proposals.append(Proposal("appoint", {"type": "appoint", "office": "MILITIA_COMMANDER"},
                                  "nobody is militia commander (the squads' head, who appoints the captains): "
                                  "appoint the best-suited dwarf", 3))
        return
    cap = _d(offices.get("MILITIA_CAPTAIN"))
    if (appoint and int(cap.get("vacant_squad") or 0) > 0 and cap.get("appointable") is not False
            and not cmd_vacant):
        proposals.append(Proposal("appoint", {"type": "appoint", "office": "MILITIA_CAPTAIN"},
                                  f"{cap['vacant_squad']} squad(s) have lost their captain: appoint the "
                                  "best-suited dwarf to lead", 3))
        return
    left = sorted(code for code, o in offices.items()
                  if isinstance(o, dict) and o.get("appointable") is True and not o.get("ai")
                  and int(o.get("vacant") or 0) > 0 and not _l(o.get("held")))
    if left:
        notes.append("the fort may fill these offices and the AI doesn't: "
                     + ", ".join(c.lower().replace("_", " ") for c in left) + " (the nobles screen)")
