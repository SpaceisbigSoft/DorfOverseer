"""(r11 n1, the player 22 Nov 01:43) Office holders changed for better ones.

"yes [a tiny fort lets an office holder double as messenger] but it should be
updated when a suitable dwarf is free, additionally the office holders should
be changed out if a vastly more suited dwarf is available in general."

The interim messenger itself is appointed by the messenger rule
(planner_world._messenger_rule, `appoint` with `interim`). This rule swaps:

  * the interim messenger out (the messenger also holds another office) as
    soon as a suitable free citizen exists (the bridge's filters: no office,
    no soldier, staff, patient, wounded, mother of a baby, child, mood); never
    while the messenger is away (an army's roll, off the map, a Make contact
    run being sent, a Diplomacy mission out);
  * a civilian office's holder (manager, bookkeeper, broker, chief medical
    dwarf, sheriff, captain of the guard, messenger) for a free citizen
    vastly better at the office's skills: the candidate's skill score (the
    first skill counts double, lua/ai-nobles.lua skill_score) at least
    max(holder + n1_swap_margin_add, holder x n1_swap_margin_factor). Never a
    post DF fills (elected, inherited, replaced), a holder in a strange mood,
    away, or at a job of the office (the broker while a caravan is here).

Both: no threat that can reach the dwarves, no siege, no crisis; one swap a
day fort-wide (n1_swap_gap_days) and one a season per office
(office_swap_cooldown_ticks, by cooldown_key's office_swap:<CODE>). The
bridge re-checks everything and swaps all-or-nothing (lua/ai-nobles-swap.lua).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, abs_tick, player_rules
from planner_traffic import _danger_near

__all__ = ["_office_swap_rule", "swap_needed", "SWAP_ORDER", "OFFICE_WORDS"]

# the most needed office first: one swap a day goes where it matters most
SWAP_ORDER = ("MANAGER", "CHIEF_MEDICAL_DWARF", "BROKER", "BOOKKEEPER", "SHERIFF", "CAPTAIN_OF_THE_GUARD", "MESSENGER")
OFFICE_WORDS = {"MANAGER": "manager", "BOOKKEEPER": "bookkeeper", "BROKER": "broker",
                "CHIEF_MEDICAL_DWARF": "chief medical dwarf", "SHERIFF": "sheriff",
                "CAPTAIN_OF_THE_GUARD": "captain of the guard", "MESSENGER": "messenger"}


def swap_needed(held: int, cfg: dict) -> int:
    """The skill score a free citizen needs to replace a holder of score `held`
    (lua/ai-nobles-swap.lua needed(), the same sum)."""
    import math
    held = int(held or 0)
    return max(held + int(cfg["n1_swap_margin_add"]), math.ceil(held * float(cfg["n1_swap_margin_factor"])))


def _last_swap(memory) -> int | None:
    fired = _d(getattr(memory, "last_fired", None)) if memory is not None else {}
    ticks = [t for k, t in fired.items() if str(k).startswith("office_swap") and isinstance(t, int)]
    return max(ticks) if ticks else None


def _messenger_busy(s: dict, ms: dict) -> str | None:
    """Why the messenger may not be swapped now: away, a run being sent, a
    Diplomacy mission out (planner_world._messenger_out)."""
    if ms.get("away"):
        return str(ms["away"])
    missions = _d(s.get("missions"))
    if _d(_d(missions.get("send")).get("running")):
        return "a mission is being sent"
    from planner_world import _messenger_out
    if _messenger_out(missions):
        return "a Diplomacy mission is out"
    return None


def _office_swap_rule(s: dict, cfg: dict, proposals: list, notes: list, memory=None) -> None:
    rules = player_rules(s)
    if not rules["appoint_nobles"] or not cfg.get("n1_office_swaps", True):
        return
    offices = _d(s.get("offices"))
    if not offices or "error" in offices or "offices" in _d(s.get("_errors")):
        return
    if _danger_near(s):
        return                       # a threat that can reach the dwarves, or a siege: not now
    if memory is not None and _d(getattr(memory, "crisis", None)).get("since"):
        return                       # a crisis: the fort's offices stay as they are
    now = abs_tick(s)
    last = _last_swap(memory)
    if isinstance(now, int) and last is not None and 0 <= now - last < int(cfg["n1_swap_gap_days"]) * TICKS_PER_DAY:
        return                       # one swap a day, fort-wide
    fired = _d(getattr(memory, "last_fired", None)) if memory is not None else {}

    def cooled(code: str) -> bool:
        t = fired.get(f"office_swap:{code}")
        return not (isinstance(now, int) and isinstance(t, int) and 0 <= now - t < int(cfg["office_swap_cooldown_ticks"]))

    ms = _d(offices.get("messenger"))
    # the interim messenger out: any suitable free citizen will do
    if ms.get("interim") and ms.get("free_unit") is not None:
        busy = _messenger_busy(s, ms)
        if busy:
            notes.append(f"{ms.get('held_by') or 'the interim messenger'} doubles as messenger; "
                         f"{ms.get('free_name') or 'a free dwarf'} could take over, once the messenger is back ({busy})")
        else:
            proposals.append(Proposal("office_swap", {"type": "appoint", "office": "MESSENGER", "replace": True,
                                                      "interim_out": True},
                                      f"{ms.get('held_by') or 'an office holder'} doubles as messenger for now (they "
                                      f"hold another office); {ms.get('free_name') or 'a free dwarf'} is free and "
                                      "suitable: they take the messenger's post", 4))
            return
    swap = _d(offices.get("swap"))
    for code in SWAP_ORDER:
        o = _d(swap.get(code))
        if not o or o.get("fixed") or o.get("cand_unit") is None or o.get("holder_unit") is None:
            continue
        hs, cs = int(o.get("holder_score") or 0), int(o.get("cand_score") or 0)
        need = swap_needed(hs, cfg)
        if cs < need or not cooled(code):
            continue
        busy = o.get("busy") or (_messenger_busy(s, ms) if code == "MESSENGER" else None)
        word = OFFICE_WORDS.get(code, code.lower())
        if busy:
            notes.append(f"{o.get('cand')} would make a far better {word} than {o.get('holder')} "
                         f"(skill {hs} -> {cs}); not now: {busy}")
            continue
        proposals.append(Proposal("office_swap", {"type": "appoint", "office": code, "replace": True,
                                                  "margin_add": int(cfg["n1_swap_margin_add"]),
                                                  "margin_factor": float(cfg["n1_swap_margin_factor"])},
                                  f"{o.get('cand')} is far better suited as {word} than {o.get('holder')} "
                                  f"(skill {hs} -> {cs}, {need} needed): {o.get('cand')} takes the post", 5))
        return
