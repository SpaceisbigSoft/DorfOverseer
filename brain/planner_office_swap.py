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
    dwarf, messenger; (r11 n1 fixes) not the sheriff or the captain of the
    guard, whose posts lead the fortress guard squad) for a free citizen
    vastly better at the office's skills: the candidate's skill score (the
    first skill counts double, lua/ai-nobles.lua skill_score) at least
    max(holder + n1_swap_margin_add, holder x n1_swap_margin_factor). Never a
    post DF fills (elected, inherited, replaced), a holder in a strange mood,
    away, or at a job of the office (the broker while a caravan is here).

Both: no threat that can reach the dwarves, no siege, no crisis; one swap a
day fort-wide (n1_swap_gap_days) and one a season per office
(office_swap_cooldown_ticks, by cooldown_key's office_swap:<CODE>). The
bridge re-checks everything and swaps all-or-nothing (lua/ai-nobles-swap.lua).

(r11 n1 fixes) A swap the bridge refused waits its back-off for that office
only (refusal_key adds the office); a refused or waiting interim swap-out
lets the better-holder swaps through; no messenger swap while the missions
report can't be read; a waiting swap's note is said once a day or when its
reason changes (memory.world_seen["swap_said"]).
"""

from __future__ import annotations

from digest import _d, _l
from planner_core import Proposal, TICKS_PER_DAY, _refused_wait, abs_tick, player_rules
from planner_traffic import _danger_near

__all__ = ["_office_swap_rule", "swap_needed", "SWAP_ORDER", "OFFICE_WORDS"]

# the most needed office first: one swap a day goes where it matters most
SWAP_ORDER = ("MANAGER", "CHIEF_MEDICAL_DWARF", "BROKER", "BOOKKEEPER", "MESSENGER")
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
    raw = s.get("missions")
    if "missions" in _d(s.get("_errors")) or not isinstance(raw, dict) or "error" in raw:
        return "the missions report could not be read"
    missions = _d(raw)
    if _d(_d(missions.get("send")).get("running")):
        return "a mission is being sent"
    from planner_world import _messenger_out
    if _messenger_out(missions):
        return "a Diplomacy mission is out"
    return None


def _say(memory, notes: list, key: str, why: str, text: str, now) -> None:
    """A waiting swap's note: once a day, or when its reason changes."""
    if memory is None or not isinstance(now, int):
        notes.append(text)
        return
    ws = getattr(memory, "world_seen", None)
    if not isinstance(ws, dict):
        memory.world_seen = ws = {}
    said = ws.setdefault("swap_said", {})
    last = _d(said.get(key))
    if last.get("why") == why and isinstance(last.get("tick"), int) and 0 <= now - last["tick"] < TICKS_PER_DAY:
        return
    said[key] = {"why": why, "tick": now}
    for k in [k for k, v in said.items() if not isinstance(_d(v).get("tick"), int) or now - v["tick"] > 28 * TICKS_PER_DAY]:
        del said[k]
    notes.append(text)


def _refused(memory, p, s, now) -> bool:
    """The bridge refused this very swap lately: its back-off still runs."""
    if memory is None or not isinstance(now, int):
        return False
    return _refused_wait(memory, p, now, s.get("bridge_version")) is not None


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
    # (0.105.97) never a held killer into an office (B, 23 Nov: Fath Shemnish,
    # 2 kills and celled, made militia captain); lua/ai-nobles.lua passes them
    # over too, so a report from before this bridge is the only way one is named
    from planner_killers import held_killer_ids
    held = held_killer_ids(s)
    # the interim messenger out: any suitable free citizen will do
    if ms.get("interim") and ms.get("free_unit") is not None and ms.get("free_unit") not in held:
        busy = _messenger_busy(s, ms)
        p = Proposal("office_swap", {"type": "appoint", "office": "MESSENGER", "replace": True, "interim_out": True},
                     f"{ms.get('held_by') or 'an office holder'} doubles as messenger for now (they "
                     f"hold another office); {ms.get('free_name') or 'a free dwarf'} is free and "
                     "suitable: they take the messenger's post", 4)
        if busy:
            _say(memory, notes, "interim_out", busy,
                 f"{ms.get('held_by') or 'the interim messenger'} doubles as messenger; "
                 f"{ms.get('free_name') or 'a free dwarf'} could take over, once the messenger is back ({busy})", now)
        elif not _refused(memory, p, s, now):   # refused lately: the other swaps go on meanwhile
            proposals.append(p)
            return
    swap = _d(offices.get("swap"))
    for code in SWAP_ORDER:
        o = _d(swap.get(code))
        if not o or o.get("fixed") or o.get("cand_unit") is None or o.get("holder_unit") is None:
            continue
        if o.get("cand_unit") in held:
            continue
        hs, cs = int(o.get("holder_score") or 0), int(o.get("cand_score") or 0)
        need = swap_needed(hs, cfg)
        if cs < need or not cooled(code):
            continue
        busy = o.get("busy") or (_messenger_busy(s, ms) if code == "MESSENGER" else None)
        word = OFFICE_WORDS.get(code, code.lower())
        if busy:
            _say(memory, notes, f"better:{code}", str(busy),
                 f"{o.get('cand')} would make a far better {word} than {o.get('holder')} "
                 f"(skill {hs} -> {cs}); not now: {busy}", now)
            continue
        p = Proposal("office_swap", {"type": "appoint", "office": code, "replace": True,
                                     "margin_add": int(cfg["n1_swap_margin_add"]),
                                     "margin_factor": float(cfg["n1_swap_margin_factor"])},
                     f"{o.get('cand')} is far better suited as {word} than {o.get('holder')} "
                     f"(skill {hs} -> {cs}, {need} needed): {o.get('cand')} takes the post", 5)
        if _refused(memory, p, s, now):
            continue
        proposals.append(p)
        return
